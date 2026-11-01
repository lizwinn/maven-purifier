# Testing

`nix flake check` runs every check in the Nix sandbox (`tests/default.nix`):

- `multi-app`, `multi-core`: the `multi` fixture, a parent POM with modules
  `core` and `app`, built from its lockfile with its tests.
- `multi-runs`: `app` runs from the jars of the packages and prints the
  expected greeting; `core` has its sources jar and POM.
- `multi-deploy`: the deploy script deploys the Nix-built files of every
  module to a `file:` repository with the maven-deploy-plugin of the lock,
  and the deployed files are the built ones.
- `sources`: the `sources` fixture, with a dependency from every kind of
  source (see its `pom.xml`), builds offline and its test checks that a
  class of each is on the classpath.
- `sources-declared`: the download that `sources` declares in
  `.mvn/maven-purifier.json` is in the local repository.
- `wrapper-version`: the `wrapper` fixture names Maven 3.9.11 in its Maven
  wrapper, and its build runs that Maven.
- `lock-version`: the lock reader rejects another format version.
- `packaging`: the extension jar holds the event spy and its Sisu index,
  and the command's Python compiles.
- `treefmt`: the Nix files are formatted with nixfmt.

The CI workflow (`.github/workflows/check.yml`) also evaluates the checks
for every system, and covers the two parts that need the network or a Nix
installation: it locks a copy of `wrapper` again and requires the
downloads, modules and Maven of the committed lock, and it runs
`maven-purifier mvn clean install` offline on a copy of `multi`.

The fixtures' lockfiles are committed. Lock them again, from the
repository root, after changing a fixture or the lock tool:

```zsh
tests/relock-fixtures.sh
```

The script serves `tests/snapshot-repository` on localhost:18080, where
`sources` takes its SNAPSHOT from; the check fetches those files from the
committed repository instead. `tests/snapshot-producer` is the library in
that repository, deployed there once.
