// SPDX-License-Identifier: MIT
package io.github.nixpurifiers.maven;

import java.io.IOException;
import java.nio.file.Path;
import java.util.Map;
import org.apache.maven.api.annotations.Nullable;
import org.apache.maven.api.di.Inject;
import org.apache.maven.api.di.Named;
import org.apache.maven.api.di.Priority;
import org.apache.maven.api.di.Singleton;
import org.apache.maven.api.di.Typed;
import org.apache.maven.api.model.Model;
import org.apache.maven.api.services.model.ModelProcessor;
import org.apache.maven.api.services.xml.ModelXmlFactory;
import org.apache.maven.api.services.xml.XmlReaderRequest;
import org.apache.maven.api.spi.ModelParser;
import org.apache.maven.impl.model.DefaultModelProcessor;

@Named("purifier")
@Singleton
@Priority(1000)
@Typed(ModelProcessor.class)
public final class ProjectedModelProcessor4 implements ModelProcessor {
  private final ModelProcessor delegate;

  @Inject public ProjectedModelProcessor4(ModelXmlFactory factory, @Nullable Map<String, ModelParser> parsers) {
    delegate = new DefaultModelProcessor(factory, parsers);
  }

  @Override public Path locateExistingPom(Path directory) { return delegate.locateExistingPom(directory); }

  @Override public Model read(XmlReaderRequest request) throws IOException {
    Model original = delegate.read(request);
    Path path = request.getPath() != null ? request.getPath() : original.getPomFile();
    org.apache.maven.model.Model bridge = new org.apache.maven.model.Model(original);
    return ProjectedVersions.select(bridge,
        ProjectedVersions.forSource(path == null ? null : path.toFile()), null).getDelegate();
  }
}
