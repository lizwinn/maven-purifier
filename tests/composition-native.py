# SPDX-License-Identifier: MIT
"""Lock and use a Nix-provided JVM dependency through the ordinary Maven loop."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

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
