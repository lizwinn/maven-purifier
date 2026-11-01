# SPDX-License-Identifier: MIT
#
# The flake's checks. Every one builds in the sandbox; the only network
# access is the fixed-output fetches of locked artifacts.
{
  pkgs,
  # The flake's default package overlay, which adds buildMavenProject.
  overlay,
  cli,
  extension,
}:
let
  inherit (pkgs) lib;

  # Every fixture builds the way a consumer's package does: through
  # buildMavenProject of a package set the overlay applies to.
  withOverlay = pkgs.extend overlay;
  inherit (withOverlay) buildMavenProject;

  # A reactor of a parent POM and two modules. core depends on
  # commons-lang3 and installs a sources jar beside its jar; app depends on
  # core, and its JUnit 5 test runs in the build.
  multi = buildMavenProject {
    src = ./fixtures/multi;
    doCheck = true;
  };

  # The lock names the artifacts of each package, so a consumer reaches
  # them without building first. app runs from the jars of the packages
  # and the locked commons-lang3.
  multiRuns =
    pkgs.runCommand "maven-purifier-test-multi-runs"
      {
        nativeBuildInputs = [ multi.jdk ];
      }
      ''
        test -f ${multi.packages.core.artifacts."core-sources.jar"}
        test -f ${multi.packages.core.artifacts."core.pom"}
        cp=${multi.packages.app.artifacts."app.jar"}
        cp=$cp:${multi.packages.core.artifacts."core.jar"}
        cp=$cp:${multi.repository}/org/apache/commons/commons-lang3/3.17.0/commons-lang3-3.17.0.jar
        out_text=$(java -cp "$cp" example.multi.app.Main nix)
        if [ "$out_text" != "Hello, Nix!" ]; then
          echo "app printed '$out_text'" >&2
          exit 1
        fi
        touch $out
      '';

  # The deploy script deploys the artifacts Nix built, with the
  # maven-deploy-plugin of the lock, to a file: repository.
  multiDeploy = pkgs.runCommand "maven-purifier-test-multi-deploy" { } ''
    export HOME=$TMPDIR/home
    mkdir -p $HOME
    ${multi.deploy}/bin/maven-purifier-deploy --repository-id local --url file://$TMPDIR/deployed
    deployed=$TMPDIR/deployed/example/multi
    cmp ${multi.packages.core.artifacts."core-sources.jar"} $deployed/core/1.0.0/core-1.0.0-sources.jar
    cmp ${multi.packages.core.artifacts."core.jar"} $deployed/core/1.0.0/core-1.0.0.jar
    cmp ${multi.packages.app.artifacts."app.jar"} $deployed/app/1.0.0/app-1.0.0.jar
    cmp ${
      multi.packages.multi-parent.artifacts."multi-parent.pom"
    } $deployed/multi-parent/1.0.0/multi-parent-1.0.0.pom
    test -f $deployed/core/maven-metadata.xml
    touch $out
  '';

  # A build with every kind of dependency source; see the comment in its
  # pom.xml. Its lock took the SNAPSHOT from tests/snapshot-repository on
  # localhost:18080, so the check fetches those files from the committed
  # repository instead, by their locked hashes. Its test checks that a
  # class of every source is on the classpath, and that the core
  # extension's property reached a resource.
  snapshotUrl = "http://localhost:18080/";
  fetchFromSnapshotRepository =
    {
      name,
      urls,
      hash,
    }:
    let
      url = builtins.head urls;
    in
    if lib.hasPrefix snapshotUrl url then
      pkgs.runCommand name
        {
          outputHash = hash;
          outputHashMode = "flat";
        }
        ''
          cp ${./snapshot-repository}/${lib.removePrefix snapshotUrl url} $out
        ''
    else
      pkgs.fetchurl { inherit name urls hash; };
  sources = buildMavenProject {
    src = ./fixtures/sources;
    fetchurl = fetchFromSnapshotRepository;
    doCheck = true;
  };

  # A build whose Maven wrapper names Maven 3.9.11 as a zip: the lock run
  # and the sandboxed build both use that distribution.
  wrapper = buildMavenProject { src = ./fixtures/wrapper; };
  wrapperVersion =
    assert wrapper.maven.version == "3.9.11";
    pkgs.runCommand "maven-purifier-test-wrapper-version" { JAVA_HOME = wrapper.jdk.home; } ''
      ${wrapper.maven}/bin/mvn --version | grep -q 'Apache Maven 3.9.11'
      test -f ${wrapper.packages.wrapped.artifacts."wrapped.jar"}
      touch $out
    '';

  # The lock reader rejects a lock of another format version.
  lockVersion =
    let
      lockFile = builtins.toFile "maven-purifier.lock.json" (
        builtins.toJSON {
          version = 999;
          artifacts = [ ];
          projects = [ ];
        }
      );
      result = builtins.tryEval (import ../nix/lib/lock.nix { inherit lockFile; }).version;
    in
    assert !result.success;
    pkgs.runCommand "maven-purifier-test-lock-version" { } "touch $out";

  # The extension jar holds the class Maven loads and the index that names
  # it, and the command's Python parses.
  packaging =
    pkgs.runCommand "maven-purifier-test-packaging"
      {
        nativeBuildInputs = [
          pkgs.jdk_headless
          pkgs.python3
        ];
      }
      ''
        jar=${extension}/share/java/maven-purifier-extension.jar
        jar tf $jar | grep -qx 'io/github/nixpurifiers/maven/RecordingEventSpy.class'
        unzip_index=$(jar xf $jar META-INF/sisu/javax.inject.Named && cat META-INF/sisu/javax.inject.Named)
        test "$unzip_index" = io.github.nixpurifiers.maven.RecordingEventSpy
        python3 -c 'import py_compile, sys; py_compile.compile(sys.argv[1], cfile="cli.pyc", doraise=True)' \
          ${cli}/libexec/maven-purifier/maven_purifier.py
        ${cli}/bin/maven-purifier --help | grep -q 'maven-purifier lock'
        touch $out
      '';
in
{
  multi-app = multi.packages.app;
  multi-core = multi.packages.core;
  multi-runs = multiRuns;
  multi-deploy = multiDeploy;
  sources = sources.packages.sources;
  wrapper-version = wrapperVersion;
  lock-version = lockVersion;
  inherit packaging;
}
