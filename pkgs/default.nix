# SPDX-License-Identifier: MIT
{ callPackage, ... }:
let
  version = builtins.replaceStrings [ "\n" ] [ "" ] (builtins.readFile ../version.txt);
  extension = callPackage ./extension { inherit version; };
in
{
  # The Maven core extension that records what a lock run downloads.
  inherit extension;
  # The `maven-purifier` command, with `lock` and `mvn`.
  cli = callPackage ./cli { inherit version extension; };
}
