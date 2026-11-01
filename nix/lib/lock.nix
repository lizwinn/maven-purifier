# SPDX-License-Identifier: MIT
#
# Reads a maven-purifier lock file, written by `maven-purifier lock`.
#
# Beside `artifacts` (see read-lock.nix), where each `path` is the path of
# the file in a Maven local repository, the lock holds:
#
#   maven.version        the Maven version of the lock run
#   maven.distribution   the path of its distribution archive in `artifacts`
#   javaVersion          the version of the JDK that ran the lock run
#   goals                the goals the lock run ran
#   definitionHash       a hash of the build definition (every pom.xml and
#                        .mvn/), which tells the tool when to lock again
#   projects             one entry per module the build installs: groupId,
#                        artifactId, version, and its artifacts, each with
#                        `key` (<artifactId>[-<classifier>].<extension>),
#                        classifier, extension and its local repository path
#
# Needs no nixpkgs, like read-lock.nix.
{ lockFile }:
let
  lock = import ./read-lock.nix {
    inherit lockFile;
    purifier = "maven-purifier";
    formatVersion = import ./lock-version.nix;
  };
in
lock
// {
  projectsByArtifactId = builtins.listToAttrs (
    map (p: {
      name = p.artifactId;
      value = p;
    }) lock.projects
  );
}
