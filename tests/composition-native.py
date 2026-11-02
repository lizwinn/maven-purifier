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
reference = 'path:' + str(root) + '#checks.' + system + '.composition.producer'
with tempfile.TemporaryDirectory(prefix='maven-project-input-') as temporary:
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
        env=dict(os.environ, COMPOSITION_FLAKE=str(root), COMPOSITION_PROJECT=str(project)), check=True)
