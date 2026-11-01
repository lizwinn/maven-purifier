# SPDX-License-Identifier: MIT
#
# The default package overlay. It adds the packages of pkgs/ under
# `pkgs.maven-purifier` (`.extension`, `.cli`), and the builder
# `pkgs.buildMavenProject` (nix/lib/build-maven-project.nix) beside them,
# where nixpkgs keeps its own builders, so a package written for
# callPackage takes it by name. A consumer that lists this flake in
# `projects` holds it as `maven-purifier/default`, which its package sets
# apply by default.
{ closure-lib, ... }:
let
  packages = closure-lib.caisson.nixpkgs.mkPackagesOverlay ../../pkgs "maven-purifier";
in
{
  overlay =
    final: prev:
    packages final prev
    // {
      buildMavenProject = final.callPackage ../../nix/lib/build-maven-project.nix {
        inherit (closure-lib) purifier;
      };
    };
}
