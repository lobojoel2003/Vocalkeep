#!/usr/bin/env bash
# Set a new version everywhere: ./scripts/bump-version.sh 1.2.3
# Then add a "## [1.2.3]" section to CHANGELOG.md, commit, and tag v1.2.3 (see docs/releasing.md).
set -euo pipefail
cd "$(dirname "$0")/.."

new="${1:-}"
if ! [[ "$new" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
  echo "usage: $0 MAJOR.MINOR.PATCH[-pre]" >&2
  exit 1
fi
old="$(tr -d '[:space:]' < VERSION)"

echo "$new" > VERSION
sed -i.bak -E "/^\[workspace.package\]/,/^\[/ s/^version = \"[^\"]+\"/version = \"$new\"/" Cargo.toml
sed -i.bak -E "s/^(vocalkeep-core = \{ path = \"[^\"]+\", version = )\"[^\"]+\"/\1\"$new\"/" Cargo.toml
sed -i.bak -E "s/^version = \"[^\"]+\"/version = \"$new\"/" pipeline/pyproject.toml
sed -i.bak -E "s/^__version__ = \"[^\"]+\"/__version__ = \"$new\"/" pipeline/src/vocalkeep/__init__.py
rm -f Cargo.toml.bak pipeline/pyproject.toml.bak pipeline/src/vocalkeep/__init__.py.bak

(cd desktop && npm version "$new" --no-git-tag-version --allow-same-version >/dev/null)
python3 - "$new" <<'PY'
import json, sys
path = "desktop/src-tauri/tauri.conf.json"
conf = json.load(open(path))
conf["version"] = sys.argv[1]
open(path, "w").write(json.dumps(conf, indent=2, ensure_ascii=False) + "\n")
PY
# Refresh Cargo.lock entries for the workspace crates.
cargo update --workspace --offline >/dev/null 2>&1 || cargo update --workspace >/dev/null

echo "Version bumped: $old -> $new"
./scripts/check-version.sh
