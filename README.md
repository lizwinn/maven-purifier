# maven-purifier

A command and a Nix library that make Nix the dependency and build backend
of a Maven build. Maven still plans the build. maven-purifier records the
files Maven downloads in a lockfile, Nix builds the project from that
lockfile in its sandbox, and after a prefetch Maven and the editor work with
the network cut off. The lockfile is the one file maven-purifier adds to a
repository.

maven-purifier is one of the [nix-purifiers](https://nix-purifiers.github.io),
and meets their [contract](https://github.com/nix-purifiers/purifier/blob/main/CONTRACT.md).

## Quickstart

maven-purifier runs on x86_64-linux and aarch64-linux.

Lock the build from its root, and commit the lockfile it writes,
`maven-purifier.lock.json`, to the repository. We recommend this setup, and
the builder and every command read the lockfile there by default:

```zsh
nix run github:nix-purifiers/maven-purifier -- lock
```

Build a module with Nix. The flake's `overlays.default` adds the builder
`buildMavenProject` to the package set:

```nix
{
  inputs.maven-purifier.url = "github:nix-purifiers/maven-purifier";
  inputs.nixpkgs.follows = "maven-purifier/nixpkgs";

  outputs = { nixpkgs, maven-purifier, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        overlays = [ maven-purifier.overlays.default ];
      };
      project = pkgs.buildMavenProject { src = ./.; };
    in
    {
      packages.${system}.app = project.packages.app;
      checks.${system}.tests = project.tests;
    };
}
```

`nix build '.#app'` builds module `app`. A package written for
`callPackage`, such as one in an overlay, takes the builder by name like any
other builder:

```nix
# package.nix
{ buildMavenProject }:
(buildMavenProject { src = ./.; }).packages.app
```

The builder's result has:

- `packages.<artifactId>`: the files the module installs, in Maven layout.
  `artifacts.<key>` names each file, where the key is
  `<artifactId>[-<classifier>].<extension>`, such as
  `packages.core.artifacts."core-sources.jar"`. The lockfile lists them, so
  Nix knows every output at evaluation time, without building first.
- `tests`: the build with its tests, whose output holds the test reports.
- `release`: every artifact the build installs, built with the tests
  skipped; `maven-purifier publish` deploys it.
- `fetches`: the download entries the build fetches, for SBOM, license and
  vulnerability tools.

The builder also takes `fetchers` (a company mirror or credentials go into
`fetchers.fetchurl`), `lockFile` (a lockfile outside `src`), `jdk` (the
default is nixpkgs' headless JDK of the Java major version the lock was made
with), `mavenFlags`, `srcFilter` and `checkDefinition`;
`nix/lib/build-maven-project.nix` documents them. `buildMavenProject.override`
replaces the packages the builder takes from the package set, such as
`javaPackages` or `stdenvNoCC`.

To deploy what Nix built, with the target from the root POM's
`distributionManagement` and the credentials from `~/.m2/settings.xml`:

```zsh
nix run github:nix-purifiers/maven-purifier -- publish
```

`--repository-id ID --url URL` names another target.

A build whose repository cannot hold the lockfile, such as a project you
package without being able to commit to it, can keep the lockfile outside
it. The builder then takes the lockfile as `lockFile`. Every command takes
`--lockfile FILE`, or reads the path from the environment variable
`MAVEN_PURIFIER_LOCKFILE`; `--lockfile` takes precedence. A dev shell can
set the variable to the path it passes to the builder as `lockFile`.

## Development loop

After `maven-purifier prefetch` (see [Working offline](#working-offline)), you run
Maven as usual: `mvn clean install`, `mvn test`, `mvn package`, `./mvnw
verify`. Maven resolves from the locked files, offline.

To add or upgrade a dependency or a plugin, edit the POM and lock again:

```zsh
nix run github:nix-purifiers/maven-purifier -- lock
nix run github:nix-purifiers/maven-purifier -- prefetch
```

A relock keeps what version ranges and SNAPSHOTs resolved to in the
previous lock: the lock run starts from the metadata files the lockfile
recorded. To move them to what the repositories hold now, update instead,
for every package or for the ones you name:

```zsh
nix run github:nix-purifiers/maven-purifier -- update
nix run github:nix-purifiers/maven-purifier -- update org.slf4j:slf4j-api
```

`maven-purifier update` locks with the goals that the lockfile recorded.
Maven keeps no lockfile of its own, so `maven-purifier.lock.json` is the one
file that `update` changes.

maven-purifier is a Maven core extension and a command, rather than a Maven
plugin with a goal. Maven Resolver reports each download only to core
extensions, which Maven loads before it reads the build. The command runs
Maven with the extension loaded.

`maven-purifier lock` copies the build to a temporary directory and runs
Maven there with an empty local repository and an empty home directory. The
default goals are `clean install`; pass others as arguments, with any Maven
options they need, such as `maven-purifier lock clean deploy -Prelease`.
The lock holds what those goals need, so lock the goals you run. The lock
run also runs the tests, so the lock holds what they need even when a Nix
build skips them. It locks again only when a `pom.xml`, anything under
`.mvn/`, the goals or the settings changed; `--force` locks regardless. A
relock of an unchanged build writes the same lockfile, byte for byte. It
keeps the recorded resolution of version ranges and SNAPSHOTs. It also
keeps the recorded Java major version, and runs on the nixpkgs JDK of that
version whatever `JAVA_HOME` names. A first lock runs on `JAVA_HOME`, or on
the JDK that maven-purifier's nixpkgs provides. To move to another Java
version, delete the lockfile and lock again.

## Working offline

```zsh
nix run github:nix-purifiers/maven-purifier -- prefetch
```

`maven-purifier prefetch` fetches everything the lockfile lists into the
Nix store and keeps it there with a garbage-collector root in
`.maven-purifier/` at the build root, where Maven reads the locked
repository. For a lockfile outside the build root, the root stays in the
build root rather than beside the lockfile. Besides what the build downloads, the lock holds what
day-to-day development asks for: every plugin the build declares, the source
jars of its dependencies, and the default plugins of the Maven inside the
editor. The command copies the locked repository to
`.maven-purifier/repository`, writes `.maven-purifier/settings.xml` with
offline mode on, and adds lines of its own at the end of
`.mvn/maven.config`, after the line `-Dmaven-purifier.prefetched=true`.
Maven reads that file for every build, so `mvn`, `./mvnw` and an editor
that reads it resolve from the locked files. The lines of `prefetch` take
no part in the build definition, and a lock run or a Nix build leaves them
out; delete them to resolve online again.

The lines also load maven-purifier's extension, which warns when a Maven of
another version runs: its default plugin versions differ from the locked
ones. The locked Maven is `.maven-purifier/bin/mvn`, and nixpkgs' JDK of the
locked Java major version is `.maven-purifier/jdk`. Put
`.maven-purifier/bin` on `PATH`, or use a Maven wrapper that names the
locked version.

## Editor

An editor that imports a Maven build, such as VS Code or Neovim through
jdtls, or IntelliJ IDEA, runs a Maven of its own. After a prefetch, make
`.maven-purifier/settings.xml` the editor's Maven user settings,
`java.configuration.maven.userSettings` for jdtls or *User settings file*
in IntelliJ IDEA, and the editor resolves from the locked files without the
network: dependencies, their source jars, and the plugins of its own Maven.

The lock holds the default plugins of the Maven that jdtls embeds, which
the lock run reads from the jdtls of maven-purifier's nixpkgs. An editor whose Maven has other
default plugin versions finds them missing offline, unless the build pins
the version of every plugin it uses in `<pluginManagement>`, as we
recommend; then every Maven asks for the locked versions.

## Troubleshooting

Each common mistake fails with a message that says what went wrong and what
to run.

- When a pom.xml, `.mvn/` or the lock goals changed after locking, a Nix
  build fails at evaluation, and `maven-purifier prefetch` and `publish`
  fail, saying that the build definition changed and to run
  `maven-purifier lock`.
- When a build needs a dependency or plugin that the lock does not hold, a
  Nix build fails with Maven's offline error and adds that the lock does
  not hold everything the build needs, and to run `maven-purifier lock
  --force` with the goals and `-P` options of the build. After a prefetch,
  Maven itself names the files it could not resolve and the same command.
- When someone edited the lockfile, it no longer matches its `lockHash`,
  and a Nix build and every command fail, saying so and asking for
  `maven-purifier lock --force`. A lockfile that is valid JSON but misses a
  field names the field. A lockfile that is not JSON fails the commands
  with the parse error and the same command; for a Nix build, Nix's own JSON
  parser reports it.
- When a lock run sees a file reach the local repository without a download
  that Maven reported, it fails with the list of such files: a plugin
  downloaded them itself. Declare them in `.mvn/maven-purifier.json`, as
  [Supported language repositories](#supported-language-repositories)
  shows.

## Supported language repositories

Each source of dependencies reaches the lock as follows.

- **Repositories declared in POMs, plugins and their dependencies,
  profiles and version ranges.** Maven Resolver downloads them during the
  lock run, and the extension records each file with its URL. Profiles
  count as they were active in the lock run; `-P` options belong among the
  lock goals.
- **Repositories, mirrors and profiles in `settings.xml`.** The lock run
  uses `~/.m2/settings.xml`, or the file that `--settings FILE` names. The
  lockfile records the settings without `<servers>`, `<proxies>`,
  `<localRepository>` and `<offline>`, and a Nix build and a prefetched
  Maven use the recorded settings, whose repository and mirror ids the names
  of metadata files depend on.
- **Core extensions** (`.mvn/extensions.xml`). Maven resolves them before it
  loads the recording extension, so the lock takes each of their URLs from
  Maven Resolver's tracking file, which names the repository a file came
  from.
- **Metadata files** (`maven-metadata.xml`), which version ranges,
  SNAPSHOTs and plugin prefixes read. Their URLs serve new contents
  whenever a version is published, so the lockfile holds the contents the
  lock run read.
- **SNAPSHOT dependencies.** The lockfile holds the timestamped files the
  lock run resolved, under both names Maven Resolver stores them under.
- **Files a plugin downloads itself**, outside Maven Resolver, such as the
  Node.js of frontend-maven-plugin. Maven reports nothing about them, so the
  build declares each with its URL and its path in the local repository, in
  `.mvn/maven-purifier.json`, and the lock run fetches it:

  ```json
  { "downloads": [ { "url": "https://…/node-v22.0.0-linux-x64.tar.gz",
                     "path": "com/github/eirslett/node/22.0.0/node-22.0.0-linux-x64.tar.gz" } ] }
  ```

- **Maven itself.** The version the build's Maven wrapper names in
  `.mvn/wrapper/maven-wrapper.properties`, or else the Maven of
  maven-purifier's nixpkgs. Its distribution archive is locked like any
  other download, so the sandboxed build runs the same Maven.
- **Repositories that need credentials.** The lock run authenticates with
  the `<servers>` of the settings, which the lockfile leaves out. A Nix
  build fetches their files through `fetchers.fetchurl`, such as nixpkgs'
  `fetchurl` with `netrcPhase`, or through Nix's own `netrc-file` setting.

A file of Maven Central is recorded under repo1.maven.org, whichever of
Central's hosts served it, and Nix fetches it from repo.maven.apache.org or
Google's copy of Central when repo1 fails. `MAVEN_PURIFIER_CENTRAL_MIRROR`
makes a lock run download through another copy of Central without changing
the lockfile. The lock run copies the proxy from `https_proxy` and
`http_proxy` into its settings when they name none.

The sandboxed build runs the locked goals with
`deploy` replaced by `install`, since Maven refuses to deploy offline, and
`release.publish` deploys exactly the files the Nix build made. The local
repository holds copies rather than links into the store, since Maven 3.10
treats a file as absent when its real path differs from its path in the
repository. Every run turns Maven Resolver 2's prefix filter off, since its
list of groups changes as groups are published and offline it saves
nothing. The jars of a Nix build get a fixed timestamp, so a rebuild gives
the same bytes.

## Examples

### Gson

[Gson](https://github.com/google/gson) is Google's JSON library, a Maven
build of several modules. Its `proto` module runs protoc, a native binary
that Maven downloads for the machine it runs on; the lock holds protoc for
both Linux systems.

From a clone of Gson, lock the build and prefetch it:

```zsh
nix run github:nix-purifiers/maven-purifier -- lock
nix run github:nix-purifiers/maven-purifier -- prefetch
```

Commit `maven-purifier.lock.json`. The locked Maven now builds and tests
Gson offline on the locked JDK, and an editor that reads
`.maven-purifier/settings.xml` imports it offline:

```zsh
JAVA_HOME=$PWD/.maven-purifier/jdk .maven-purifier/bin/mvn clean install
```

Add a `flake.nix` at the root of the clone to build Gson with Nix:

```nix
{
  inputs.maven-purifier.url = "github:nix-purifiers/maven-purifier";
  inputs.nixpkgs.follows = "maven-purifier/nixpkgs";

  outputs = { nixpkgs, maven-purifier, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        overlays = [ maven-purifier.overlays.default ];
      };
      gson = pkgs.buildMavenProject { src = ./.; };
    in
    {
      packages.${system} = {
        gson = gson.packages.gson;
        gson-extras = gson.packages.gson-extras;
        proto = gson.packages.proto;
        default = gson.release;
      };
      checks.${system}.tests = gson.tests;
    };
}
```

`nix build` builds every artifact Gson installs, `nix build '.#gson'` builds
the library alone, and `nix flake check` runs Gson's tests in the Nix
sandbox. After a change to a POM, lock and prefetch again.

## Credits

maven-purifier follows the design of
[sbt-purifier](https://github.com/nix-purifiers/sbt-purifier): a lock run
that records every download of the build tool, a Nix library that builds
from the lockfile, offline work on the locked downloads, and a publish step
for what Nix built. The purifier idea was inspired by nixcloud's
[cargo (libnix)](https://github.com/nixcloud/cargo).
