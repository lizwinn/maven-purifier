// SPDX-License-Identifier: MIT
package io.github.nixpurifiers.maven;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.Reader;
import java.util.Map;
import javax.inject.Inject;
import javax.inject.Named;
import javax.inject.Singleton;
import org.apache.maven.model.Model;
import org.apache.maven.model.building.ModelProcessor;
import org.apache.maven.model.io.ModelReader;
import org.apache.maven.model.locator.ModelLocator;
import org.eclipse.sisu.Priority;
import org.eclipse.sisu.Typed;

@Named("purifier")
@Singleton
@Priority(1000)
@Typed(ModelProcessor.class)
public final class ProjectedModelProcessor implements ModelProcessor {
  @Inject private ModelReader reader;
  @Inject private ModelLocator locator;

  @Override public File locatePom(File directory) { return locator.locatePom(directory); }

  private Model select(Model model, Map<String, ?> options, File source) throws IOException {
    return ProjectedVersions.select(model,
        ProjectedVersions.forSource(ProjectedVersions.source(options, source)), null);
  }

  @Override public Model read(File input, Map<String, ?> options) throws IOException {
    return select(reader.read(input, options), options, input);
  }
  @Override public Model read(Reader input, Map<String, ?> options) throws IOException {
    return select(reader.read(input, options), options, null);
  }
  @Override public Model read(InputStream input, Map<String, ?> options) throws IOException {
    return select(reader.read(input, options), options, null);
  }
}
