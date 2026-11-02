# SPDX-License-Identifier: MIT
{
  pkgs,
  build,
  purifier,
  extension,
}:
let
  # Deliberately claims a native version outside the consumer's constraints.
  # Its sole source of authority is the Nix input, not Maven version ordering.
  runtimeModels = pkgs.runCommand "private-runtime-parent" { } ''
    dir=$out/example/purifier/metadata/private-parent/7
    mkdir -p "$dir"
    cat > "$dir/private-parent-7.pom" <<'POM'
    <project xmlns="http://maven.apache.org/POM/4.0.0">
      <modelVersion>4.0.0</modelVersion><groupId>example.purifier.metadata</groupId>
      <artifactId>private-parent</artifactId><version>7</version><packaging>pom</packaging>
    </project>
    POM
    echo '{"modules":[]}' > "$out/purifier-runtime-modules.json"
  '';
  producer =
    pkgs.runCommand "nix-built-commons-lang3"
      {
        nativeBuildInputs = [ pkgs.jdk_headless ];
        passthru.projections = purifier.jvmProjections {
          repository = producer;
          runtimeRepository = runtimeModels;
          inherit (pkgs) runCommand python3;
        };
      }
      ''
        mkdir -p classes
        cat > StringUtils.java <<'JAVA'
        package org.apache.commons.lang3;
        public final class StringUtils {
          public static boolean isEmpty(CharSequence value) {
            return value == null || value.length() == 0;
          }
          public static String capitalize(String value) {
            if (value == null || value.isEmpty()) return value;
            return Character.toUpperCase(value.charAt(0)) + value.substring(1);
          }
        }
        JAVA
        javac --release 8 -d classes StringUtils.java
        dir=$out/org/apache/commons/commons-lang3/0.0.1
        mkdir -p "$dir"
        jar --create --file "$dir/commons-lang3-0.0.1.jar" \
          --date=1980-01-01T00:00:02Z -C classes .
        cat > "$dir/commons-lang3-0.0.1.pom" <<'POM'
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modelVersion>4.0.0</modelVersion>
          <parent><groupId>example.purifier.metadata</groupId>
          <artifactId>private-parent</artifactId><version>7</version></parent>
          <groupId>org.apache.commons</groupId>
          <artifactId>commons-lang3</artifactId><version>0.0.1</version>
        </project>
        POM
      '';
  original = builtins.fromJSON (builtins.readFile ./fixtures/multi/maven-purifier.lock.json);
  unlocked = removeAttrs original [ "lockHash" ];
  withoutProvided = unlocked // {
    downloads = builtins.filter (
      entry: !(pkgs.lib.hasPrefix "org/apache/commons/commons-lang3/3.17.0/" entry.path)
    ) unlocked.downloads;
  };
  lockFile = builtins.toFile "maven-purifier.lock.json" (
    builtins.toJSON (
      withoutProvided
      // {
        lockHash = "sha256:${builtins.hashString "sha256" (builtins.toJSON withoutProvided)}";
      }
    )
  );
  consumer = build {
    src = ./fixtures/multi;
    inherit lockFile;
    projectDependencies = [ producer ];
  };
in
assert
  !builtins.any (
    entry: pkgs.lib.hasPrefix "org/apache/commons/commons-lang3/3.17.0/" entry.path
  ) consumer.fetches;
