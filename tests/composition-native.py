# SPDX-License-Identifier: MIT
"""Lock and use a Nix-provided JVM dependency through the ordinary Maven loop."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ET.register_namespace("", "http://maven.apache.org/POM/4.0.0")

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('cli', type=Path)
args = parser.parse_args()
cli = args.cli.resolve()
root = Path(__file__).resolve().parents[1]
system = subprocess.check_output(['nix', 'eval', '--impure', '--raw', '--expr', 'builtins.currentSystem'], text=True)
snapshot = json.loads(subprocess.check_output(['nix', 'flake', 'metadata', '--json',
    '--no-write-lock-file', 'path:'+str(root)], text=True))['path']
with tempfile.TemporaryDirectory(prefix='maven-project-input-') as temporary:
    subprocess.run(['nix-store', '--add-root', str(Path(temporary)/'source'), '--realise', snapshot], check=True)
    reference = 'path:' + snapshot + '#checks.' + system + '.composition.producer'
    project = Path(temporary) / 'project'
    shutil.copytree(root / 'tests/fixtures/multi', project)
    (project / 'maven-purifier.lock.json').unlink()
    original_poms = {path.relative_to(project): path.read_bytes() for path in project.rglob('pom.xml')}

    def run(*command):
        subprocess.run([str(part) for part in command], cwd=project, check=True)

    run(cli, 'lock', '--input', reference)
    data = json.loads((project / 'maven-purifier.lock.json').read_text())
    assert len(data['projectInputs']) == 1
    assert data['projectInputs'][0]['narHash'].startswith('sha256-')
    assert not any(entry['path'].startswith('org/apache/commons/commons-lang3/0.0.1-nix-')
                   for entry in data['downloads'])
    assert any(entry['path'].startswith('org/apache/commons/commons-lang3/') for entry in data['downloads']), \
        "the compiler plugin's separate dependencies must remain locked"
    run(cli, 'prefetch')
    run(project / '.maven-purifier/bin/mvn', '-B', 'clean', 'install')
    assert (project / 'core/target/core-1.0.0.jar').is_file()
    assert all((project / path).read_bytes() == contents for path, contents in original_poms.items())

    # The supplied library occurs only behind commons-text: no direct edge
    # or pre-existing management entry can accidentally make this pass.
    project = Path(temporary) / 'transitive-project'
    shutil.copytree(root / 'tests/fixtures/multi', project)
    (project / 'maven-purifier.lock.json').unlink()
    parent = project / 'pom.xml'
    model = ET.parse(parent)
    managed = model.find('.//{*}dependencyManagement/{*}dependencies')
    for dependency in list(managed):
        if dependency.findtext('{*}artifactId') == 'commons-lang3':
            managed.remove(dependency)
    model.write(parent, encoding='utf-8', xml_declaration=True)
    core = project / 'core/pom.xml'
    model = ET.parse(core)
    dependency = model.find('./{*}dependencies/{*}dependency')
    dependency.find('{*}artifactId').text = 'commons-text'
    ET.SubElement(dependency, '{http://maven.apache.org/POM/4.0.0}version').text = '1.13.0'
    model.write(core, encoding='utf-8', xml_declaration=True)
    source = project / 'core/src/main/java/example/multi/core/Greeting.java'
    source.write_text(source.read_text().replace('org.apache.commons.lang3.StringUtils',
        'org.apache.commons.text.WordUtils').replace('StringUtils.capitalize', 'WordUtils.capitalizeFully'))
    original_poms = {path.relative_to(project): path.read_bytes() for path in project.rglob('pom.xml')}
    run(cli, 'lock', '--input', reference)
    run(cli, 'prefetch')
    run(project / '.maven-purifier/bin/mvn', '-B', 'clean', 'install')
    assert all((project / path).read_bytes() == contents for path, contents in original_poms.items())
    expression = """
      let
        f = builtins.getFlake ("path:" + builtins.getEnv "COMPOSITION_FLAKE");
        p = import f.inputs.nixpkgs {
          system = builtins.currentSystem;
          overlays = [ f.overlays.default ];
        };
      in (p.maven-purifier.buildMavenProject {
        src = /. + builtins.getEnv "COMPOSITION_PROJECT";
      }).tests
    """
    subprocess.run(['nix', 'build', '--impure', '--no-link', '--print-build-logs', '--expr', expression],
        env=dict(os.environ, COMPOSITION_FLAKE=snapshot, COMPOSITION_PROJECT=str(project)), check=True)

    # Consume the full exported graph with ordinary Maven, without an adapter.
    environment = dict(os.environ, COMPOSITION_FLAKE=snapshot, COMPOSITION_PROJECT=str(project))
    repository = Path(temporary) / 'exported-repository'
    subprocess.run(['nix', 'build', '--impure', '--out-link', str(repository), '--expr',
        expression.replace('}).tests', '}).projections.maven')], env=environment, check=True)
    assert next((repository/'org/apache/commons/commons-text').glob('*/*-nix-*.jar')).is_file()
    tools = Path(temporary) / 'downstream-tools'
    tools_expression = r"""
      let f = builtins.getFlake ("path:" + builtins.getEnv "COMPOSITION_FLAKE");
          p = import f.inputs.nixpkgs { system = builtins.currentSystem; };
      in p.runCommand "maven-composition-downstream-tools" {} ''
        mkdir -p $out/bin
        ln -s ${p.maven}/bin/mvn $out/bin/mvn
        ln -s ${p.jdk} $out/jdk
      ''
    """
    subprocess.run(['nix', 'build', '--impure', '--out-link', str(tools), '--expr', tools_expression],
                   env=environment, check=True)
    downstream = Path(temporary) / 'downstream'
    source = downstream/'src/main/java/Downstream.java'
    source.parent.mkdir(parents=True)
    source.write_text("""public final class Downstream { public static void main(String[] args) throws Exception {
      String greeting = (String)Class.forName("example.multi.core.Greeting").getMethod("greet", String.class).invoke(null, "nix");
      if (!"Hello, Nix!".equals(greeting)) throw new AssertionError(greeting);
      for (String name : new String[]{"org.apache.commons.lang3.StringUtils", "org.apache.commons.text.WordUtils"}) {
        String location = Class.forName(name).getProtectionDomain().getCodeSource().getLocation().toString();
        if (!location.contains("-nix-")) throw new AssertionError(location);
      }
      System.out.println("ORDINARY MAVEN TRANSITIVE COMPOSITION PASSED");
    } }""")
    publication = next((repository/'example/multi/core').glob('*/*.pom'))
    (downstream/'pom.xml').write_text(f"""<project><modelVersion>4.0.0</modelVersion>
      <groupId>example</groupId><artifactId>downstream</artifactId><version>1</version>
      <properties><maven.compiler.release>21</maven.compiler.release></properties>
      <repositories><repository><id>projected</id><url>{repository.as_uri()}</url></repository></repositories>
      <dependencies><dependency><groupId>example.multi</groupId><artifactId>core</artifactId>
      <version>{publication.parent.name}</version></dependency></dependencies></project>""")
    plain = dict(os.environ, JAVA_HOME=str(tools/'jdk'))
    subprocess.run([str(tools/'bin/mvn'), '-B', '-Dmaven.repo.local='+str(Path(temporary)/'ordinary-m2'),
        'package', 'dependency:build-classpath', '-Dmdep.outputFile=classpath'], cwd=downstream, env=plain, check=True)
    subprocess.run([str(tools/'jdk/bin/java'), '-cp', str(downstream/'target/classes')+os.pathsep
        +(downstream/'classpath').read_text().strip(), 'Downstream'], cwd=downstream, env=plain, check=True)
