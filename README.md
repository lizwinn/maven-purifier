# maven-purifier

A command and a Nix library that make Nix the dependency and build backend
of a Maven build. Maven still plans the build. maven-purifier records the
files Maven downloads in a lockfile, and Nix builds the project from that
lockfile in its sandbox, offline. You commit the lockfile; you do not
commit generated Nix files.

maven-purifier is one of the [nix-purifiers](https://nix-purifiers.github.io).

- **A lockfile.** `maven-purifier lock` writes `maven-purifier.lock.json`
  at the build root. It names every file the build downloads by URL and
  SHA-256, Maven's own distribution and plugins included, and every
  artifact the build installs.
- **Sandboxed builds.** `buildMavenProject`, which the flake's overlay
  adds to a package set, turns a build and its lockfile into derivations.
  `packages.<artifactId>` holds the artifacts of a module in Maven layout.
- **Maven on the locked downloads.** `maven-purifier mvn` runs Maven
  offline against a local repository that Nix fills from the lockfile.

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
  `packages.core.artifacts."core-sources.jar"`. The names come from the
  lockfile, so a consumer can refer to them without building first.
- `build`: one build of the whole reactor, with every installed artifact.
- `repository`: the local repository of every locked download.
- `maven`: the Maven distribution the lock run used.

`nix/lib/build-maven-project.nix` documents the builder's arguments: `jdk`
(the default is the headless JDK of the major version the lock was made
with), `fetchurl` (for credentials or mirrors), `doCheck` (runs the tests),
`mavenFlags` and `srcFilter`.

## How the lock is made

`maven-purifier lock` copies the build to a temporary directory and runs
Maven there with an empty local repository, an empty home directory and a
settings file of its own. The default goals are `clean install`; pass
others as arguments (`maven-purifier lock clean verify`). The lock holds
what those goals need, so lock the goals you run.

Maven loads a small core extension of maven-purifier, which records the
URL of every file Maven Resolver downloads. After the run, every file in
the local repository must be a recorded download, an artifact the build
installed, or Maven Resolver's own bookkeeping, or the lock fails with the
list of files that reached the repository some other way. The lock run
also runs the tests, so the lock holds what they need even when a Nix
build skips them.

The Maven version is the one the build's Maven wrapper names in
`.mvn/wrapper/maven-wrapper.properties`, or else the Maven of the
maven-purifier flake's nixpkgs. The distribution archive is locked like
any other download, so the sandboxed build runs the same Maven.

`maven-purifier lock` locks again only when the build definition changed:
a `pom.xml`, anything under `.mvn/`, or the goals. `--force` locks
regardless.

The lock run ignores `~/.m2/settings.xml`, so that repository ids in the
lock run match the ones a sandboxed build sees. It copies the proxy from
`https_proxy` and `http_proxy` into its settings file.

## Limits

- Repositories that need credentials, and mirrors from user settings, are
  not supported yet.
- A plugin that downloads files outside Maven Resolver, such as a plugin
  that fetches Node.js, fails in the sandbox.
- SNAPSHOT dependencies and version ranges resolve at lock time, and the
  lock records the files they resolved to. Locking again may pick newer
  files.
- Publishing the artifacts Nix built is not supported yet.

## Acknowledgements

The purifier idea was inspired by nixcloud's
[cargo (libnix)](https://github.com/nixcloud/cargo).
