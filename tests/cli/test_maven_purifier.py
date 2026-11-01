# SPDX-License-Identifier: MIT
"""Unit tests of the lock tool's parsing and path logic (cli/maven_purifier.py).

Run with the module's path in MAVEN_PURIFIER_CLI:

    MAVEN_PURIFIER_CLI=cli/maven_purifier.py python3 -m unittest tests/cli/test_maven_purifier.py
"""

import importlib.util
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location("maven_purifier", os.environ["MAVEN_PURIFIER_CLI"])
assert spec is not None and spec.loader is not None
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)

CENTRAL = "https://repo.maven.apache.org/maven2/"
REPO1 = "https://repo1.maven.org/maven2/"


class TemporaryTree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path


GOOGLE = "https://maven-central.storage-download.googleapis.com/maven2/"


class Mirrors(unittest.TestCase):
    def test_central_files_get_the_canonical_url(self):
        path = "org/example/a/1/a-1.jar"
        for host in (REPO1, CENTRAL, GOOGLE):
            entry = mp.file_entry(path, host + path, "sha256-x")
            self.assertEqual(entry["url"], REPO1 + path)
            self.assertEqual(entry["mirrors"], [CENTRAL + path, GOOGLE + path])

    def test_other_repositories_have_no_mirrors(self):
        entry = mp.file_entry("a/b.jar", "https://example.org/a/b.jar", "sha256-x")
        self.assertEqual(entry, {"path": "a/b.jar", "url": "https://example.org/a/b.jar", "mirrors": [], "hash": "sha256-x"})

    def test_lock_run_mirror_of_central(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run.xml"
            with mock.patch.dict(os.environ, {"MAVEN_PURIFIER_CENTRAL_MIRROR": GOOGLE}, clear=True):
                mp.write_run_settings(ET.Element("settings"), run)
            mirror = ET.parse(run).getroot().find("mirrors/mirror")
            assert mirror is not None
            self.assertEqual(mirror.findtext("id"), "central")
            self.assertEqual(mirror.findtext("url"), GOOGLE)

    def test_settings_mirror_of_central_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run.xml"
            settings = ET.fromstring(
                "<settings><mirrors><mirror><id>corp</id><mirrorOf>*</mirrorOf>"
                "<url>https://repo.example</url></mirror></mirrors></settings>"
            )
            with mock.patch.dict(os.environ, {"MAVEN_PURIFIER_CENTRAL_MIRROR": GOOGLE}, clear=True):
                mp.write_run_settings(settings, run)
            self.assertNotIn(GOOGLE, run.read_text())


class DownloadPath(unittest.TestCase):
    def test_maven_layout_url(self):
        url = CENTRAL + "org/apache/maven/apache-maven/3.9.11/apache-maven-3.9.11-bin.zip"
        self.assertEqual(mp.download_path(url), "org/apache/maven/apache-maven/3.9.11/apache-maven-3.9.11-bin.zip")

    def test_other_url(self):
        self.assertEqual(mp.download_path("https://example.org/dist/maven.zip"), "downloads/example.org/dist/maven.zip")


class TrackedRepository(TemporaryTree):
    def test_resolver_2_key_with_digest(self):
        self.write(
            "a/1/_remote.repositories",
            "#NOTE: internal file\n#Sun Nov 01 2026\n"
            "a-1.jar>central-mirror-98c55166e0603ef6a71b8173dda7810dbd009613=\n",
        )
        self.assertEqual(mp.tracked_repository(self.root / "a/1/a-1.jar"), "central-mirror")

    def test_resolver_1_key(self):
        self.write("a/1/_remote.repositories", "a-1.pom>central=\n")
        self.assertEqual(mp.tracked_repository(self.root / "a/1/a-1.pom"), "central")

    def test_untracked_file(self):
        self.write("a/1/_remote.repositories", "a-1.pom>central=\n")
        self.assertIsNone(mp.tracked_repository(self.root / "a/1/a-1.jar"))
        self.assertIsNone(mp.tracked_repository(self.root / "b/1/b-1.jar"))


class Settings(TemporaryTree):
    SETTINGS = """<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0">
  <localRepository>/somewhere</localRepository>
  <offline>true</offline>
  <servers><server><id>corp</id><password>secret</password></server></servers>
  <proxies><proxy><id>p</id><host>proxy.example</host></proxy></proxies>
  <mirrors><mirror><id>corp</id><mirrorOf>*</mirrorOf><url>https://repo.example/maven</url></mirror></mirrors>
</settings>
"""

    def test_record_strips_credentials_and_local_state(self):
        settings, recorded = mp.read_settings(self.write("settings.xml", self.SETTINGS))
        self.assertNotIn("secret", recorded)
        self.assertNotIn("proxy.example", recorded)
        self.assertNotIn("/somewhere", recorded)
        self.assertNotIn("offline", recorded)
        self.assertIn("https://repo.example/maven", recorded)
        self.assertTrue(recorded.startswith('<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0">'))
        # The lock run itself keeps the servers and proxies.
        names = [mp.local_name(c.tag) for c in settings]
        self.assertIn("servers", names)
        self.assertIn("proxies", names)
        self.assertNotIn("localRepository", names)

    def test_no_settings(self):
        with mock.patch.object(Path, "home", return_value=self.root):
            settings, recorded = mp.read_settings(None)
        self.assertIsNone(recorded)
        self.assertEqual(settings.tag, "settings")

    def test_default_is_user_settings(self):
        self.write(".m2/settings.xml", "<settings><mirrors/></settings>")
        with mock.patch.object(Path, "home", return_value=self.root):
            _, recorded = mp.read_settings(None)
        self.assertIn("<mirrors", recorded)

    def test_malformed_settings_fail(self):
        with self.assertRaises(SystemExit):
            mp.read_settings(self.write("settings.xml", "<settings>"))

    def test_run_settings_take_the_environment_proxy(self):
        # A made-up proxy URL. gitleaks:allow
        env = {"https_proxy": "http://user%40x:p%3Ass@proxy.local:3128", "no_proxy": "localhost,127.0.0.1"}  # gitleaks:allow
        with mock.patch.dict(os.environ, env, clear=True):
            mp.write_run_settings(ET.Element("settings"), self.root / "run.xml")
        proxy = ET.parse(self.root / "run.xml").getroot().find("proxies/proxy")
        assert proxy is not None
        self.assertEqual(proxy.findtext("host"), "proxy.local")
        self.assertEqual(proxy.findtext("port"), "3128")
        self.assertEqual(proxy.findtext("username"), "user@x")
        self.assertEqual(proxy.findtext("password"), "p:ss")
        self.assertEqual(proxy.findtext("nonProxyHosts"), "localhost|127.0.0.1")

    def test_run_settings_keep_their_own_proxy(self):
        settings, _ = mp.read_settings(self.write("settings.xml", self.SETTINGS))
        with mock.patch.dict(os.environ, {"https_proxy": "http://other:1"}, clear=True):
            mp.write_run_settings(settings, self.root / "run.xml")
        text = (self.root / "run.xml").read_text()
        self.assertIn("proxy.example", text)
        self.assertNotIn("other", text)

    def test_proxy_with_credentials(self):
        with mock.patch.dict(os.environ, {"https_proxy": "http://u:p@h:1"}, clear=True):
            self.assertTrue(mp.proxy_with_credentials())
        with mock.patch.dict(os.environ, {"https_proxy": "http://h:1"}, clear=True):
            self.assertFalse(mp.proxy_with_credentials())


class IdeSettings(TemporaryTree):
    def test_offline_on_the_locked_repository(self):
        lock = {"settings": '<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0"><mirrors/></settings>\n'}
        mp.ide_settings(lock, self.root / "repository", self.root / "ide.xml")
        settings = ET.parse(self.root / "ide.xml").getroot()
        ns = "{http://maven.apache.org/SETTINGS/1.2.0}"
        self.assertEqual(settings.findtext(f"{ns}localRepository"), str(self.root / "repository"))
        self.assertEqual(settings.findtext(f"{ns}offline"), "true")
        self.assertIsNotNone(settings.find(f"{ns}mirrors"))

    def test_without_recorded_settings(self):
        mp.ide_settings({"settings": None}, self.root / "repository", self.root / "ide.xml")
        settings = ET.parse(self.root / "ide.xml").getroot()
        self.assertEqual(settings.findtext("offline"), "true")


class ArtifactKey(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(mp.artifact_key({"artifactId": "core", "classifier": "", "extension": "jar"}), "core.jar")
        self.assertEqual(
            mp.artifact_key({"artifactId": "core", "classifier": "sources", "extension": "jar"}), "core-sources.jar"
        )


class DefinitionHash(TemporaryTree):
    def setUp(self):
        super().setUp()
        self.write("pom.xml", "<project/>")
        self.write("core/pom.xml", "<project><artifactId>core</artifactId></project>")
        self.write(".mvn/extensions.xml", "<extensions/>")
        self.write("core/src/Main.java", "class Main {}")

    def test_files(self):
        self.assertEqual(mp.definition_files(self.root), [".mvn/extensions.xml", "core/pom.xml", "pom.xml"])

    def test_skips_build_outputs(self):
        before = mp.definition_hash(self.root, ["install"])
        self.write("target/pom.xml", "<generated/>")
        self.write("core/target/classes/pom.xml", "<generated/>")
        self.write("result/pom.xml", "<generated/>")
        self.write("core/src/Main.java", "class Main { int x; }")
        self.assertEqual(mp.definition_hash(self.root, ["install"]), before)

    def test_changes_with_definition_and_goals(self):
        before = mp.definition_hash(self.root, ["install"])
        self.assertNotEqual(mp.definition_hash(self.root, ["clean", "install"]), before)
        self.write("core/pom.xml", "<project><artifactId>core2</artifactId></project>")
        self.assertNotEqual(mp.definition_hash(self.root, ["install"]), before)

    def test_known_value(self):
        # The text it hashes, which nix/lib/definition-hash.nix builds too.
        import hashlib

        def h(text):
            return hashlib.sha256(text.encode()).hexdigest()

        text = (
            "goals clean install\n"
            f".mvn/extensions.xml {h('<extensions/>')}\n"
            f"core/pom.xml {h('<project><artifactId>core</artifactId></project>')}\n"
            f"pom.xml {h('<project/>')}\n"
        )
        self.assertEqual(mp.definition_hash(self.root, ["clean", "install"]), "sha256:" + h(text))


class DistributionUrl(TemporaryTree):
    def test_wrapper_properties(self):
        self.write(
            ".mvn/wrapper/maven-wrapper.properties",
            "wrapperVersion=3.3.2\ndistributionUrl=https\\://repo.maven.apache.org/maven2/org/apache/maven/"
            "apache-maven/3.9.11/apache-maven-3.9.11-bin.zip\n",
        )
        self.assertEqual(
            mp.distribution_url(self.root),
            CENTRAL + "org/apache/maven/apache-maven/3.9.11/apache-maven-3.9.11-bin.zip",
        )

    def test_default(self):
        with mock.patch.dict(os.environ, {"MAVEN_PURIFIER_DEFAULT_MAVEN": "3.10.0"}):
            self.assertEqual(
                mp.distribution_url(self.root),
                CENTRAL + "org/apache/maven/apache-maven/3.10.0/apache-maven-3.10.0-bin.tar.gz",
            )


class DeclaredDownloads(TemporaryTree):
    def declare(self, downloads):
        self.write(".mvn/maven-purifier.json", json.dumps({"downloads": downloads}))

    def test_none(self):
        self.assertEqual(mp.declared_downloads(self.root), [])

    def test_valid(self):
        self.declare([{"url": "https://example.org/x.tgz", "path": "a/b/x.tgz"}])
        self.assertEqual(mp.declared_downloads(self.root), [{"url": "https://example.org/x.tgz", "path": "a/b/x.tgz"}])

    def test_invalid(self):
        for downloads in (
            [{"url": "https://example.org/x.tgz"}],
            [{"url": "https://example.org/x.tgz", "path": "/abs/x.tgz"}],
            [{"url": "https://example.org/x.tgz", "path": "../x.tgz"}],
        ):
            self.declare(downloads)
            with self.assertRaises(SystemExit):
                mp.declared_downloads(self.root)


class DistributionTarget(TemporaryTree):
    POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <distributionManagement>
    <repository><id>releases</id><url>https://repo.example/releases</url></repository>
    <snapshotRepository><id>snapshots</id><url>https://repo.example/snapshots</url></snapshotRepository>
  </distributionManagement>
</project>
"""

    def test_release_and_snapshot(self):
        self.write("pom.xml", self.POM)
        release = {"projects": [{"version": "1.0"}]}
        snapshot = {"projects": [{"version": "1.0-SNAPSHOT"}]}
        self.assertEqual(mp.distribution_target(self.root, release), ("releases", "https://repo.example/releases"))
        self.assertEqual(mp.distribution_target(self.root, snapshot), ("snapshots", "https://repo.example/snapshots"))

    def test_missing(self):
        self.write("pom.xml", "<project/>")
        with self.assertRaises(SystemExit):
            mp.distribution_target(self.root, {"projects": [{"version": "1.0"}]})


class ReadLock(TemporaryTree):
    def test_malformed_lock(self):
        self.write("maven-purifier.lock.json", "{ not json")
        with self.assertRaises(SystemExit):
            mp.read_lock(self.root)

    def test_wrong_version(self):
        self.write("maven-purifier.lock.json", json.dumps({"version": 999}))
        with self.assertRaises(SystemExit):
            mp.read_lock(self.root)

    def test_missing_lock(self):
        with self.assertRaises(SystemExit):
            mp.read_lock(self.root)


if __name__ == "__main__":
    unittest.main()
