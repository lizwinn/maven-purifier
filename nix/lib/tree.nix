# SPDX-License-Identifier: MIT
#
# The tree of a lock: every locked file at its `path`, as a link into the
# store. A purifier's sandboxed build starts from this tree, usually by
# copying it into a writable directory of links (`cp -rs`), since build
# tools write lock and marker files next to what they read.
{
  # nixpkgs' runCommand.
  runCommand,
  # A lock read by read-lock.nix.
  lock,
  # The name of the tree's store path.
  name ? "${lock.purifier}-tree",
  # Replaces the built-in fetcher; see fetch.nix.
  fetchurl ? null,
}:
let
  fetch = import ./fetch.nix { inherit lock fetchurl; };
in
# The manifest goes to the builder as a file, since a large build locks
# thousands of artifacts and the list would not fit in an environment
# variable.
runCommand name
  {
    manifest = builtins.concatStringsSep "" (map (a: "${a.path}\t${fetch a}\n") lock.artifacts);
    passAsFile = [ "manifest" ];
    preferLocalBuild = true;
    allowSubstitutes = false;
    passthru = { inherit lock; };
  }
  ''
    mkdir -p $out
    while IFS=$'\t' read -r rel target; do
      mkdir -p "$out/$(dirname "$rel")"
      ln -s "$target" "$out/$rel"
    done < "$manifestPath"
  ''
