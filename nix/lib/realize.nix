# SPDX-License-Identifier: MIT
#
# What the interactive mode builds, without nixpkgs.
#
# `fetches` is every locked artifact; `nix-build -A fetches` downloads them
# in parallel. `manifest` is then a store file that maps the path of each
# artifact to its store path. The file refers to every artifact, so one GC
# root on it keeps them all alive, and the interactive mode builds its
# writable tree from it.
#
# A file made with builtins.toFile may refer to store paths but not to
# derivation outputs, so the manifest names each artifact through
# builtins.fetchurl: with the same name and hash, it is the same
# fixed-output store path a fetch derivation produces, and it is already
# valid once `fetches` is built, so nothing downloads twice.
{
  # A lock read by read-lock.nix.
  lock,
}:
let
  fetch = import ./fetch.nix { inherit lock; };
  byPath =
    f:
    builtins.listToAttrs (
      map (artifact: {
        name = artifact.path;
        value = f artifact;
      }) lock.artifacts
    );
in
{
  fetches = byPath fetch;
  manifest = builtins.toFile "${lock.purifier}-manifest.json" (
    builtins.toJSON (
      byPath (
        artifact:
        builtins.fetchurl {
          inherit (artifact) url;
          name = lock.artifactName artifact;
          sha256 = artifact.hash;
        }
      )
    )
  );
}
