# SPDX-License-Identifier: MIT
#
# The entry point of `maven-purifier mvn`, which evaluates it with plain
# nix-build and the build's lockfile as `lockFile`.
{ lockFile }:
import ./realize.nix { lock = import ./lock.nix { inherit lockFile; }; }
