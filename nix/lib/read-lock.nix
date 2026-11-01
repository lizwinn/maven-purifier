# SPDX-License-Identifier: MIT
#
# Reads a purifier lockfile.
#
# A purifier lockfile is JSON whose top-level `artifacts` list holds one
# entry per downloaded file. A file entry is fetched:
#
#   { "path": "<relative path in the output tree>",
#     "url":  "<where the file was downloaded from>",
#     "hash": "sha256-<base64>" }
#
# An inline entry holds the text of a file whose URL serves changing
# contents, such as a Maven metadata file:
#
#   { "path": "<relative path in the output tree>",
#     "contents": "<the file's text>" }
#
# This library treats `path` as opaque and only places each file at its
# path. The purifier decides which path a downloaded file gets: here, the
# file's path in a Maven local repository. The lockfile also holds
# `version`, the version of the purifier's lock format, and whatever else
# the purifier needs beside `artifacts`.
#
# The files read-lock.nix, fetch.nix, tree.nix and realize.nix have the
# shape the shared nix-purifiers/purifier library is expected to take, and
# stay local here until that library is published.
#
# Needs no nixpkgs: the interactive mode evaluates this with nothing but the
# Nix installation it runs.
{
  # The lockfile.
  lockFile,
  # The name of the purifier, for error messages.
  purifier,
  # The lock format version the purifier reads.
  formatVersion,
}:
let
  lock = builtins.fromJSON (builtins.readFile lockFile);

  # A store path name from a file name. Store path names allow
  # [A-Za-z0-9+._?=-], must not start with a dot, and are at most 211
  # characters; every other character becomes "_". The interactive mode
  # and the sandboxed build both name their fetches with this function,
  # so they share store paths.
  storeName =
    fileName:
    let
      # builtins.split alternates the text between matches with a list per
      # match.
      replaced = builtins.concatStringsSep "" (
        map (part: if builtins.isList part then "_" else part) (
          builtins.split "[^A-Za-z0-9+._?=-]" fileName
        )
      );
      undotted = builtins.head (builtins.match "\\.*(.*)" replaced);
      nonEmpty = if undotted == "" then "file" else undotted;
    in
    builtins.substring 0 200 nonEmpty;
in
assert
  (lock.version or null) == formatVersion
  || throw "${purifier}: ${toString lockFile} has lock format version ${
    toString (lock.version or "none")
  }; this library reads version ${toString formatVersion}. Lock the build again with the ${purifier} version that matches this library.";
lock
// {
  inherit purifier storeName;

  # The fetch name of an artifact: the file name, made a valid store name.
  artifactName = artifact: storeName (builtins.baseNameOf artifact.path);
}
