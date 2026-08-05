#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
agent_dir="${PI_AGENT_DIR:-${HOME}/.pi/agent}"
tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/my-pi-drift.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT
PI_AGENT_DIR="$tmp_dir/agent" "$repo_dir/setup.sh" >/dev/null
found=false
for relative in settings.json AGENTS.md REALTIME-SYSTEM-PROMPT.md mcp.json pi-auto-trees.json pi-codex-conversion.json pi-smart-btw.json prewalk.json fzf.json package.json package-lock.json disabled-extensions/clear-status.ts; do
  expected="$tmp_dir/agent/$relative"
  actual="$agent_dir/$relative"
  if [[ ! -e "$actual" && ! -L "$actual" ]]; then
    echo "missing: $relative"; found=true
  elif [[ -L "$actual" ]]; then
    echo "different: $relative is an unexpected link -> $(readlink "$actual")"; found=true
  elif [[ "$relative" == *.json ]] && node "$repo_dir/scripts/json-equal.mjs" "$actual" "$expected"; then
    continue
  elif ! cmp -s "$expected" "$actual"; then
    echo "different: $relative"; diff -u "$actual" "$expected" || true; found=true
  fi
done

link_relatives=(
  "packages/prewalk"
  "extensions/herdr-agent-state.ts"
  "extensions/pretty-footer.ts"
  "extensions/session-spend-dashboard"
  "skills/webflow-designer-agent-browser"
)
link_sources=(
  "$repo_dir/prewalk"
  "$repo_dir/extensions/herdr-agent-state.ts"
  "$repo_dir/extensions/pretty-footer.ts"
  "$repo_dir/extensions/session-spend-dashboard"
  "$repo_dir/skills/webflow-designer-agent-browser"
)
for index in "${!link_relatives[@]}"; do
  relative="${link_relatives[$index]}"
  source="${link_sources[$index]}"
  target="$agent_dir/$relative"
  if [[ ! -L "$target" ]]; then
    echo "different: $relative (expected repository link)"; found=true
  elif [[ "$(readlink "$target")" != "$source" ]]; then
    echo "different: $relative -> $(readlink "$target")"; found=true
  fi
done
[[ "$found" == false ]] && echo "No managed file drift detected."
