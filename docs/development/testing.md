# Testing

`nix flake check` runs every check in the Nix sandbox (`tests/default.nix`):

- `multi-app`, `multi-core`: the `multi` fixture, a parent POM with modules
  `core` and `app`, built from its lockfile with its tests.
- `multi-runs`: `app` runs from the jars of the packages and prints the
  expected greeting; `core` has its sources jar and POM.
- `wrapper-version`: the `wrapper` fixture names Maven 3.9.11 in its Maven
  wrapper, and its build runs that Maven.
- `lock-version`: the lock reader rejects another format version.
- `packaging`: the extension jar holds the event spy and its Sisu index,
  and the command's Python compiles.
- `treefmt`: the Nix files are formatted with nixfmt.

The fixtures' lockfiles are committed. Lock a fixture again after changing
its POMs, from the fixture directory:

```zsh
nix run ../../..#cli -- lock --force
```

The lock run needs the network. The interactive mode has no check of its
own yet; try it on a copy of a fixture with `maven-purifier mvn clean
install`.
