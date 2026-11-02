// SPDX-License-Identifier: MIT
package io.github.nixpurifiers.maven;

import java.io.File;
import java.io.IOException;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Properties;
import javax.inject.Named;
import javax.inject.Singleton;
import org.apache.maven.AbstractMavenLifecycleParticipant;
import org.apache.maven.MavenExecutionException;
import org.apache.maven.execution.MavenSession;
import org.apache.maven.model.Model;
import org.apache.maven.model.io.xpp3.MavenXpp3Writer;
import org.apache.maven.project.MavenProject;

/** Keep emitted POMs aligned with model selection while preserving source POMs and basedirs. */
@Named("purifier-project-inputs")
@Singleton
public final class ProjectedLifecycleParticipant extends AbstractMavenLifecycleParticipant {
  @Override public void afterProjectsRead(MavenSession session) throws MavenExecutionException {
    for (MavenProject project : session.getProjects()) {
      try {
        Properties versions = ProjectedVersions.forSource(project.getFile());
        if (versions.isEmpty()) continue;
        Model original = ProjectedVersions.select(project.getOriginalModel(), versions, project.getProperties());
        project.setOriginalModel(original);
        project.setModel(ProjectedVersions.select(project.getModel(), versions, project.getProperties()));
        File directory = new File(project.getBasedir(), ".maven-purifier");
        if (!directory.isDirectory() && !directory.mkdirs()) {
          throw new IOException("cannot create " + directory);
        }
        File selected = new File(directory, "project-pom.xml");
        try (Writer output = Files.newBufferedWriter(selected.toPath(), StandardCharsets.UTF_8)) {
          new MavenXpp3Writer().write(output, original);
        }
        try {
          // Unlike setFile, setPomFile keeps the original basedir.
          MavenProject.class.getMethod("setPomFile", File.class).invoke(project, selected);
        } catch (NoSuchMethodException olderMaven) {
          File sibling = new File(project.getBasedir(), ".maven-purifier-pom.xml");
          Files.copy(selected.toPath(), sibling.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
          project.setFile(sibling);
        } catch (ReflectiveOperationException error) {
          throw new IOException("cannot select publication POM", error);
        }
      } catch (IOException error) {
        throw new MavenExecutionException("maven-purifier: cannot apply Nix project inputs", error);
      }
    }
  }
}
