# SPDX-License-Identifier: MIT
#
# The `maven-purifier` library namespace:
#
#   readLock           the lock in memory of the purifier contract, from a
#                      maven-purifier lockfile (nix/lib/lock.nix)
#   buildMavenProject  the builder (nix/lib/build-maven-project.nix), which
#                      takes the package set it builds with as `pkgs`
{ closure-lib, ... }:
{

  overlay = final: prev: {
    maven-purifier = (prev.maven-purifier or { }) // {
      readLock = import ../../nix/lib/lock.nix;
      buildMavenProject = import ../../nix/lib/build-maven-project.nix {
        inherit (closure-lib) purifier;
      };
    };
  };

}
