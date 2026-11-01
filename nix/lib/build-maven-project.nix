# SPDX-License-Identifier: MIT
#
# buildMavenProject: the sandboxed build of a Maven build, from the lockfile
# that `maven-purifier lock` writes at the build root.
#
# The file is a package for callPackage: the first argument set is what it
# takes from the package set, and the result is the builder. The
# maven-purifier overlay (`overlays.default`) adds it to the package set as
# `buildMavenProject`, so a package written for callPackage takes it like
# any other dependency:
#
#   { buildMavenProject }: (buildMavenProject { src = ./.; }).packages.app
#
# and `buildMavenProject.override` replaces what it takes from the set. The
# builder returns
#
#   repository      the Maven local repository of every locked download
#   maven           the Maven distribution the lock run used
#   build           one build of the whole reactor, whose output holds
#                   every artifact the build installs, in Maven layout
#   packages.<id>   the artifacts of the module with artifactId <id>, in
#                   Maven layout; `artifacts.<key>` names each file, where
#                   <key> is <artifactId>[-<classifier>].<extension>
{
  lib,
  stdenvNoCC,
  runCommand,
  unzip,
  # The JDKs a build can run on; the default JDK of a build is the headless
  # one of the major version its lock was made with.
  javaPackages,
}:
{
  # The root of the Maven build.
  src,
  # The lockfile; the default is the one `maven-purifier lock` writes at the
  # build root.
  lockFile ? src + "/maven-purifier.lock.json",
  # The JDK that runs Maven.
  jdk ? null,
  # Replaces the built-in fetcher; see fetch.nix.
  fetchurl ? null,
  # Runs the build's tests. The lock run always runs them, so the lock
  # holds what they need either way.
  doCheck ? false,
  # Further arguments for Maven.
  mavenFlags ? [ ],
  # Filters the build root before it is copied into the store, as the
  # `filter` of builtins.path. The default leaves out build outputs, the
  # interactive mode's state and editor state.
  srcFilter ? null,
}:
let
  lock = import ./lock.nix { inherit lockFile; };

  defaultSrcFilter =
    path: type:
    let
      name = baseNameOf path;
    in
    !(
      (type == "directory" && (name == "target" || name == ".maven-purifier"))
      || name == ".git"
      || name == ".idea"
      || lib.hasPrefix "result" name
    );

  filteredSrc = builtins.path {
    path = src;
    name = "maven-source";
    filter = if srcFilter != null then srcFilter else defaultSrcFilter;
  };

  javaMajor = builtins.head (lib.splitString "." lock.javaVersion);
  defaultJdk =
    javaPackages.compiler."openjdk${javaMajor}".headless
      or (throw "maven-purifier: javaPackages has no openjdk${javaMajor} for the Java ${lock.javaVersion} the lock was made with; pass `jdk`.");
  jdk' = if jdk != null then jdk else defaultJdk;

  repository = import ./tree.nix {
    inherit runCommand lock fetchurl;
    name = "maven-repository";
  };

  maven = stdenvNoCC.mkDerivation {
    pname = "maven";
    inherit (lock.maven) version;
    src = "${repository}/${lock.maven.distribution}";
    nativeBuildInputs = lib.optional (lib.hasSuffix ".zip" lock.maven.distribution) unzip;
    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      cp -r . $out
      runHook postInstall
    '';
  };

  build = stdenvNoCC.mkDerivation {
    name = "maven-build";
    src = filteredSrc;
    nativeBuildInputs = [ jdk' ];
    dontConfigure = true;
    # The outputs are jars and POMs; fixup has nothing to patch, and it
    # must not rewrite them.
    dontFixup = true;
    buildPhase = ''
      runHook preBuild
      export HOME="$TMPDIR/home"
      export JAVA_HOME=${jdk'.home}
      mkdir -p "$HOME"
      # The local repository is a writable copy of real files. Maven
      # Resolver writes tracking files next to what it reads, and Maven
      # 3.10 treats a file as absent when its real path differs from its
      # path in the repository. A file without a tracking entry counts as
      # available offline.
      cp -rL --no-preserve=mode ${repository}/. "$TMPDIR/repository"
      echo '<settings/>' > "$TMPDIR/settings.xml"
      ${maven}/bin/mvn -o -B -ntp \
        -s "$TMPDIR/settings.xml" \
        -Dmaven.repo.local="$TMPDIR/repository" \
        -Duser.home="$HOME" \
        ${lib.optionalString (!doCheck) "-DskipTests"} \
        ${lib.escapeShellArgs mavenFlags} \
        ${lib.escapeShellArgs lock.goals} </dev/null
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      mkdir -p $out
      for path in ${
        lib.escapeShellArgs (lib.concatMap (p: map (a: a.path) p.artifacts) lock.projects)
      }; do
        if [ ! -f "$TMPDIR/repository/$path" ]; then
          echo "maven-purifier: the lock names $path, which this build did not install; run maven-purifier lock" >&2
          exit 1
        fi
        mkdir -p "$out/$(dirname "$path")"
        cp "$TMPDIR/repository/$path" "$out/$path"
      done
      runHook postInstall
    '';
    passthru = { inherit lock; };
  };

  mkPackage =
    project:
    let
      package =
        runCommand project.artifactId
          {
            passthru = {
              mavenProject = project;
              inherit (project) groupId artifactId version;
              # The files of the package by key, such as
              # artifacts."core-sources.jar". They are known from the lock
              # alone, before the package is built.
              artifacts = builtins.listToAttrs (
                map (a: {
                  name = a.key;
                  value = "${package}/${a.path}";
                }) project.artifacts
              );
            };
            meta.description = "${project.groupId}:${project.artifactId}:${project.version}, built by maven-purifier";
          }
          ''
            ${lib.concatMapStrings (a: ''
              mkdir -p "$out/${dirOf a.path}"
              cp ${build}/${a.path} "$out/${a.path}"
            '') project.artifacts}
          '';
    in
    package;

  packages = builtins.mapAttrs (_: mkPackage) lock.projectsByArtifactId;
in
{
  inherit
    lock
    repository
    maven
    build
    packages
    ;
  jdk = jdk';
}
