#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

bash -n sync setup.sh scripts/check.sh scripts/drift.sh scripts/restore.sh
node --check scripts/render-settings.mjs
node --check scripts/json-equal.mjs
node --check scripts/update-git-pins.mjs

json_files=(
  settings.json
  mcp.json
  pi-auto-trees.json
  pi-codex-conversion.json
  pi-smart-btw.json
  prewalk.json
  package.json
  package-lock.json
  settings.local.example.json
  fzf.json
)

node -e 'for (const file of process.argv.slice(1)) JSON.parse(require("fs").readFileSync(file, "utf8"))' "${json_files[@]}"
node scripts/render-settings.mjs settings.json settings.local.example.json >/dev/null

[[ -f prewalk/package.json ]] || {
  echo "Missing Prewalk submodule. Run: git submodule update --init" >&2
  exit 1
}

git submodule status -- prewalk >/dev/null

for forbidden in auth.json trust.json run-history.jsonl mcp-cache.json models-store.json cursor-sdk-model-list.json; do
  if git ls-files --error-unmatch "$forbidden" >/dev/null 2>&1; then
    echo "Forbidden runtime file is tracked: $forbidden" >&2
    exit 1
  fi
done

if git ls-files | grep -E '(^|/)(sessions|cache|generated|intercom|node_modules|\.pi-subagents)(/|$)|\.(db|sqlite|pem|key)$' >/dev/null; then
  echo "Tracked files include forbidden runtime or credential material" >&2
  exit 1
fi

if git grep -nEI "(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|authorization[[:space:]]*:[[:space:]]*bearer)" -- . ':!scripts/check.sh'; then
  echo "Potential secret found in tracked content" >&2
  exit 1
fi

git diff --check
echo "All checks passed."
