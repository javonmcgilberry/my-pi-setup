#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
agent_dir="${PI_AGENT_DIR:-${HOME}/.pi/agent}"
tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/my-pi-drift.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT
PI_AGENT_DIR="$tmp_dir/agent" "$repo_dir/setup.sh" --skip-install >/dev/null
found=false
for relative in settings.json AGENTS.md REALTIME-SYSTEM-PROMPT.md mcp.json pi-auto-trees.json pi-codex-conversion.json pi-explore-subagents.json pi-smart-btw.json prewalk.json fzf.json package.json package-lock.json; do
  expected="$tmp_dir/agent/$relative"
  actual="$agent_dir/$relative"
  if [[ ! -e "$actual" && ! -L "$actual" ]]; then
    echo "missing: $relative"; found=true
  elif [[ -L "$actual" ]]; then
    echo "link: $relative -> $(readlink "$actual")"
  elif [[ "$relative" == *.json ]] && node "$repo_dir/scripts/json-equal.mjs" "$actual" "$expected"; then
    continue
  elif ! cmp -s "$expected" "$actual"; then
    echo "different: $relative"; diff -u "$actual" "$expected" || true; found=true
  fi
done
[[ "$found" == false ]] && echo "No managed file drift detected."
