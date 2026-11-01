// SPDX-License-Identifier: MIT
package example.multi.app;

import example.multi.core.Greeting;

public final class Main {
  private Main() {}

  public static void main(String[] args) {
    System.out.println(Greeting.greet(args.length > 0 ? args[0] : "world"));
  }
}
