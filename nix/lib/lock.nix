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
#   settings             the settings the lock run used, without servers and
#                        proxies, as XML text; null when it used none
#   definitionHash       a hash of the build definition (every pom.xml and
#                        .mvn/) and the goals; see definition-hash.nix
#   projects             one entry per module the build installs: groupId,
#                        artifactId, version, and its artifacts, each with
#                        `key` (<artifactId>[-<classifier>].<extension>),
#                        classifier, extension and its local repository path
#
# The reader checks the shape of the lock, so that a lock someone edited by
# hand fails with the field at fault rather than deep inside a build.
#
# Needs no nixpkgs, like read-lock.nix.
{ lockFile }:
let
  lock = import ./read-lock.nix {
    inherit lockFile;
    purifier = "maven-purifier";
    formatVersion = import ./lock-version.nix;
  };

  invalid =
    problem:
    throw "maven-purifier: ${toString lockFile} is not a lock that maven-purifier wrote: ${problem}. Run `maven-purifier lock --force` to write it again.";

  isString = builtins.isString;
  checkArtifact =
    i: a:
    if !(builtins.isAttrs a) then
      invalid "artifacts[${toString i}] is not an object"
    else if !(isString (a.path or null)) then
      invalid "artifacts[${toString i}] has no `path`"
    else if a ? contents then
      isString a.contents || invalid "the `contents` of ${a.path} is not a string"
    else
      (isString (a.url or null) || invalid "${a.path} has neither `url` nor `contents`")
      && (isString (a.hash or null) || invalid "${a.path} has no `hash`")
      && (builtins.isList (a.mirrors or null) || invalid "${a.path} has no `mirrors` list");

  checkProject =
    p:
    (builtins.isAttrs p && isString (p.artifactId or null) || invalid "a project has no `artifactId`")
    && (isString (p.groupId or null) || invalid "project ${p.artifactId} has no `groupId`")
    && (isString (p.version or null) || invalid "project ${p.artifactId} has no `version`")
    && (
      builtins.isList (p.artifacts or null)
      && builtins.all (a: isString (a.key or null) && isString (a.path or null)) p.artifacts
      || invalid "project ${p.artifactId} has an artifact without `key` or `path`"
    );

  valid =
    (builtins.isList (lock.artifacts or null) || invalid "it has no `artifacts` list")
    && (builtins.isList (lock.projects or null) || invalid "it has no `projects` list")
    && (builtins.isList (lock.goals or null) || invalid "it has no `goals` list")
    && (isString (lock.javaVersion or null) || invalid "it has no `javaVersion`")
    && (
      isString (lock.maven.version or null) && isString (lock.maven.distribution or null)
      || invalid "it has no `maven.version` and `maven.distribution`"
    )
    && builtins.all (x: x) (
      builtins.genList (i: checkArtifact i (builtins.elemAt lock.artifacts i)) (
        builtins.length lock.artifacts
      )
    )
    && builtins.all checkProject lock.projects
    && (
      builtins.any (a: a.path == lock.maven.distribution) lock.artifacts
      || invalid "`artifacts` has no entry for the Maven distribution ${lock.maven.distribution}"
    );
in
assert valid;
lock
// {
  projectsByArtifactId = builtins.listToAttrs (
    map (p: {
      name = p.artifactId;
      value = p;
    }) lock.projects
  );
}
