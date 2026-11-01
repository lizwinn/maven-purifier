// SPDX-License-Identifier: MIT
package io.github.nixpurifiers.maven;

import org.eclipse.aether.artifact.DefaultArtifact;
import org.eclipse.aether.metadata.DefaultMetadata;
import org.eclipse.aether.metadata.Metadata;
import org.eclipse.aether.repository.RemoteRepository;

/**
 * Unit tests of the URL-to-path logic of the recording extension. Run with the Maven Resolver API
 * on the class path; it exits non-zero on the first failure.
 */
public final class RecordingEventSpyTest {
  private RecordingEventSpyTest() {}

  private static void check(String expected, String actual) {
    if (!expected.equals(actual)) {
      throw new AssertionError("expected " + expected + " but got " + actual);
    }
  }

  public static void main(String[] args) {
    check(
        "org/apache/commons/commons-lang3/3.17.0/commons-lang3-3.17.0.jar",
        RecordingEventSpy.artifactPath(
            new DefaultArtifact("org.apache.commons:commons-lang3:jar:3.17.0")));
    check(
        "example/core/1.0/core-1.0-sources.jar",
        RecordingEventSpy.artifactPath(new DefaultArtifact("example:core:jar:sources:1.0")));
    check(
        "example/core/1.0/core-1.0.pom",
        RecordingEventSpy.artifactPath(new DefaultArtifact("example:core:pom:1.0")));
    // A timestamped SNAPSHOT lives in the directory of its base version.
    check(
        "example/snaplib/1.0-SNAPSHOT/snaplib-1.0-20261101.082447-1.jar",
        RecordingEventSpy.artifactPath(
            new DefaultArtifact("example:snaplib:jar:1.0-20261101.082447-1")));

    check(
        "org/slf4j/slf4j-api/maven-metadata.xml",
        RecordingEventSpy.metadataPath(
            new DefaultMetadata(
                "org.slf4j", "slf4j-api", "maven-metadata.xml", Metadata.Nature.RELEASE)));
    check(
        "example/snaplib/1.0-SNAPSHOT/maven-metadata.xml",
        RecordingEventSpy.metadataPath(
            new DefaultMetadata(
                "example",
                "snaplib",
                "1.0-SNAPSHOT",
                "maven-metadata.xml",
                Metadata.Nature.SNAPSHOT)));
    check(
        "org/apache/maven/plugins/maven-metadata.xml",
        RecordingEventSpy.metadataPath(
            new DefaultMetadata(
                "org.apache.maven.plugins", "maven-metadata.xml", Metadata.Nature.RELEASE)));

    RemoteRepository withSlash =
        new RemoteRepository.Builder("central", "default", "https://repo.maven.apache.org/maven2/")
            .build();
    RemoteRepository withoutSlash =
        new RemoteRepository.Builder("google", "default", "https://maven.google.com").build();
    check(
        "https://repo.maven.apache.org/maven2/a/b/1/b-1.jar",
        RecordingEventSpy.url(withSlash, "a/b/1/b-1.jar"));
    check("https://maven.google.com/a/b/1/b-1.jar", RecordingEventSpy.url(withoutSlash, "a/b/1/b-1.jar"));

    System.out.println("RecordingEventSpyTest: all checks passed");
  }
}
