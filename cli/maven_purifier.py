# SPDX-License-Identifier: MIT
"""maven-purifier: lock a Maven build's downloads, build from them, deploy what Nix built.

  maven-purifier lock [--force] [--settings FILE] [GOAL...]
      Runs the build once with an empty local repository and records every
      file Maven downloads in maven-purifier.lock.json at the build root.
      The default goals are `clean install`. The lock holds what these
      goals need, so lock the goals you run; Maven options such as -P
      belong among them. The lock run uses FILE, or ~/.m2/settings.xml,
      and the lock records those settings without servers and proxies. The
      lock is renewed only when the build definition, the goals or the
      settings changed, unless --force is given.

  maven-purifier mvn [ARG...]
      Runs Maven offline from the locked downloads, which Nix fetches into
      .maven-purifier/ at the build root.

  maven-purifier deploy [--repository-id ID --url URL] [ARG...]
      Builds the artifacts with Nix and deploys them with the locked Maven
      and ~/.m2/settings.xml (for credentials). The default target is the
      root pom.xml's distributionManagement.

The package that installs this script sets the environment variables
MAVEN_PURIFIER_EXTENSION (the recording extension jar),
MAVEN_PURIFIER_NIX_LIB (the Nix library directory),
MAVEN_PURIFIER_NIXPKGS (the nixpkgs that `deploy` builds with),
MAVEN_PURIFIER_DEFAULT_MAVEN (the default Maven version) and
MAVEN_PURIFIER_DEFAULT_JAVA_HOME (the JDK used when JAVA_HOME is unset).
"""

import base64
import copy
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

LOCK_NAME = "maven-purifier.lock.json"
FORMAT_VERSION = 1
STATE_DIR = ".maven-purifier"
CENTRAL = "https://repo.maven.apache.org/maven2/"

# Files Maven Resolver writes into a local repository for its own
# bookkeeping. They are not downloads, and an offline build does not need
# them.
BOOKKEEPING = {"_remote.repositories", "resolver-status.properties", "maven-metadata-local.xml"}

# Maven Resolver stores the checksum files it fetched to validate a download
# beside the download. An offline build validates no checksums.
CHECKSUM_SUFFIXES = (".sha1", ".md5", ".sha256", ".sha512")

# Directories that never belong to the build definition or the build input.
SKIPPED_DIRS = {"target", ".git", STATE_DIR, ".idea", "node_modules"}


def fail(message):
    print(f"maven-purifier: {message}", file=sys.stderr)
    sys.exit(1)


def info(message):
    print(f"maven-purifier: {message}", file=sys.stderr)


def build_root():
    root = Path.cwd()
    if not (root / "pom.xml").is_file():
        fail(f"{root} has no pom.xml; run maven-purifier from the root of a Maven build")
    return root