pkgs.runCommand "maven-nix-composition"
  {
    passthru = { inherit producer consumer; };
    nativeBuildInputs = [
      pkgs.python3
      consumer.jdk
    ];
  }
  ''
    # Both the tested build and its publication must use the Nix input.
    test -d ${consumer.tests}
    export CATALOG=${producer.projections.maven.catalog}
    export POM=${consumer.packages.core.artifacts."core.pom"}
    python - <<'PY'
    import json, os, xml.etree.ElementTree as ET
    catalog = json.load(open(os.environ['CATALOG']))
    selected = next(m['version'] for m in catalog['modules'] if m['name'] == 'commons-lang3')
    root = ET.parse(os.environ['POM']).getroot()
    ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
    dependency = root.find('m:dependencies/m:dependency', ns)
    assert dependency.findtext('m:version', namespaces=ns) == selected
    PY
    # A plain downstream Java invocation sees the produced jars and provider.
    provided=$(find ${producer.projections.maven} -name '*.jar')
    output=$(java -cp "${consumer.packages.app.artifacts."app.jar"}:${
      consumer.packages.core.artifacts."core.jar"
    }:$provided" example.multi.app.Main nix)
    test "$output" = 'Hello, Nix!'
    # Activate the inferred selections in a normal working tree. Source POMs
    # remain unchanged, and Maven must keep each module's original basedir.
    cp -r --no-preserve=mode ${./fixtures/multi} native
    mkdir -p native/.maven-purifier
    cp ${consumer.prefetch}/project-inputs.properties native/.maven-purifier/
    mkdir native/.maven-purifier/repository
    cp -r --no-preserve=mode ${consumer.prefetch}/repository/. native/.maven-purifier/repository/
    export HOME=$TMPDIR/home JAVA_HOME=${consumer.jdk.home}
    mkdir -p "$HOME"
    (
      cd native
      find . -name pom.xml -exec sha256sum {} + > "$TMPDIR/source-poms.before"
      ${consumer.maven}/bin/mvn -o -B -ntp \
        -Dmaven.ext.class.path=${extension}/share/java/maven-purifier-extension.jar \
        -Dmaven.repo.local="$PWD/.maven-purifier/repository" \
        -Dproject.build.outputTimestamp=1980-01-01T00:00:02Z clean install
      sha256sum -c "$TMPDIR/source-poms.before"
      test -f core/target/core-1.0.0.jar
      # Maven 4 has a separate model API and DI container. Resolve and compile
      # from the original POMs using that adapter too, without new downloads.
      rm -rf core/target app/target
      ${pkgs.maven_4}/bin/mvn -o -B -ntp -pl core -am \
        -Dmaven.ext.class.path=${extension}/share/java/maven-purifier-extension.jar \
        -Dmaven.repo.local="$PWD/.maven-purifier/repository" \
        org.apache.maven.plugins:maven-compiler-plugin:3.15.0:compile
      test -f core/target/classes/example/multi/core/Greeting.class
      sha256sum -c "$TMPDIR/source-poms.before"
      python - <<'PYTHON'
    import json, os, xml.etree.ElementTree as ET
    expected = next(m['version'] for m in json.load(open(os.environ['CATALOG']))['modules']
                    if m['name'] == 'commons-lang3')
    ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
    pom = ET.parse('.maven-purifier/repository/example/multi/core/1.0.0/core-1.0.0.pom')
    dep = pom.find('m:dependencies/m:dependency', ns)
    assert dep.findtext('m:version', namespaces=ns) == expected
    PYTHON
    )
    # An ordinary downstream Maven build needs no purifier plugin: its parent
    # and dependency descriptors must resolve the exact Nix-built components.
    cp -r ${./fixtures/multi/app} downstream
    chmod -R u+w downstream
    cp -r --no-preserve=mode ${consumer.repository} local-repository
    ${consumer.release.publish}/bin/maven-purifier-publish \
      --repository-id local --url "file://$TMPDIR/published"
    test -f "$TMPDIR/published/example/purifier/metadata/private-parent/7/private-parent-7.pom"
    rm -rf local-repository/example/purifier/metadata
    cp -r --no-preserve=mode "$TMPDIR/published"/. local-repository/
    ${pkgs.python3}/bin/python ${purifier.jvmRepositoryTool} \
      --rewrite-sources downstream --catalog ${consumer.projections.maven.catalog}
    export HOME=$TMPDIR/home JAVA_HOME=${consumer.jdk.home}
    mkdir -p "$HOME"
    cd downstream
    ${consumer.maven}/bin/mvn -o -B -ntp \
      -Dmaven.repo.local="$TMPDIR/local-repository" \
      -Dproject.build.outputTimestamp=1980-01-01T00:00:02Z clean install
    test -n "$(find target -name 'app-*-nix-*.jar')"
    touch $out
  ''
