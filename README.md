# maven-purifier

A command and a Nix library that make Nix the dependency and build backend
of a Maven build. Maven still plans the build. maven-purifier records the
files Maven downloads in a lockfile, and Nix builds the project from that
lockfile in its sandbox, offline. You commit the lockfile; you do not
commit generated Nix files.

maven-purifier is one of the [nix-purifiers](https://nix-purifiers.github.io).
Its design follows [sbt-purifier](https://github.com/nix-purifiers/sbt-purifier)
(formerly sbt-nix-backend): a lock run that records every download of the
build tool, a Nix library that builds from the lockfile, an interactive
mode on the locked downloads, and a publish step for what Nix built.

- **A lockfile.** `maven-purifier lock` writes `maven-purifier.lock.json`
  at the build root. It names every file the build downloads, Maven's own
  distribution and plugins included, and every artifact the build installs.
- **Sandboxed builds.** `buildMavenProject`, which the flake's overlay
  adds to a package set, turns a build and its lockfile into derivations.
  `packages.<artifactId>` holds the artifacts of a module in Maven layout.
- **Maven on the locked downloads.** `maven-purifier mvn` runs Maven
  offline against a local repository that Nix fills from the lockfile.
- **Deploying what Nix built.** `maven-purifier deploy` deploys the
  artifacts of the Nix build with the locked Maven, so nothing that is
  published was compiled outside the sandbox.

## Use

Lock the build from its root:

```zsh
nix run github:nix-purifiers/maven-purifier -- lock
```

Commit `maven-purifier.lock.json`. The flake's `overlays.default` adds
`buildMavenProject` to a package set, and a package written for
`callPackage` takes it by name:

```nix
# package.nix
{ buildMavenProject }:
(buildMavenProject { src = ./.; }).packages.app
```

```nix
{
  inputs.maven-purifier.url = "github:nix-purifiers/maven-purifier";
  inputs.nixpkgs.follows = "maven-purifier/nixpkgs";

  outputs = { nixpkgs, maven-purifier, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        overlays = [
          maven-purifier.overlays.default
          (final: prev: { app = final.callPackage ./package.nix { }; })
        ];
      };
    in
    {
      packages.${system}.app = pkgs.app;
    };
}
```

`nix build '.#app'` builds module `app`. The builder returns:

- `packages.<artifactId>`: the files the module installs, in Maven layout.
  `artifacts.<key>` names each file, where the key is
  `<artifactId>[-<classifier>].<extension>`, such as
  `packages.core.artifacts."core-sources.jar"`. The lockfile lists them,
  so Nix knows every output of the build at evaluation time, without
  building first.
- `build`: one build of the whole reactor, with every installed artifact.
- `deploy`: a script, `bin/maven-purifier-deploy --repository-id ID --url
  URL`, that deploys the files of every package with `deploy:deploy-file`.
- `repository`: the local repository of every locked download.
- `maven`: the Maven distribution the lock run used.

`nix/lib/build-maven-project.nix` documents the builder's arguments: `jdk`
(the default is the headless JDK of the major version the lock was made
with), `fetchurl` (for credentials or mirrors), `doCheck` (runs the tests),
`mavenFlags` and `srcFilter`.

To run Maven offline from the lock, for example while developing:

```zsh
nix run github:nix-purifiers/maven-purifier -- mvn clean install
```

### Editors

An editor that imports a Maven build, such as VS Code or Neovim through
jdtls, or IntelliJ IDEA, runs a Maven of its own. `maven-purifier
ide-settings` fetches the locked downloads and prints the path of
`.maven-purifier/ide-settings.xml`, which holds the lock's settings with
offline mode on and the locked repository as the local repository. Make
it the editor's Maven user settings, `java.configuration.maven.userSettings`
for jdtls or *User settings file* in IntelliJ IDEA, and the editor
resolves from the same files as `maven-purifier mvn`, without the network.

The Maven inside an editor has default plugin versions of its own, which
differ from those of the Maven that made the lock. We recommend pinning the
version of every plugin the build uses in `<pluginManagement>`, the
lifecycle plugins such as maven-compiler-plugin and maven-resources-plugin
included, as Maven's own guidance does. The editor's Maven then asks for
the locked versions. Without the pins, the editor reports that it could not
resolve a plugin in offline mode, such as maven-resources-plugin 3.4.0.

### Errors

Each common mistake fails with a message that says what went wrong and what
to run.

- When a pom.xml, `.mvn/` or the lock goals changed after locking, a Nix
  build fails at evaluation, saying that the build definition changed
  since the lock was made and to run `maven-purifier lock`.
  `maven-purifier mvn` says the same, and resolves online until the lock
  is renewed.
- When the build needs a dependency or plugin that the lock does not hold,
  Maven reports that it cannot reach the repository in offline mode.
  maven-purifier adds that the lock does not hold everything the build
  needs, and to run `maven-purifier lock --force` with the goals and `-P`
  options of the build.
- When someone edited the lockfile, a missing or misshaped field fails
  with the name of the field and asks for `maven-purifier lock --force`. A
  changed hash fails the fetch of that file with Nix's hash mismatch. A
  lockfile that is not JSON fails `maven-purifier mvn` with the parse error
  and the same command; for a Nix build, Nix's own JSON parser reports it.

### Deploying

To deploy, with the target from the root POM's `distributionManagement`
and the credentials from `~/.m2/settings.xml`:

```zsh
nix run github:nix-purifiers/maven-purifier -- deploy
```

`--repository-id ID --url URL` names another target.

## How the lock is made

`maven-purifier lock` copies the build to a temporary directory and runs
Maven there with an empty local repository and an empty home directory.
The default goals are `clean install`; pass others as arguments, with any
Maven options they need (`maven-purifier lock clean deploy -Prelease`).
The lock holds what those goals need, so lock the goals you run. The lock
run also runs the tests, so the lock holds what they need even when a Nix
build skips them.

Maven loads a small core extension of maven-purifier, which records every
file Maven Resolver downloads, with its URL, and every artifact the build
installs. After the run, every file in the local repository must be a
recorded download, an artifact the build installed, or Maven Resolver's
own bookkeeping, or the lock fails with the list of files that reached the
repository some other way.

Each source of dependencies reaches the lock this way:

- **Repositories declared in POMs, plugins and their dependencies,
  profiles, version ranges**: Maven Resolver downloads them during the
  run, and the extension records them. Profiles count as they were active
  in the lock run; `-P` options belong among the lock goals.
- **Repositories, mirrors and profiles in `settings.xml`**: the lock run
  uses `~/.m2/settings.xml`, or the file `--settings FILE` names. The lock
  records the settings without `<servers>`, `<proxies>`, `<localRepository>`
  and `<offline>`, and the sandboxed build and the interactive mode use the
  recorded settings. Their repository and mirror ids are then those of the
  lock run, which the names of metadata files in the local repository
  depend on.
- **Core extensions** (`.mvn/extensions.xml`): Maven resolves them before
  it loads the recording extension. The lock takes each of their URLs
  from Maven Resolver's tracking file, which names the repository a file
  came from.
- **Metadata files** (`maven-metadata.xml`), which version ranges,
  SNAPSHOTs and plugin prefixes read: their URLs serve new contents
  whenever a version is published, so the lock holds the contents the lock
  run read, inline.
- **SNAPSHOT dependencies**: the lock holds the timestamped files the lock
  run resolved, under both names Maven Resolver stores them under.
- **Files a plugin downloads itself**, outside Maven Resolver: Maven
  reports nothing about them, so the build declares them in
  `.mvn/maven-purifier.json`, each with its URL and its path in the local
  repository, where plugins that do this cache their downloads:

  ```json
  { "downloads": [ { "url": "https://…/node-v22.0.0-linux-x64.tar.gz",
                     "path": "com/github/eirslett/node/22.0.0/node-22.0.0-linux-x64.tar.gz" } ] }
  ```

  The lock run fetches each one into its local repository, and the lock
  holds it like any other download.
- **Maven itself**: the version the build's Maven wrapper names in
  `.mvn/wrapper/maven-wrapper.properties`, or else the Maven of the
  maven-purifier flake's nixpkgs. The distribution archive is locked like
  any other download, so the sandboxed build runs the same Maven.

A file of Maven Central lists both of its hosts, `repo.maven.apache.org`
and `repo1.maven.org`, so a Nix fetch falls back from one to the other.

`maven-purifier lock` locks again only when the build definition changed:
a `pom.xml`, anything under `.mvn/`, the goals, or the settings. `--force`
locks regardless.

The lock run copies the proxy from `https_proxy` and `http_proxy` into its
settings when the settings name none. When the proxy URL carries
credentials, the lock run allows Basic authentication to the proxy, which
Java disables by default, and downloads one file at a time, since Maven
3.9's HttpClient transport fails with 407 on concurrent downloads through
such a proxy.

## Decisions

- **The sandboxed build runs the locked goals with `deploy` replaced by
  `install`.** Maven refuses to deploy offline, and deploying is the job
  of the `deploy` script, which deploys exactly the files the Nix build
  made.
- **The local repository holds real files.** Maven 3.10 treats a file as
  absent when its real path differs from its path in the repository, so
  the build and the interactive mode copy the locked files rather than
  linking into the Nix store.
- **The prefix filter of Maven Resolver 2 is off in every run.** It reads
  a list of the groups each repository holds, which changes as groups are
  published, and offline it saves nothing.
- **A file of Maven Central is recorded under repo1.maven.org**, whichever
  of Central's hosts served it, with repo.maven.apache.org and Google's
  copy of Central as mirrors. `MAVEN_PURIFIER_CENTRAL_MIRROR` makes a lock
  run download through another copy of Central, which spares Central's
  rate limit, without changing the lock.
- **The interactive mode and the deploy step run on nixpkgs' JDK of the
  locked Java major version**, as the sandboxed build does, whatever
  `JAVA_HOME` names.
- **A stale lock fails a Nix build** at evaluation time, since the lock
  also names the build's outputs. `checkDefinition = false` turns the
  comparison off, and it applies only when `src` is a path.

## Limits

- **Credentials for the Nix fetch.** The lock run authenticates with the
  `<servers>` of the settings, which the lock does not record. A Nix
  build fetches the locked files of a private repository through the
  builder's `fetchurl` argument, for example nixpkgs' `fetchurl` with
  `netrcPhase`, or through Nix's own `netrc-file` setting, which the
  default fetcher and the interactive mode use.
- **Locking again moves SNAPSHOTs and version ranges.** A lock holds what
  they resolved to in its lock run. The next lock run resolves them
  afresh, which is what Maven does on every online build.
- **A file a plugin downloads without declaring it** fails the lock with
  its path listed, since Maven reports nothing about it; declaring it in
  `.mvn/maven-purifier.json` locks it.

## Acknowledgements

maven-purifier follows the design of sbt-purifier. The purifier idea was
inspired by nixcloud's [cargo (libnix)](https://github.com/nixcloud/cargo).
