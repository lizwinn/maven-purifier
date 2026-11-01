# SPDX-License-Identifier: MIT
#
# The `maven-purifier` library namespace. It holds nothing: the builder
# needs a package set, so it is the package `buildMavenProject` that the
# default package overlay adds.
{ ... }:
{

  overlay = final: prev: {
    maven-purifier = prev.maven-purifier or { };
  };

}
