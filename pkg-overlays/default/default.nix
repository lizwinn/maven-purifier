# SPDX-License-Identifier: MIT
#
# The default package overlay. It adds the packages of pkgs/ under
# `pkgs.maven-purifier` (`.extension`, `.cli`). A consumer that lists this
# flake in `projects` holds it as `maven-purifier/default`, which its
# package sets apply by default. The builder is in the library, as
# `lib.maven-purifier.buildMavenProject`.
{ closure-lib, ... }:
{
  overlay = closure-lib.caisson.nixpkgs.mkPackagesOverlay ../../pkgs "maven-purifier";
}
