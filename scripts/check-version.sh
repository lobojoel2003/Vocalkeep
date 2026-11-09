#!/usr/bin/env bash
# Verify that every manifest carries the version in ./VERSION.
#
#   ./scripts/check-version.sh            # all manifests agree
#   ./scripts/check-version.sh v1.2.3     # ...and the tag matches, and CHANGELOG.md has a section
set -euo pipefail
cd "$(dirname "$0")/.."

version="$(tr -d '[:space:]' < VERSION)"
if ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
  echo "VERSION '$version' is not semantic (MAJOR.MINOR.PATCH[-pre])" >&2
  exit 1
fi

fail=0
check() {
  local file="$1" found="$2"
  if [[ "$found" != "$version" ]]; then
    echo "✗ $file has version '$found', expected '$version'" >&2
    fail=1
  else
    echo "✓ $file: $found"
  fi
}

json_version() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$1"
}

check Cargo.toml "$(sed -n '/^\[workspace.package\]/,/^\[/{s/^version *= *"\(.*\)"/\1/p}' Cargo.toml | head -1)"
check "Cargo.toml (vocalkeep-core dependency)" \
  "$(grep -E '^vocalkeep-core = ' Cargo.toml | sed -E 's/.*version = "([^"]+)".*/\1/')"
check Cargo.lock "$(awk '/^name = "vocalkeep-core"$/{getline; gsub(/version = |"/, ""); print; exit}' Cargo.lock)"
check desktop/package.json "$(json_version desktop/package.json)"
check desktop/package-lock.json "$(json_version desktop/package-lock.json)"
check desktop/src-tauri/tauri.conf.json "$(json_version desktop/src-tauri/tauri.conf.json)"
check pipeline/pyproject.toml "$(sed -n 's/^version *= *"\(.*\)"/\1/p' pipeline/pyproject.toml | head -1)"
check pipeline/src/vocalkeep/__init__.py \
  "$(sed -n 's/^__version__ *= *"\(.*\)"/\1/p' pipeline/src/vocalkeep/__init__.py | head -1)"

if [[ $# -ge 1 && -n "$1" ]]; then
  tag="${1#refs/tags/}"
  if [[ "$tag" != "v$version" ]]; then
    echo "✗ tag '$tag' does not match VERSION 'v$version'" >&2
    fail=1
  else
    echo "✓ tag $tag"
  fi
  if ! grep -qE "^## \[$version\]" CHANGELOG.md; then
    echo "✗ CHANGELOG.md has no '## [$version]' section" >&2
    fail=1
  else
    echo "✓ CHANGELOG.md has a $version section"
  fi
fi

exit $fail
