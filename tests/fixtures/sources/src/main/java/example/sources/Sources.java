// SPDX-License-Identifier: MIT
package example.sources;

import androidx.annotation.NonNull;
import example.snapshot.Snap;
import java.io.IOException;
import java.io.InputStream;
import java.util.Properties;
import org.apache.commons.io.FilenameUtils;
import org.apache.commons.lang3.StringUtils;
import org.apache.commons.text.WordUtils;
import org.slf4j.LoggerFactory;

/** Uses a class from every dependency source of the build. */
public final class Sources {
  private Sources() {}

  @NonNull
  public static String describe() throws IOException {
    Properties build = new Properties();
    try (InputStream in = Sources.class.getResourceAsStream("build.properties")) {
      build.load(in);
    }
    return String.join(
        " ",
        StringUtils.capitalize("lang3"),
        FilenameUtils.getExtension("io.txt"),
        WordUtils.capitalize("text"),
        Snap.word(),
        LoggerFactory.class.getSimpleName(),
        build.getProperty("os.name"));
  }

  public static void main(String[] args) throws IOException {
    System.out.println(describe());
  }
}
