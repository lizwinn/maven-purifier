// SPDX-License-Identifier: MIT
package io.github.nixpurifiers.maven;

import java.io.File;
import java.io.IOException;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.List;
import org.apache.maven.artifact.Artifact;
import org.apache.maven.artifact.repository.ArtifactRepository;
import org.apache.maven.plugin.AbstractMojo;
import org.apache.maven.plugin.MojoExecutionException;
import org.apache.maven.project.MavenProject;

/** Captures the effective reactor for Maven versions predating repository event spies. */
public final class LegacyRecorderMojo extends AbstractMojo {
  private List<MavenProject> projects;
  private MavenProject project;
  private ArtifactRepository localRepository;

  @Override
  public void execute() throws MojoExecutionException {
    String record = System.getenv("MAVEN_PURIFIER_RECORD");
    if (record == null) throw new MojoExecutionException("MAVEN_PURIFIER_RECORD is unset");
    try (Writer output = Files.newBufferedWriter(Paths.get(record), StandardCharsets.UTF_8,
        StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
      List<MavenProject> reactor = projects;
      if (reactor == null || reactor.isEmpty()) {
        reactor = new ArrayList<>();
        reactor.add(project);
      }
      for (MavenProject module : reactor) {
        for (ArtifactRepository repository : module.getRemoteArtifactRepositories()) {
          repository(output, repository);
        }
        for (ArtifactRepository repository : module.getPluginArtifactRepositories()) {
          repository(output, repository);
        }
        installed(output, module, "", "pom");
        if (!"pom".equals(module.getPackaging())) {
          Artifact main = module.getArtifact();
          installed(output, module, main.getClassifier(), main.getArtifactHandler().getExtension());
        }
        for (Artifact attached : module.getAttachedArtifacts()) {
          installed(output, module, attached.getClassifier(), attached.getArtifactHandler().getExtension());
        }
      }
    } catch (IOException error) {
      throw new MojoExecutionException("Cannot record the legacy Maven reactor", error);
    }
  }

  private static void repository(Writer output, ArtifactRepository repository) throws IOException {
    output.write("{\"event\":\"repository\",\"repository\":" + json(repository.getId())
        + ",\"repositoryUrl\":" + json(repository.getUrl()) + "}\n");
  }

  private void installed(Writer output, MavenProject module, String classifier, String extension)
      throws IOException {
    classifier = classifier == null ? "" : classifier;
    String name = module.getArtifactId() + "-" + module.getVersion()
        + (classifier.isEmpty() ? "" : "-" + classifier) + "." + extension;
    File file = new File(localRepository.getBasedir(), module.getGroupId().replace('.', '/') + "/"
        + module.getArtifactId() + "/" + module.getVersion() + "/" + name);
    if (!file.isFile()) return;
    output.write("{\"event\":\"install\",\"groupId\":" + json(module.getGroupId())
        + ",\"artifactId\":" + json(module.getArtifactId()) + ",\"version\":" + json(module.getVersion())
        + ",\"classifier\":" + json(classifier) + ",\"extension\":" + json(extension)
        + ",\"file\":" + json(file.getAbsolutePath()) + "}\n");
  }

  private static String json(String value) {
    return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + "\"";
  }
}
