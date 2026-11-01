#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Locks every fixture again with the maven-purifier of this checkout. Run it
# from the repository root; it needs the network. The `sources` fixture
# takes a SNAPSHOT from tests/snapshot-repository, which this script serves
# on localhost:18080 while it locks.
set -euo pipefail
root=$(pwd)
cli=$(nix build --no-link --print-out-paths "$root#cli")
python=$(nix build --no-link --print-out-paths 'nixpkgs#python3')

"$python/bin/python3" -m http.server 18080 --bind 127.0.0.1 \
  --directory "$root/tests/snapshot-repository" >/dev/null 2>&1 &
server=$!
trap 'kill $server' EXIT

lock() {
  local fixture=$1
  shift
  echo "locking $fixture" >&2
  (cd "$root/tests/fixtures/$fixture" && "$cli/bin/maven-purifier" lock --force "$@")
}

lock multi clean deploy
lock wrapper
lock sources --settings settings.xml clean install -Pextra
