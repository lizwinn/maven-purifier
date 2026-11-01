# SPDX-License-Identifier: MIT
#
# The recording extension (extension/), compiled against the Maven API
# jars of nixpkgs' Maven. The event spy API it uses is the same in every
# Maven 3 release, and Maven 3.9 runs on Java 8, so the classes target
# Java 8.
{
  stdenvNoCC,
  jdk_headless,
  maven,
  version,
}:
stdenvNoCC.mkDerivation {
  pname = "maven-purifier-extension";
  inherit version;
  src = ../../extension;
  nativeBuildInputs = [ jdk_headless ];
  buildPhase = ''
    runHook preBuild
    mkdir classes
    javac --release 8 -Xlint:-options -Xlint:-deprecation -d classes \
      -cp "${maven}/maven/lib/*" $(find src -name '*.java')
    cp -r resources/. classes/
    jar --create --file maven-purifier-extension.jar \
      --date=1980-01-01T00:00:02Z -C classes .
    runHook postBuild
  '';
  installPhase = ''
    runHook preInstall
    install -Dm644 maven-purifier-extension.jar $out/share/java/maven-purifier-extension.jar
    runHook postInstall
  '';
  meta.description = "Maven core extension that records the downloads of a maven-purifier lock run";
}
