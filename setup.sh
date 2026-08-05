#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
agent_dir="${PI_AGENT_DIR:-${HOME}/.pi/agent}"
shared_skills_dir="${AGENTS_SKILLS_DIR:-${HOME}/.agents/skills}"
dry_run=false

usage() {
  cat <<'EOF'
Usage: ./setup.sh [--dry-run]

  --dry-run  Print intended changes without writing anything.

Environment:
  PI_AGENT_DIR       Pi configuration target (default: ~/.pi/agent)
  AGENTS_SKILLS_DIR  Cross-harness skill target (default: ~/.agents/skills)
EOF
}

while (($#)); do
  case "$1" in
    --dry-run) dry_run=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

managed_files=(
  AGENTS.md
  REALTIME-SYSTEM-PROMPT.md
  mcp.json
  pi-auto-trees.json
  pi-codex-conversion.json
  pi-smart-btw.json
  prewalk.json
  package.json
  package-lock.json
  fzf.json
  disabled-extensions/clear-status.ts
)

prewalk_source="${repo_dir}/prewalk"
owned_link_sources=(
  "$prewalk_source"
  "${repo_dir}/extensions/herdr-agent-state.ts"
  "${repo_dir}/extensions/pretty-footer.ts"
  "${repo_dir}/extensions/session-spend-dashboard"
  "${repo_dir}/skills/webflow-designer-agent-browser"
)

for relative in "${managed_files[@]}"; do
  [[ -f "${repo_dir}/${relative}" ]] || { echo "Missing managed source: $relative" >&2; exit 1; }
done
[[ -f "${prewalk_source}/package.json" ]] || {
  echo "Missing Prewalk submodule. Run: git submodule update --init" >&2
  exit 1
}
for source_path in "${owned_link_sources[@]}"; do
  [[ -e "$source_path" ]] || { echo "Missing linked source: $source_path" >&2; exit 1; }
done

settings_override=()
if [[ -f "${repo_dir}/settings.local.json" ]]; then
  settings_override+=("${repo_dir}/settings.local.json")
fi
if ((${#settings_override[@]})); then
  rendered_settings="$(node "${repo_dir}/scripts/render-settings.mjs" "${repo_dir}/settings.json" "${settings_override[0]}")"
else
  rendered_settings="$(node "${repo_dir}/scripts/render-settings.mjs" "${repo_dir}/settings.json")"
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
backup_dir="${agent_dir}/backups/${timestamp}"

run() {
  if "$dry_run"; then
    printf 'would run:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

run mkdir -p "$agent_dir"

retired_files=(
  pi-explore-subagents.json
  skills/webflow-designer-agent-browser
)

for relative in "${retired_files[@]}"; do
  target_path="${agent_dir}/${relative}"
  if [[ -e "$target_path" || -L "$target_path" ]]; then
    run mkdir -p "${backup_dir}/$(dirname "$relative")"
    run mv "$target_path" "${backup_dir}/${relative}"
  fi
done

settings_target="${agent_dir}/settings.json"

if [[ -f "$settings_target" && ! -L "$settings_target" ]] && cmp -s <(printf '%s\n' "$rendered_settings") "$settings_target"; then
  echo "unchanged: settings.json (tracked defaults + local overrides)"
else
  if [[ -e "$settings_target" || -L "$settings_target" ]]; then
    run mkdir -p "$backup_dir"
    run mv "$settings_target" "${backup_dir}/settings.json"
  fi
  if "$dry_run"; then
    echo "would render: settings.json (tracked defaults + local overrides)"
  else
    settings_tmp="${settings_target}.tmp.$$"
    printf '%s\n' "$rendered_settings" > "$settings_tmp"
    mv "$settings_tmp" "$settings_target"
  fi
fi

for relative in "${managed_files[@]}"; do
  source_path="${repo_dir}/${relative}"
  target_path="${agent_dir}/${relative}"

  if [[ -f "$target_path" && ! -L "$target_path" ]] && cmp -s "$source_path" "$target_path"; then
    echo "unchanged: $relative"
    continue
  fi

  if [[ -e "$target_path" || -L "$target_path" ]]; then
    run mkdir -p "${backup_dir}/$(dirname "$relative")"
    run mv "$target_path" "${backup_dir}/${relative}"
  fi

  run mkdir -p "$(dirname "$target_path")"
  run cp -p "$source_path" "$target_path"
done

link_owned() {
  local source_path="$1"
  local target_path="$2"
  local relative="$3"

  if [[ -L "$target_path" ]] && [[ "$(readlink "$target_path")" == "$source_path" ]]; then
    echo "unchanged: ${relative} -> ${source_path}"
    return
  fi

  if [[ -e "$target_path" || -L "$target_path" ]]; then
    run mkdir -p "${backup_dir}/$(dirname "$relative")"
    run mv "$target_path" "${backup_dir}/${relative}"
  fi
  run mkdir -p "$(dirname "$target_path")"
  run ln -s "$source_path" "$target_path"
}

link_owned "$prewalk_source" "${agent_dir}/packages/prewalk" "packages/prewalk"
link_owned "${repo_dir}/extensions/herdr-agent-state.ts" "${agent_dir}/extensions/herdr-agent-state.ts" "extensions/herdr-agent-state.ts"
link_owned "${repo_dir}/extensions/pretty-footer.ts" "${agent_dir}/extensions/pretty-footer.ts" "extensions/pretty-footer.ts"
link_owned "${repo_dir}/extensions/session-spend-dashboard" "${agent_dir}/extensions/session-spend-dashboard" "extensions/session-spend-dashboard"
link_owned "${repo_dir}/skills/webflow-designer-agent-browser" "${shared_skills_dir}/webflow-designer-agent-browser" "external-agents-skills-webflow-designer-agent-browser"

echo "Setup complete: Pi at $agent_dir; shared skills at $shared_skills_dir"
