// SPDX-License-Identifier: MIT
package example.sources;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class SourcesTest {
  @Test
  void usesEverySource() throws Exception {
    assertEquals("Lang3 txt Text snapshot LoggerFactory linux", Sources.describe());
  }
}
