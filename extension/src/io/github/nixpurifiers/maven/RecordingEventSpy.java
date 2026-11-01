// SPDX-License-Identifier: MIT
package io.github.nixpurifiers.maven;

import java.io.IOException;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import javax.inject.Named;
import javax.inject.Singleton;
import org.apache.maven.eventspy.AbstractEventSpy;
import org.eclipse.aether.RepositoryEvent;
import org.eclipse.aether.artifact.Artifact;
import org.eclipse.aether.metadata.Metadata;
import org.eclipse.aether.repository.ArtifactRepository;
import org.eclipse.aether.repository.RemoteRepository;

/**
 * Records what a Maven build downloads and what it installs, for the lock run of maven-purifier.
 *
 * <p>Maven loads this class as a core extension when the lock run passes the extension jar in
 * {@code -Dmaven.ext.class.path}. Maven forwards every repository event of its resolver to the
 * event spies it loads. When the environment variable {@code MAVEN_PURIFIER_RECORD} names a file,
 * this spy appends one JSON object per line to it:
 *
 * <ul>
 *   <li>{@code {"event":"download","repository":…,"repositoryUrl":…,"url":…,"file":…}} for each
 *       artifact or metadata file the resolver downloaded, with the id and URL of the repository it
 *       came from, its own URL, and the file it was stored at in the local repository;
 *   <li>{@code {"event":"install","groupId":…,"artifactId":…,"version":…,"classifier":…,
 *       "extension":…,"file":…}} for each artifact the build installed into the local repository.
 * </ul>
 *
 * <p>Without the variable the spy does nothing.
 */
@Named("maven-purifier")
@Singleton
public class RecordingEventSpy extends AbstractEventSpy {

  private Writer out;

  @Override
  public void init(Context context) throws IOException {
    String record = System.getenv("MAVEN_PURIFIER_RECORD");
    if (record != null && !record.isEmpty()) {
      out =
          Files.newBufferedWriter(
              Paths.get(record),
              StandardCharsets.UTF_8,
              StandardOpenOption.CREATE,
              StandardOpenOption.APPEND);
    }
  }

  @Override
  public synchronized void onEvent(Object event) throws IOException {
    if (out == null || !(event instanceof RepositoryEvent)) {
      return;
    }
    RepositoryEvent e = (RepositoryEvent) event;
    if (e.getException() != null || e.getFile() == null) {
      return;
    }
    switch (e.getType()) {
      case ARTIFACT_DOWNLOADED:
        if (remote(e.getRepository()) != null) {
          download(remote(e.getRepository()), artifactPath(e.getArtifact()), e);
        }
        break;
      case METADATA_DOWNLOADED:
        if (remote(e.getRepository()) != null) {
          download(remote(e.getRepository()), metadataPath(e.getMetadata()), e);
        }
        break;
      case ARTIFACT_INSTALLED:
        install(e.getArtifact(), e);
        break;
      default:
        break;
    }
  }

  @Override
  public synchronized void close() throws IOException {
    if (out != null) {
      out.close();
      out = null;
    }
  }

  private static RemoteRepository remote(ArtifactRepository repository) {
    return repository instanceof RemoteRepository ? (RemoteRepository) repository : null;
  }

  private void download(RemoteRepository repository, String path, RepositoryEvent e)
      throws IOException {
    out.write(
        "{\"event\":\"download\",\"repository\":"
            + json(repository.getId())
            + ",\"repositoryUrl\":"
            + json(repository.getUrl())
            + ",\"url\":"
            + json(url(repository, path))
            + ",\"file\":"
            + json(e.getFile().getAbsolutePath())
            + "}\n");
    out.flush();
  }

  private void install(Artifact a, RepositoryEvent e) throws IOException {
    out.write(
        "{\"event\":\"install\",\"groupId\":"
            + json(a.getGroupId())
            + ",\"artifactId\":"
            + json(a.getArtifactId())
            + ",\"version\":"
            + json(a.getVersion())
            + ",\"classifier\":"
            + json(a.getClassifier())
            + ",\"extension\":"
            + json(a.getExtension())
            + ",\"file\":"
            + json(e.getFile().getAbsolutePath())
            + "}\n");
    out.flush();
  }

  private static String url(RemoteRepository repository, String path) {
    String base = repository.getUrl();
    return (base.endsWith("/") ? base : base + "/") + path;
  }

  // The path of an artifact in the Maven 2 repository layout. A SNAPSHOT
  // artifact's directory is its base version and its file name carries the
  // resolved timestamp version.
  private static String artifactPath(Artifact a) {
    StringBuilder path = new StringBuilder();
    path.append(a.getGroupId().replace('.', '/')).append('/');
    path.append(a.getArtifactId()).append('/');
    path.append(a.getBaseVersion()).append('/');
    path.append(a.getArtifactId()).append('-').append(a.getVersion());
    if (!a.getClassifier().isEmpty()) {
      path.append('-').append(a.getClassifier());
    }
    if (!a.getExtension().isEmpty()) {
      path.append('.').append(a.getExtension());
    }
    return path.toString();
  }

  // The path of a metadata file in the Maven 2 repository layout: the
  // group, artifact and version directories it applies to, each only when
  // set, then its type, such as maven-metadata.xml.
  private static String metadataPath(Metadata m) {
    StringBuilder path = new StringBuilder();
    if (!m.getGroupId().isEmpty()) {
      path.append(m.getGroupId().replace('.', '/')).append('/');
    }
    if (!m.getArtifactId().isEmpty()) {
      path.append(m.getArtifactId()).append('/');
    }
    if (!m.getVersion().isEmpty()) {
      path.append(m.getVersion()).append('/');
    }
    path.append(m.getType());
    return path.toString();
  }

  private static String json(String s) {
    StringBuilder b = new StringBuilder("\"");
    for (int i = 0; i < s.length(); i++) {
      char c = s.charAt(i);
      switch (c) {
        case '"':
          b.append("\\\"");
          break;
        case '\\':
          b.append("\\\\");
          break;
        default:
          if (c < 0x20) {
            b.append(String.format("\\u%04x", (int) c));
          } else {
            b.append(c);
          }
      }
    }
    return b.append('"').toString();
  }
}
