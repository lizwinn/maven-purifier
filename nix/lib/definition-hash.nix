# SPDX-License-Identifier: MIT
#
# The definition hash of a Maven build, as `maven-purifier lock` computes it
# (definition_hash in cli/maven_purifier.py): the SHA-256 of a text that
# names the lock goals and each definition file with the SHA-256 of its
# contents. The definition files are every regular file named pom.xml, and
# every regular file under .mvn/ at the build root; the walk skips the
# directories that never belong to a build definition and symbolic links.
#
# `src` must be a path, since the walk reads the directory at evaluation
# time.
{ src, goals }:
let
  skipped = [
    "target"
    ".git"
    ".maven-purifier"
    ".idea"
    "node_modules"
  ];
  skippedDir = name: builtins.elem name skipped || builtins.substring 0 6 name == "result";

  # The definition files under `dir`, as paths relative to the build root.
  # `rel` is the relative path of `dir`, "" at the root; `inMvn` says whether
  # `dir` is .mvn/ at the build root or below it.
  walk =
    dir: rel: inMvn:
    let
      entries = builtins.readDir dir;
      relOf = name: if rel == "" then name else "${rel}/${name}";
    in
    builtins.concatLists (
      map (
        name:
        let
          type = entries.${name};
        in
        if type == "directory" then
          if skippedDir name then
            [ ]
          else
            walk (dir + "/${name}") (relOf name) (inMvn || (rel == "" && name == ".mvn"))
        else if type == "regular" && (name == "pom.xml" || inMvn) then
          [ (relOf name) ]
        else
          [ ]
      ) (builtins.attrNames entries)
    );

  files = builtins.sort builtins.lessThan (walk src "" false);
  lines = [
    "goals ${builtins.concatStringsSep " " goals}"
  ]
  ++ map (rel: "${rel} ${builtins.hashFile "sha256" (src + "/${rel}")}") files;
in
"sha256:${builtins.hashString "sha256" (builtins.concatStringsSep "\n" lines + "\n")}"
