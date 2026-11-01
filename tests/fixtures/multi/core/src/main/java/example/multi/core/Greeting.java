// SPDX-License-Identifier: MIT
package example.multi.core;

import org.apache.commons.lang3.StringUtils;

public final class Greeting {
  private Greeting() {}

  public static String greet(String name) {
    return "Hello, " + StringUtils.capitalize(name) + "!";
  }
}
