// SPDX-License-Identifier: MIT
package example.multi.app;

import static org.junit.jupiter.api.Assertions.assertEquals;

import example.multi.core.Greeting;
import org.junit.jupiter.api.Test;

class MainTest {
  @Test
  void greetsCapitalized() {
    assertEquals("Hello, Maven!", Greeting.greet("maven"));
  }
}
