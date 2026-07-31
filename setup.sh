#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
agent_dir="${PI_AGENT_DIR:-${HOME}/.pi/agent}"
dry_run=false
install_packages=true

usage() {
  cat <<'EOF'
Usage: ./setup.sh [--dry-run] [--skip-install]

  --dry-run       Print intended changes without writing anything.
  --skip-install  Do not run npm install after copying package metadata.
EOF
}

while (($#)); do
  case "$1" in
    --dry-run) dry_run=true ;;
    --skip-install) install_packages=false ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

managed_files=(
  AGENTS.md
  REALTIME-SYSTEM-PROMPT.md
  settings.json
  mcp.json
  pi-auto-trees.json
  pi-codex-conversion.json
  pi-explore-subagents.json
  pi-smart-btw.json
  prewalk.json
  package.json
  package-lock.json
  extensions/herdr-agent-state.ts
  extensions/pretty-footer.ts
  disabled-extensions/clear-status.ts
)

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
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

for relative in "${managed_files[@]}"; do
  source_path="${repo_dir}/${relative}"
  target_path="${agent_dir}/${relative}"

  [[ -f "$source_path" ]] || { echo "Missing managed source: $relative" >&2; exit 1; }

  if [[ -f "$target_path" ]] && cmp -s "$source_path" "$target_path"; then
    echo "unchanged: $relative"
    continue
  fi

  if [[ -e "$target_path" || -L "$target_path" ]]; then
    run mkdir -p "${backup_dir}/$(dirname "$relative")"
    run cp -p "$target_path" "${backup_dir}/${relative}"
  fi

  run mkdir -p "$(dirname "$target_path")"
  run cp -p "$source_path" "$target_path"
done

prewalk_source="${repo_dir}/prewalk"
prewalk_link="${agent_dir}/packages/prewalk"
[[ -f "${prewalk_source}/package.json" ]] || {
  echo "Missing Prewalk submodule. Run: git submodule update --init" >&2
  exit 1
}

if [[ -L "$prewalk_link" ]] && [[ "$(readlink "$prewalk_link")" == "$prewalk_source" ]]; then
  echo "unchanged: packages/prewalk"
else
  if [[ -e "$prewalk_link" || -L "$prewalk_link" ]]; then
    run mkdir -p "${backup_dir}/packages"
    run mv "$prewalk_link" "${backup_dir}/packages/prewalk"
  fi
  run mkdir -p "${agent_dir}/packages"
  run ln -s "$prewalk_source" "$prewalk_link"
fi

if "$install_packages"; then
  if "$dry_run"; then
    echo "would run: npm install --prefix $(printf '%q' "$agent_dir")"
  else
    npm install --prefix "$agent_dir"
  fi
fi

echo "Pi setup complete: $agent_dir"
