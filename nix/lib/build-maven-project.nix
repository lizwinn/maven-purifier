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
  writeText,
  writeShellScriptBin,
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
  # Compares the build definition with the one the lock was made from, and
  # fails at evaluation time when they differ. The comparison reads `src`
  # at evaluation time, so it applies only when `src` is a path; a `src`
  # that a derivation produces is not compared.
  checkDefinition ? true,
}:
let
  lock =
    let
      read = import ./lock.nix { inherit lockFile; };
      current = import ./definition-hash.nix {
        inherit src;
        inherit (read) goals;
      };
    in
    if checkDefinition && builtins.isPath src && read.definitionHash != current then
      throw "maven-purifier: the build definition (a pom.xml, .mvn/ or the goals) changed since ${toString lockFile} was made. Run `maven-purifier lock` at the build root to lock it again."
    else
      read;

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

  # The settings the lock run used, without servers and proxies, so that the
  # build sees the repository and mirror ids of the lock run.
  settings = writeText "settings.xml" (
    if lock.settings or null != null then lock.settings else "<settings/>\n"
  );

  # The goals of the build: the locked goals, with `deploy` replaced by
  # `install`. Deploying is the job of the `deploy` script below, which
  # deploys what this build made.
  buildGoals = map (goal: if goal == "deploy" then "install" else goal) lock.goals;

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
      maven_failed() {
        echo "maven-purifier: Maven failed offline. If it reports an artifact that has not been downloaded, the lock does not hold everything this build needs: run \`maven-purifier lock --force\` at the build root, with the goals and -P options you build with. If it reports a compile or test failure, the build itself failed." >&2
        exit 1
      }
      ${maven}/bin/mvn -o -B -ntp \
        -s ${settings} \
        -Dmaven.repo.local="$TMPDIR/repository" \
        -Duser.home="$HOME" \
        -Daether.remoteRepositoryFilter.prefixes=false \
        ${lib.optionalString (!doCheck) "-DskipTests"} \
        ${lib.escapeShellArgs mavenFlags} \
        ${lib.escapeShellArgs buildGoals} </dev/null || maven_failed
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

  # The maven-deploy-plugin version the lock holds, when its goals deployed;
  # otherwise Maven downloads this version when the deploy script runs.
  deployPluginVersion =
    let
      versions = lib.concatMap (
        a:
        let
          m = builtins.match "org/apache/maven/plugins/maven-deploy-plugin/([^/]+)/maven-deploy-plugin-[^/]+\\.jar" a.path;
        in
        lib.optional (m != null) (builtins.head m)
      ) lock.artifacts;
    in
    if versions != [ ] then lib.last (lib.naturalSort versions) else "3.1.4";

  # The arguments of deploy:deploy-file for a module: its main artifact (the
  # one without a classifier that is not the POM, or else the POM), its POM,
  # and every other artifact attached by classifier and type.
  deployArguments =
    project:
    let
      pom = lib.findFirst (
        a: a.classifier == "" && a.extension == "pom"
      ) (throw "maven-purifier: ${project.artifactId} installs no POM") project.artifacts;
      main = lib.findFirst (a: a.classifier == "" && a.extension != "pom") pom project.artifacts;
      attached = builtins.filter (a: a != pom && a != main) project.artifacts;
    in
    [
      "-Dfile=${build}/${main.path}"
      "-DpomFile=${build}/${pom.path}"
    ]
    ++ lib.optionals (attached != [ ]) [
      "-Dfiles=${lib.concatMapStringsSep "," (a: "${build}/${a.path}") attached}"
      "-Dclassifiers=${lib.concatMapStringsSep "," (a: a.classifier) attached}"
      "-Dtypes=${lib.concatMapStringsSep "," (a: a.extension) attached}"
    ];

  # Deploys the artifacts Nix built, module by module, with
  # deploy:deploy-file of the locked Maven:
  #
  #   maven-purifier-deploy --repository-id ID --url URL [MAVEN ARG...]
  #
  # Maven reads ~/.m2/settings.xml as usual, which is where the credentials
  # of the repository ID belong. The local repository is a copy of the
  # locked downloads, so the deploy plugin comes from the lock when the
  # lock run deployed.
  deploy = writeShellScriptBin "maven-purifier-deploy" ''
    set -euo pipefail
    repository_id=
    url=
    args=()
    while [ $# -gt 0 ]; do
      case "$1" in
        --repository-id) repository_id=$2; shift 2 ;;
        --url) url=$2; shift 2 ;;
        *) args+=("$1"); shift ;;
      esac
    done
    if [ -z "$repository_id" ] || [ -z "$url" ]; then
      echo "usage: maven-purifier-deploy --repository-id ID --url URL [MAVEN ARG...]" >&2
      exit 2
    fi
    export JAVA_HOME=''${JAVA_HOME:-${jdk'.home}}
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    cp -rL --no-preserve=mode ${repository}/. "$work/repository"
    cd "$work"
    deploy_file() {
      ${maven}/bin/mvn -B -ntp -Dmaven.repo.local="$work/repository" \
        -Daether.remoteRepositoryFilter.prefixes=false "''${args[@]}" \
        org.apache.maven.plugins:maven-deploy-plugin:${deployPluginVersion}:deploy-file \
        -DrepositoryId="$repository_id" -Durl="$url" -DgeneratePom=false "$@"
    }
    ${lib.concatMapStrings (p: ''
      echo "maven-purifier: deploying ${p.groupId}:${p.artifactId}:${p.version}" >&2
      deploy_file ${lib.escapeShellArgs (deployArguments p)}
    '') lock.projects}
  '';
in
{
  inherit
    lock
    repository
    maven
    build
    packages
    deploy
    ;
  jdk = jdk';
}
