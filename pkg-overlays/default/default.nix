# SPDX-License-Identifier: MIT
#
# The default package overlay. It adds one attribute to the package set, the
# scope `pkgs.maven-purifier` (pkgs/default.nix): the builder
# `buildMavenProject`, the command `cli` and the Maven extension
# `extension`. A package written for callPackage takes the scope by name. A
# consumer that lists this flake in `projects` holds the overlay as
# `maven-purifier/default`, which its package sets apply by default.
{ closure-lib, ... }:
{
  overlay = closure-lib.caisson.nixpkgs.mkPackagesOverlay ../../pkgs "maven-purifier";
}
