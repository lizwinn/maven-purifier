# SPDX-License-Identifier: MIT
#
# What the interactive mode builds, without nixpkgs.
#
# `fetches` is every locked file entry; `nix-build -A fetches` downloads
# them in parallel. `manifest` is then a store file that maps the path of
# each artifact to its store path. The file refers to every artifact, so
# one GC root on it keeps them all alive, and the interactive mode builds
# its writable tree from it.
#
# A file made with builtins.toFile may refer to store paths but not to
# derivation outputs, so the manifest names each file entry through
# builtins.fetchurl: with the same name and hash, it is the same
# fixed-output store path a fetch derivation produces, and it is already
# valid once `fetches` is built, so nothing downloads twice. An inline
# entry is a store file made with builtins.toFile, which the manifest may
# name directly.
{
  # A lock read by read-lock.nix.
  lock,
}:
let
  fetch = import ./fetch.nix { inherit lock; };
  byPath =
    artifacts: f:
    builtins.listToAttrs (
      map (artifact: {
        name = artifact.path;
        value = f artifact;
      }) artifacts
    );
in
{
  fetches = byPath (builtins.filter (a: !(a ? contents)) lock.artifacts) fetch;
  manifest = builtins.toFile "${lock.purifier}-manifest.json" (
    builtins.toJSON (
      byPath lock.artifacts (
        artifact:
        if artifact ? contents then
          fetch artifact
        else
          builtins.fetchurl {
            inherit (artifact) url;
            name = lock.artifactName artifact;
            sha256 = artifact.hash;
          }
      )
    )
  );
}
