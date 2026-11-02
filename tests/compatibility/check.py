# SPDX-License-Identifier: MIT
"""Compile, test, relock, prefetch and sandbox-build using a Maven release."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("version")
parser.add_argument("cli", type=Path)
parser.add_argument("jdk", type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
cli = str(args.cli.resolve())
env = dict(os.environ, JAVA_HOME=str(args.jdk.resolve()))
with tempfile.TemporaryDirectory(prefix="maven-compatibility-") as tmp:
    project = Path(tmp) / "project"
    shutil.copytree(Path(__file__).parent, project, ignore=shutil.ignore_patterns("check.py", "__pycache__"))
    wrapper = project / ".mvn/wrapper/maven-wrapper.properties"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(
        "distributionUrl=https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/"
        f"{args.version}/apache-maven-{args.version}-bin.tar.gz\n"
    )

    def run(*command, extra_env=None):
        subprocess.run(command, cwd=project, env=env | (extra_env or {}), check=True)

    run(cli, "lock")
    lockfile = project / "maven-purifier.lock.json"
    initial = lockfile.read_bytes()
    data = json.loads(initial)
    assert data["maven"]["version"] == args.version
    assert data["javaMajor"] == ("8" if args.version.startswith(("2.", "3.0.")) else "17")
    run(cli, "lock", "--force")
    assert lockfile.read_bytes() == initial, "a relock changed the pinned resolution"
    run(cli, "prefetch")
    run(str(project / ".maven-purifier/bin/mvn"), "-B", "clean", "install",
        extra_env={"JAVA_HOME": "/deliberately-absent-jdk"})
    # This also checks that prefetch's generated config doesn't stale the lock.
    run(cli, "prefetch")
    expression = """
      let
        f = builtins.getFlake ("path:" + builtins.getEnv "COMPAT_FLAKE");
        p = import f.inputs.nixpkgs {
          system = builtins.currentSystem;
          overlays = [ f.overlays.default ];
        };
      in (p.maven-purifier.buildMavenProject {
        src = /. + builtins.getEnv "COMPAT_PROJECT";
      }).tests
    """
    run("nix", "build", "--impure", "--no-link", "--print-build-logs", "--expr", expression,
        extra_env={"COMPAT_FLAKE": str(root), "COMPAT_PROJECT": str(project)})

    if not args.version.startswith('2.'):
        # Maven 3.0 needs the Plexus registration; newer Maven 3 and Maven 4
        # use their respective model APIs. Exercise inferred input selection
        # on the same JDK as the baseline compatibility test.
        project = Path(tmp) / 'project-input'
        shutil.copytree(Path(__file__).parent, project, ignore=shutil.ignore_patterns('check.py', '__pycache__'))
        wrapper = project / '.mvn/wrapper/maven-wrapper.properties'
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text('distributionUrl=https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/'
                           + args.version + '/apache-maven-' + args.version + '-bin.tar.gz\n')
        pom = project / 'pom.xml'
        pom.write_text(pom.read_text().replace('<dependencies>', '<dependencies><dependency>'
            '<groupId>org.apache.commons</groupId><artifactId>commons-lang3</artifactId>'
            '<version>99.0</version></dependency>'))
        source_pom = pom.read_bytes()
        (project / 'src/main/java/example/Hello.java').write_text(
            'package example; public final class Hello { public static int answer() { '
            'return org.apache.commons.lang3.StringUtils.capitalize("nix").equals("Nix") ? 42 : 0; } }\n')
        system = subprocess.check_output(['nix', 'eval', '--impure', '--raw', '--expr', 'builtins.currentSystem'], text=True)
        reference = 'path:' + str(root) + '#checks.' + system + '.composition.producer'
        run(cli, 'lock', '--input', reference)
        data = json.loads((project / 'maven-purifier.lock.json').read_text())
        assert len(data['projectInputs']) == 1
        assert not any('/commons-lang3/0.0.1-nix-' in entry['path'] for entry in data['downloads'])
        run(cli, 'prefetch')
        run(str(project / '.maven-purifier/bin/mvn'), '-B', 'clean', 'install')
        assert pom.read_bytes() == source_pom
        run('nix', 'build', '--impure', '--no-link', '--print-build-logs', '--expr', expression,
            extra_env={'COMPAT_FLAKE': str(root), 'COMPAT_PROJECT': str(project)})
