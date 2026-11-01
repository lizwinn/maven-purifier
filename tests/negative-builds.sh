#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Builds copies of the multi fixture whose lock someone edited, and requires
# each build to fail with the message that says what went wrong. These
# mistakes only show when a derivation builds, so they cannot be flake
# checks, which only evaluate a failing derivation. Run it from the
# repository root; CI runs it.
set -euo pipefail
root=$(pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
jq() { nix shell 'nixpkgs#jq' -c jq "$@"; }

# Builds the `core` package of the build at $1 and requires the build to
# fail with output that contains $2.
expect_failure() {
  local src=$1 expected=$2 log=$work/log
  if nix build --no-link --impure --expr "
      let
        flake = builtins.getFlake \"path:$root\";
        pkgs = import flake.inputs.nixpkgs {
          system = builtins.currentSystem;
          overlays = [ flake.overlays.default ];
        };
      in
      (pkgs.buildMavenProject { src = $src; }).packages.core" >"$log" 2>&1; then
    echo "FAIL: the build of $src succeeded" >&2
    exit 1
  fi
  if ! grep -qF -- "$expected" "$log"; then
    echo "FAIL: the build of $src failed without '$expected':" >&2
    tail -30 "$log" >&2
    exit 1
  fi
  echo "ok: $(basename "$src") fails with '$expected'"
}

# A hash someone changed: the fetch of that file fails with Nix's hash
# mismatch.
cp -r tests/fixtures/multi "$work/tampered"
jq '(.artifacts[] | select(.path | endswith("commons-lang3-3.17.0.jar")) | .hash) = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="' \
  tests/fixtures/multi/maven-purifier.lock.json >"$work/tampered/maven-purifier.lock.json"
expect_failure "$work/tampered" "hash mismatch"

# An entry someone removed: Maven fails offline, and the build says what to
# run.
cp -r tests/fixtures/multi "$work/missing"
jq 'del(.artifacts[] | select(.path | endswith("commons-lang3-3.17.0.jar")))' \
  tests/fixtures/multi/maven-purifier.lock.json >"$work/missing/maven-purifier.lock.json"
# shellcheck disable=SC2016 # the backticks are part of the message
expect_failure "$work/missing" 'run `maven-purifier lock --force`'
