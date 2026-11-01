# SPDX-License-Identifier: MIT
#
# The entry point of `maven-purifier deploy`, which evaluates it with
# nix-build: `src` is the build root as a string, and `nixpkgs` is the
# nixpkgs source the command was built with.
{ src, nixpkgs }:
let
  pkgs = import nixpkgs { };
in
(pkgs.callPackage ./build-maven-project.nix { } { src = /. + src; }).deploy
