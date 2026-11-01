# SPDX-License-Identifier: MIT
#
# The `maven-purifier` command (cli/maven_purifier.py). Its wrapper names
# the recording extension, the Nix library that `maven-purifier mvn`
# evaluates, the Maven version a build without a Maven wrapper locks, and
# the JDK used when JAVA_HOME is unset.
{
  lib,
  stdenvNoCC,
  makeWrapper,
  python3,
  jdk_headless,
  maven,
  version,
  extension,
}:
stdenvNoCC.mkDerivation {
  pname = "maven-purifier";
  inherit version;
  src = lib.fileset.toSource {
    root = ../..;
    fileset = lib.fileset.unions [
      ../../cli
      ../../nix/lib
    ];
  };
  nativeBuildInputs = [ makeWrapper ];
  dontConfigure = true;
  dontBuild = true;
  installPhase = ''
    runHook preInstall
    install -Dm644 cli/maven_purifier.py $out/libexec/maven-purifier/maven_purifier.py
    mkdir -p $out/share/maven-purifier
    cp -r nix/lib $out/share/maven-purifier/nix
    makeWrapper ${python3.interpreter} $out/bin/maven-purifier \
      --add-flags $out/libexec/maven-purifier/maven_purifier.py \
      --set MAVEN_PURIFIER_EXTENSION ${extension}/share/java/maven-purifier-extension.jar \
      --set MAVEN_PURIFIER_NIX_LIB $out/share/maven-purifier/nix \
      --set MAVEN_PURIFIER_DEFAULT_MAVEN ${maven.version} \
      --set MAVEN_PURIFIER_DEFAULT_JAVA_HOME ${jdk_headless.home}
    runHook postInstall
  '';
  meta = {
    description = "Lock the downloads of a Maven build, and run Maven offline from them";
    mainProgram = "maven-purifier";
  };
}
