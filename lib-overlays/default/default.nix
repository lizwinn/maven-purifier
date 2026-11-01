# SPDX-License-Identifier: MIT
#
# The `maven-purifier` library namespace. `readLock` reads a maven-purifier
# lockfile into the lock in memory of the purifier contract
# (nix/lib/lock.nix).
{ ... }:
{

  overlay = final: prev: {
    maven-purifier = (prev.maven-purifier or { }) // {
      readLock = import ../../nix/lib/lock.nix;
    };
  };

}
