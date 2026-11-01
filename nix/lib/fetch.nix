# SPDX-License-Identifier: MIT
#
# The store path of a locked artifact.
#
# A file entry ({ path, url, hash }) is fetched. By default the fetch is a
# fixed-output derivation on Nix's built-in fetcher (the same derivation
# <nix/fetchurl.nix> makes), so neither the interactive mode nor a
# sandboxed build needs nixpkgs to download. A fixed-output store path
# depends only on its name and hash, so the default fetcher and nixpkgs'
# fetchurl produce the same paths.
#
# An inline entry ({ path, contents }) holds the text of a file whose URL
# serves changing contents, and becomes a store file of that text.
#
# `fetchurl`, when given, replaces the built-in fetcher. It is called with
# { name, url, hash } and is the place for credentials (nixpkgs' fetchurl
# takes `netrcPhase`) or mirrors.
{
  # A lock read by read-lock.nix.
  lock,
  fetchurl ? null,
}:
artifact:
let
  name = lock.artifactName artifact;
in
if artifact ? contents then
  builtins.toFile name artifact.contents
else if fetchurl != null then
  fetchurl {
    inherit name;
    inherit (artifact) url hash;
  }
else
  derivation {
    inherit name;
    builder = "builtin:fetchurl";
    system = "builtin";
    inherit (artifact) url;
    urls = [ artifact.url ];
    outputHash = artifact.hash;
    outputHashAlgo = "sha256";
    outputHashMode = "flat";
    unpack = false;
    executable = false;
    preferLocalBuild = true;
    impureEnvVars = [
      "http_proxy"
      "https_proxy"
      "ftp_proxy"
      "all_proxy"
      "no_proxy"
    ];
  }