def sri(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return "sha256-" + base64.b64encode(digest.digest()).decode()


def definition_files(root):
    """The files that define the build: every pom.xml, and .mvn/."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIPPED_DIRS and not d.startswith("result"))
        rel = Path(dirpath).relative_to(root)
        for name in sorted(filenames):
            if name == "pom.xml" or (rel.parts and rel.parts[0] == ".mvn"):
                files.append(rel / name)
    return files


def definition_hash(root, goals):
    digest = hashlib.sha256()
    digest.update(json.dumps(goals).encode() + b"\0")
    for rel in definition_files(root):
        digest.update(str(rel).encode() + b"\0")
        digest.update((root / rel).read_bytes() + b"\0")
    return "sha256-" + base64.b64encode(digest.digest()).decode()


def distribution_url(root):
    """The Maven distribution the build uses: the one the Maven wrapper names, or the default."""
    props = root / ".mvn" / "wrapper" / "maven-wrapper.properties"
    if props.is_file():
        for line in props.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "distributionUrl":
                return value.strip().replace("\\:", ":")
    version = os.environ["MAVEN_PURIFIER_DEFAULT_MAVEN"]
    return f"{CENTRAL}org/apache/maven/apache-maven/{version}/apache-maven-{version}-bin.tar.gz"


def download_path(url):
    """The tree path of a download that is not a Maven artifact, such as the Maven distribution."""
    parsed = urllib.parse.urlparse(url)
    marker = "/maven2/"
    if marker in parsed.path:
        return parsed.path.split(marker, 1)[1]
    return f"downloads/{parsed.netloc}{parsed.path}"


def prefetch(url):
    out = subprocess.run(
        ["nix", "store", "prefetch-file", "--json", "--hash-type", "sha256", url],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(out.stdout)
    return result["hash"], result["storePath"]


def unpack_maven(archive, dest):
    """Unpacks a Maven distribution archive and returns its bin/mvn."""
    dest.mkdir(parents=True, exist_ok=True)
    if str(archive).endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="tar")
    homes = [p for p in dest.iterdir() if (p / "bin" / "mvn").exists()]
    if len(homes) != 1:
        fail(f"{archive} does not unpack to a single Maven home")
    for script in (homes[0] / "bin").iterdir():
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)
    return homes[0] / "bin" / "mvn"


def java_home():
    home = os.environ.get("JAVA_HOME") or os.environ.get("MAVEN_PURIFIER_DEFAULT_JAVA_HOME")
    if not home:
        fail("set JAVA_HOME to the JDK that runs Maven")
    return home


def java_version(home):
    out = subprocess.run(
        [f"{home}/bin/java", "-XshowSettings:properties", "-version"],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in out.stderr.splitlines():
        key, sep, value = line.strip().partition(" = ")
        if sep and key == "java.version":
            return value
    fail(f"could not read the version of the JDK at {home}")


def proxy_with_credentials():
    for name in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        value = os.environ.get(name)
        if value and urllib.parse.urlparse(value).username:
            return True
    return False


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def env_proxies(qualify):
    """<proxy> elements for the proxy environment variables, which Maven ignores."""
    proxies = []
    no_proxy = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
    non_proxy = "|".join(h.strip() for h in no_proxy.split(",") if h.strip())
    for protocol in ("https", "http"):
        value = os.environ.get(f"{protocol}_proxy") or os.environ.get(f"{protocol.upper()}_PROXY")
        if not value:
            continue
        p = urllib.parse.urlparse(value)
        fields = {
            "id": f"env-{protocol}",
            "active": "true",
            "protocol": protocol,
            "host": p.hostname or "",
            "port": str(p.port or (443 if p.scheme == "https" else 80)),
        }
        if p.username:
            fields["username"] = urllib.parse.unquote(p.username)
        if p.password:
            fields["password"] = urllib.parse.unquote(p.password)
        if non_proxy:
            fields["nonProxyHosts"] = non_proxy
        proxy = ET.Element(qualify("proxy"))
        for name, text in fields.items():
            ET.SubElement(proxy, qualify(name)).text = text
        proxies.append(proxy)
    return proxies


def read_settings(source):
    """The settings the lock run uses, and the part of them the lock records.

    The lock run uses the given settings file, or the user's
    ~/.m2/settings.xml. The lock records them without <servers> and
    <proxies>, which hold credentials, and without <localRepository> and
    <offline>, which each run sets itself. The sandboxed build and the
    interactive mode use the recorded settings, so their repository and
    mirror ids are the ids of the lock run, which the names of metadata files
    in the local repository depend on.
    """
    if source is None:
        default = Path.home() / ".m2" / "settings.xml"
        source = default if default.is_file() else None
    if source is None:
        return ET.Element("settings"), None
    try:
        settings = ET.parse(source).getroot()
    except (OSError, ET.ParseError) as e:
        fail(f"cannot read the settings file {source}: {e}")
    if local_name(settings.tag) != "settings":
        fail(f"{source} is not a Maven settings file")
    namespace = settings.tag[1:].split("}")[0] if settings.tag.startswith("{") else ""
    if namespace:
        ET.register_namespace("", namespace)
    for child in list(settings):
        if local_name(child.tag) in ("localRepository", "offline"):
            settings.remove(child)
    recorded = copy.deepcopy(settings)
    for child in list(recorded):
        if local_name(child.tag) in ("servers", "proxies"):
            recorded.remove(child)
    return settings, ET.tostring(recorded, encoding="unicode") + "\n"


def write_run_settings(settings, path):
    """Writes the lock run's settings, adding the environment's proxy when they name none."""
    settings = copy.deepcopy(settings)
    namespace = settings.tag[1:].split("}")[0] if settings.tag.startswith("{") else ""

    def qualify(name):
        return f"{{{namespace}}}{name}" if namespace else name

    if not any(local_name(c.tag) == "proxies" for c in settings):
        proxies = env_proxies(qualify)
        if proxies:
            element = ET.SubElement(settings, qualify("proxies"))
            element.extend(proxies)
    path.write_text(ET.tostring(settings, encoding="unicode") + "\n")


def recorded_settings(lock_data, path):
    """Writes the settings a lock recorded, or empty settings."""
    path.write_text(lock_data.get("settings") or "<settings/>\n")


def copy_build(root, dest):
    def ignore(_dir, names):
        return [n for n in names if n in SKIPPED_DIRS or n.startswith("result")]

    shutil.copytree(root, dest, symlinks=True, ignore=ignore)


def read_record(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def artifact_key(install):
    classifier = f"-{install['classifier']}" if install["classifier"] else ""
    extension = f".{install['extension']}" if install["extension"] else ""
    return f"{install['artifactId']}{classifier}{extension}"


def tracked_repository(path):
    """The repository id that Maven Resolver's tracking file names for a file, or None."""
    tracking = path.parent / "_remote.repositories"
    if not tracking.is_file():
        return None
    for line in tracking.read_text().splitlines():
        if line.startswith("#"):
            continue
        name, sep, rest = line.partition(">")
        if sep and name == path.name:
            # Maven Resolver 2 writes the repository key as the id followed
            # by a digest of the repository, Maven Resolver 1 as the id.
            repository = re.sub(r"-[0-9a-f]{40}$", "", rest.rstrip("=").strip())
            if repository:
                return repository
    return None


def lock(args):
    force = False
    settings_source = None
    goals = []
    rest = iter(args)
    for arg in rest:
        if arg == "--force":
            force = True
        elif arg == "--settings":
            settings_source = Path(next(rest, "")).resolve()
        else:
            goals.append(arg)
    goals = goals or ["clean", "install"]
    root = build_root()
    lock_path = root / LOCK_NAME
    def_hash = definition_hash(root, goals)
    settings, settings_record = read_settings(settings_source)
    if not force and lock_path.is_file():
        try:
            old = json.loads(lock_path.read_text())
        except json.JSONDecodeError:
            old = {}
        if (
            old.get("version") == FORMAT_VERSION
            and old.get("definitionHash") == def_hash
            and old.get("settings") == settings_record
        ):
            info(f"{LOCK_NAME} is up to date; pass --force to lock again")
            return

    home = java_home()
    with tempfile.TemporaryDirectory(prefix="maven-purifier-lock-") as tmp:
        tmp = Path(tmp)
        url = distribution_url(root)
        info(f"fetching {url}")
        dist_hash, dist_store = prefetch(url)
        dist_path = download_path(url)
        mvn = unpack_maven(Path(dist_store), tmp / "maven")
        maven_version = mvn.parent.parent.name.removeprefix("apache-maven-")

        project = tmp / "project"
        copy_build(root, project)
        repo = tmp / "repository"
        repo.mkdir()
        (tmp / "home").mkdir()
        write_run_settings(settings, tmp / "settings.xml")
        record = tmp / "record.jsonl"

        env = dict(os.environ)
        env.update(
            {
                "JAVA_HOME": home,
                "HOME": str(tmp / "home"),
                "MAVEN_PURIFIER_RECORD": str(record),
            }
        )
        if proxy_with_credentials():
            # Java disables Basic authentication to a proxy by default, for
            # HTTPS tunnels and plain requests alike. Maven 3.9's Apache
            # HttpClient transport also fails with 407 on concurrent
            # downloads through a proxy that asks for credentials, so the
            # lock run downloads one file at a time.
            env["MAVEN_OPTS"] = " ".join(
                filter(
                    None,
                    [
                        env.get("MAVEN_OPTS", ""),
                        "-Djdk.http.auth.tunneling.disabledSchemes=",
                        "-Djdk.http.auth.proxying.disabledSchemes=",
                        "-Dmaven.artifact.threads=1",
                    ],
                )
            )
        command = [
            str(mvn),
            "-B",
            "-ntp",
            "-s",
            str(tmp / "settings.xml"),
            f"-Dmaven.repo.local={repo}",
            f"-Dmaven.ext.class.path={os.environ['MAVEN_PURIFIER_EXTENSION']}",
            f"-Duser.home={tmp / 'home'}",
            *goals,
        ]
        info(f"running Maven {maven_version} on a copy of the build: {' '.join(goals)}")
        if subprocess.run(command, cwd=project, env=env, check=False).returncode != 0:
            fail("the lock run failed; the lockfile is unchanged")

        events = read_record(record) if record.exists() else []
        downloads = {}
        repository_urls = {}
        for e in events:
            if e["event"] != "download":
                continue
            rel = Path(e["file"]).relative_to(repo).as_posix()
            downloads.setdefault(rel, e["url"])
            repository_urls.setdefault(e["repository"], e["repositoryUrl"])
            # Maven Resolver stores a timestamped SNAPSHOT under its base
            # version, which the event names, and also under the name it has
            # in the remote repository. Both copies are the same file.
            remote_name = e["url"].rsplit("/", 1)[-1]
            sibling = Path(rel).parent / remote_name
            if remote_name != Path(rel).name and (repo / sibling).is_file():
                downloads.setdefault(sibling.as_posix(), e["url"])

        installs = [e for e in events if e["event"] == "install"]
        installed = {Path(e["file"]).relative_to(repo).as_posix() for e in installs}
        # The version and artifact directories of the build's own modules,
        # where installing and deploying write metadata files of their own.
        module_dirs = set()
        for rel in installed:
            version_dir = Path(rel).parent
            module_dirs.update({version_dir.as_posix(), version_dir.parent.as_posix()})

        unrecorded = []
        for path in sorted(repo.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(repo).as_posix()
            if path.name in BOOKKEEPING or path.name.endswith(".lastUpdated"):
                continue
            if rel in downloads or rel in installed:
                continue
            if path.name.startswith("maven-metadata") and Path(rel).parent.as_posix() in module_dirs:
                continue
            _, dot, suffix = rel.rpartition(".")
            if dot and f".{suffix}" in CHECKSUM_SUFFIXES:
                continue
            # Maven resolves core extensions (.mvn/extensions.xml) before
            # it loads the recording extension. Maven Resolver still tracks
            # which repository each of those files came from, and a release
            # artifact has the same path in the remote repository as in the
            # local one.
            repository = tracked_repository(path)
            if repository is not None and repository in repository_urls and "SNAPSHOT" not in rel:
                base_url = str(repository_urls[repository])
                downloads[rel] = (base_url if base_url.endswith("/") else base_url + "/") + rel
                continue
            unrecorded.append(rel)
        if unrecorded:
            listing = "\n  ".join(unrecorded)
            fail(
                "these files reached the local repository without a recorded download, "
                f"so a sandboxed build could not have them:\n  {listing}"
            )

        # A metadata file lists the versions a repository holds, and its URL
        # serves new contents whenever a version is published, so a fetch
        # pinned by hash would break. The lock holds the contents the
        # resolver read. Every other download is immutable.
        artifacts = [{"path": dist_path, "url": url, "hash": dist_hash}]
        for rel, src in sorted(downloads.items()):
            if Path(rel).name.startswith("maven-metadata"):
                artifacts.append({"path": rel, "contents": (repo / rel).read_text()})
            else:
                artifacts.append({"path": rel, "url": src, "hash": sri(repo / rel)})
        artifacts.sort(key=lambda a: str(a["path"]))

        projects = {}
        for e in installs:
            key = (e["groupId"], e["artifactId"])
            p = projects.setdefault(
                key,
                {
                    "groupId": e["groupId"],
                    "artifactId": e["artifactId"],
                    "version": e["version"],
                    "artifacts": {},
                },
            )
            p["artifacts"][artifact_key(e)] = {
                "key": artifact_key(e),
                "classifier": e["classifier"],
                "extension": e["extension"],
                "path": Path(e["file"]).relative_to(repo).as_posix(),
            }
        names = {}
        for g, a in projects:
            names.setdefault(a, []).append(g)
        clashes = {a: gs for a, gs in names.items() if len(gs) > 1}
        if clashes:
            fail(f"several modules share an artifactId, which names a package: {clashes}")

        result = {
            "version": FORMAT_VERSION,
            "maven": {"version": maven_version, "distribution": dist_path},
            "javaVersion": java_version(home),
            "goals": goals,
            "settings": settings_record,
            "definitionHash": def_hash,
            "projects": [
                dict(p, artifacts=sorted(p["artifacts"].values(), key=lambda a: a["key"]))
                for _, p in sorted(projects.items())
            ],
            "artifacts": artifacts,
        }
        lock_path.write_text(json.dumps(result, indent=2) + "\n")
        modules = ", ".join(sorted(a for _, a in projects))
        info(f"wrote {LOCK_NAME} with {len(artifacts)} downloads; the build installs {modules}")


def realize(root, lock_data):
    """Fetches the locked downloads through Nix into a writable tree under .maven-purifier/."""
    state = root / STATE_DIR
    state.mkdir(exist_ok=True)
    entry = Path(os.environ["MAVEN_PURIFIER_NIX_LIB"]) / "realize-entry.nix"
    args = [str(entry), "--arg", "lockFile", str(root / LOCK_NAME)]
    try:
        subprocess.run(["nix-build", *args, "-A", "fetches", "--no-out-link"], check=True, stdout=subprocess.DEVNULL)
        # The manifest is a store file, not a derivation. Evaluating it in
        # read/write mode writes it to the store and gives its path, and
        # the GC root keeps it and every artifact it names alive.
        manifest_path = json.loads(
            subprocess.run(
                ["nix-instantiate", "--eval", "--read-write-mode", "--json", *args, "-A", "manifest"],
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            ).stdout
        )
        subprocess.run(
            ["nix-store", "--add-root", str(state / "gcroot"), "--realise", manifest_path],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        fail(f"Nix could not fetch the downloads that {LOCK_NAME} names")

    repo = state / "repository"
    stamp = state / "manifest"
    if not (stamp.exists() and stamp.read_text() == manifest_path):
        if repo.exists():
            shutil.rmtree(repo)
        manifest = json.loads(Path(manifest_path).read_text())
        for rel, source in manifest.items():
            dest = repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
        stamp.write_text(manifest_path)

    version = lock_data["maven"]["version"]
    maven_home = state / f"maven-{version}"
    if not maven_home.exists():
        archive = repo / lock_data["maven"]["distribution"]
        mvn = unpack_maven(archive.resolve(), maven_home)
    else:
        mvn = next(maven_home.glob("*/bin/mvn"))
    return repo, mvn


def run_mvn(args):
    root = build_root()
    lock_data = read_lock(root)
    repo, mvn = realize(root, lock_data)
    env = dict(os.environ)
    env.setdefault("JAVA_HOME", java_home())
    if lock_data.get("definitionHash") != definition_hash(root, lock_data["goals"]):
        info(f"the build definition changed since {LOCK_NAME} was made; Maven resolves online until `maven-purifier lock` renews it")
        os.execve(str(mvn), [str(mvn), *args], env)
    settings = root / STATE_DIR / "settings.xml"
    recorded_settings(lock_data, settings)
    result = subprocess.run(
        [str(mvn), "-o", "-s", str(settings), f"-Dmaven.repo.local={repo}", *args],
        env=env,
        check=False,
    )
    if result.returncode != 0:
        goals = " ".join(lock_data["goals"])
        info(
            f"Maven ran offline from the downloads locked for `{goals}`. If it reported a "
            "plugin or dependency that has not been downloaded, lock the goals you run: "
            "`maven-purifier lock --force <goal>...`"
        )
    sys.exit(result.returncode)


def read_lock(root):
    lock_path = root / LOCK_NAME
    if not lock_path.is_file():
        fail(f"{root} has no {LOCK_NAME}; run `maven-purifier lock` first")
    lock_data = json.loads(lock_path.read_text())
    if lock_data.get("version") != FORMAT_VERSION:
        fail(f"{LOCK_NAME} has lock format version {lock_data.get('version')}; run `maven-purifier lock --force`")
    return lock_data


def distribution_target(root, lock_data):
    """The repository id and URL of the root POM's distributionManagement."""
    try:
        pom = ET.parse(root / "pom.xml").getroot()
    except ET.ParseError as e:
        fail(f"cannot read {root / 'pom.xml'}: {e}")
    snapshot = any(p["version"].endswith("-SNAPSHOT") for p in lock_data["projects"])
    wanted = "snapshotRepository" if snapshot else "repository"
    for management in pom:
        if local_name(management.tag) != "distributionManagement":
            continue
        for repository in management:
            if local_name(repository.tag) != wanted:
                continue
            fields = {local_name(c.tag): (c.text or "").strip() for c in repository}
            if fields.get("id") and fields.get("url"):
                return fields["id"], fields["url"]
    fail(
        f"the root pom.xml declares no <distributionManagement><{wanted}>; "
        "pass --repository-id and --url"
    )


def deploy(args):
    repository_id = None
    url = None
    maven_args = []
    rest = iter(args)
    for arg in rest:
        if arg == "--repository-id":
            repository_id = next(rest, None)
        elif arg == "--url":
            url = next(rest, None)
        else:
            maven_args.append(arg)
    root = build_root()
    lock_data = read_lock(root)
    if url is None or repository_id is None:
        repository_id, url = distribution_target(root, lock_data)
    state = root / STATE_DIR
    state.mkdir(exist_ok=True)
    entry = Path(os.environ["MAVEN_PURIFIER_NIX_LIB"]) / "deploy-entry.nix"
    info("building the artifacts with Nix")
    try:
        script = subprocess.run(
            [
                "nix-build",
                str(entry),
                "--argstr",
                "src",
                str(root),
                "--arg",
                "nixpkgs",
                os.environ["MAVEN_PURIFIER_NIXPKGS"],
                "-o",
                str(state / "deploy"),
            ],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        fail("the Nix build of the artifacts failed")
    deploy_bin = Path(script) / "bin" / "maven-purifier-deploy"
    env = dict(os.environ)
    env.setdefault("JAVA_HOME", java_home())
    os.execve(
        str(deploy_bin),
        [str(deploy_bin), "--repository-id", repository_id, "--url", url, *maven_args],
        env,
    )


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return
    verb, args = sys.argv[1], sys.argv[2:]
    if verb == "lock":
        lock(args)
    elif verb == "mvn":
        run_mvn(args)
    elif verb == "deploy":
        deploy(args)
    else:
        fail(f"unknown command {verb!r}; the commands are `lock`, `mvn` and `deploy`")


if __name__ == "__main__":
    main()
