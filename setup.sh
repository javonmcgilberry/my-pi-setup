#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
agent_dir="${PI_AGENT_DIR:-${HOME}/.pi/agent}"
default_agent_dir="${HOME}/.pi/agent"
shared_skills_dir="${AGENTS_SKILLS_DIR:-${HOME}/.agents/skills}"
default_shared_skills_dir="${HOME}/.agents/skills"
macos_launch_agents_dir="${HOME}/Library/LaunchAgents"
default_commands_dir="${HOME}/.local/bin"
if [[ -n "${PI_COMMANDS_DIR:-}" ]]; then
  commands_dir="$PI_COMMANDS_DIR"
elif [[ "$agent_dir" != "$default_agent_dir" ]]; then
  commands_dir="$(dirname "$agent_dir")/bin"
else
  commands_dir="$default_commands_dir"
fi
manifest_script="${repo_dir}/scripts/manifest.mjs"
repo_real_dir="$(cd -P "$repo_dir" && pwd)"
dry_run=false

usage() {
  cat <<'EOF'
Usage: ./setup.sh [--dry-run]

  --dry-run  Print intended changes without writing anything.

Environment:
  PI_AGENT_DIR       Pi configuration target (default: ~/.pi/agent)
  AGENTS_SKILLS_DIR  Cross-harness skill target (default: ~/.agents/skills)
  PI_COMMANDS_DIR    Command target (default: ~/.local/bin for a live install)

On macOS, a live default install also manages the LaunchAgent that starts the
default tmux server in the GUI login session. Temporary Pi installs do not touch
~/Library/LaunchAgents.
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

if ! "$dry_run" && { [[ "$agent_dir" == "$default_agent_dir" ]] || [[ "$shared_skills_dir" == "$default_shared_skills_dir" ]] || [[ "$commands_dir" == "$default_commands_dir" ]]; } && pgrep -x pi >/dev/null 2>&1; then
  echo "Pi is running. Close active Pi sessions before applying the live setup." >&2
  exit 1
fi

manifest() {
  node "$manifest_script" "$@"
}

manifest validate >/dev/null

manage_macos_launch_agents=false
if [[ "$(uname -s)" == "Darwin" && "$agent_dir" == "$default_agent_dir" && "$shared_skills_dir" == "$default_shared_skills_dir" ]]; then
  manage_macos_launch_agents=true
fi

assert_safe_target_parent() {
  local root="$1"
  local relative="$2"
  is_allowed_system_symlink() { [[ "$1" == "/tmp" || "$1" == "/var" ]]; }
  if [[ -L "$root" ]] && ! is_allowed_system_symlink "$root"; then
    echo "Refusing symlinked target root: $root" >&2
    exit 1
  fi
  local root_probe="${root%/}"
  [[ -z "$root_probe" ]] && root_probe="/"
  while [[ "$root_probe" != "/" ]]; do
    if [[ -L "$root_probe" ]] && ! is_allowed_system_symlink "$root_probe"; then
      echo "Refusing symlinked target ancestor: $root_probe" >&2
      exit 1
    fi
    root_probe="$(dirname "$root_probe")"
  done
  local parent_relative="${relative%/*}"
  [[ "$parent_relative" == "$relative" ]] && parent_relative="."
  local current="$root"
  local parts=()
  IFS='/' read -r -a parts <<< "$relative"
  local last_index=$((${#parts[@]} - 1))
  for ((index = 0; index < last_index; index += 1)); do
    current="${current}/${parts[index]}"
    if [[ -L "$current" ]] && ! is_allowed_system_symlink "$current"; then
      echo "Refusing symlinked target parent: $current" >&2
      exit 1
    fi
  done
  if ! python3 - "$root" "$parent_relative" <<'PY'
import os
import sys

root = os.path.realpath(sys.argv[1])
parent = os.path.realpath(os.path.join(sys.argv[1], sys.argv[2]))
try:
    inside = os.path.commonpath((root, parent)) == root
except ValueError:
    inside = False
sys.exit(0 if inside else 1)
PY
  then
    echo "Refusing target parent outside configured root: ${root}/${parent_relative}" >&2
    exit 1
  fi
}

assert_safe_target_parent "$agent_dir" ""
assert_safe_target_parent "$shared_skills_dir" ""
assert_safe_target_parent "$commands_dir" ""

rendered_entries=()
while IFS=$'\t' read -r source target _backup; do
  rendered_entries+=("${source}"$'\t'"${target}")
done < <(manifest list rendered)
if ((${#rendered_entries[@]} != 1)); then
  echo "Manifest must declare exactly one rendered settings entry" >&2
  exit 1
fi
IFS=$'\t' read -r rendered_source rendered_target <<< "${rendered_entries[0]}"
settings_target="${agent_dir}/${rendered_target}"

while IFS=$'\t' read -r source _target _backup; do
  [[ -f "${repo_dir}/${source}" ]] || {
    echo "Missing copied source: $source" >&2
    exit 1
  }
done < <(manifest list copied)
while IFS=$'\t' read -r source _target _backup; do
  [[ -f "${repo_dir}/${source}" ]] || {
    echo "Missing command source: $source" >&2
    exit 1
  }
done < <(manifest list commands)
while IFS=$'\t' read -r source _target _backup; do
  [[ -f "${repo_dir}/${source}" ]] || {
    echo "Missing macOS LaunchAgent source: $source" >&2
    exit 1
  }
done < <(manifest list macosLaunchAgents)

link_resolves_into_repo() {
  local target="$1"
  local resolved
  resolved="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$target")"
  [[ "$resolved" == "$repo_real_dir" || "$resolved" == "$repo_real_dir/"* ]]
}

while IFS=$'\t' read -r relative; do
  target_path="${agent_dir}/${relative}"
  if [[ -L "$target_path" ]] && link_resolves_into_repo "$target_path"; then
    echo "External target unexpectedly points into this repository: $relative" >&2
    exit 1
  fi
done < <(manifest list externalLinks)
while IFS=$'\t' read -r target; do
  assert_safe_target_parent "$agent_dir" "$target"
done < <(manifest list externalLinks)

while IFS=$'\t' read -r _source target _backup; do
  assert_safe_target_parent "$agent_dir" "$target"
done < <(manifest list rendered)
while IFS=$'\t' read -r _source target _backup; do
  assert_safe_target_parent "$agent_dir" "$target"
done < <(manifest list copied)
while IFS=$'\t' read -r _source target _backup; do
  assert_safe_target_parent "$agent_dir" "$target"
done < <(manifest list linked pi)
while IFS=$'\t' read -r _source target _backup; do
  assert_safe_target_parent "$commands_dir" "$target"
done < <(manifest list commands)
while IFS=$'\t' read -r target _backup; do
  assert_safe_target_parent "$agent_dir" "$target"
done < <(manifest list retired pi)
while IFS=$'\t' read -r _source target _backup; do
  assert_safe_target_parent "$shared_skills_dir" "$target"
done < <(manifest list shared)
while IFS=$'\t' read -r target _backup; do
  assert_safe_target_parent "$shared_skills_dir" "$target"
done < <(manifest list retired shared)
while IFS=$'\t' read -r target _backup; do
  assert_safe_target_parent "$commands_dir" "$target"
done < <(manifest list retired commands)
if "$manage_macos_launch_agents"; then
  assert_safe_target_parent "$macos_launch_agents_dir" ""
  while IFS=$'\t' read -r _source target _backup; do
    assert_safe_target_parent "$macos_launch_agents_dir" "$target"
  done < <(manifest list macosLaunchAgents)
fi

settings_override=()
local_override_entries=()
while IFS=$'\t' read -r relative; do
  local_override_entries+=("$relative")
done < <(manifest list localOverrides)
if ((${#local_override_entries[@]} > 1)); then
  echo "Manifest supports at most one local settings override" >&2
  exit 1
fi
if ((${#local_override_entries[@]} == 1)) && [[ -f "${repo_dir}/${local_override_entries[0]}" ]]; then
  settings_override+=("${repo_dir}/${local_override_entries[0]}")
fi
render_settings_args=(
  node
  "${repo_dir}/scripts/render-settings.mjs"
  "${repo_dir}/${rendered_source}"
)
if ((${#settings_override[@]})); then
  render_settings_args+=("${settings_override[0]}")
fi
prewalk_checkout="${HOME}/Developer/pi-prewalk"
if [[ -e "$prewalk_checkout" ]]; then
  if ! git -C "$prewalk_checkout" rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "Canonical Prewalk checkout is not a Git working tree: $prewalk_checkout" >&2
    exit 1
  fi
  render_settings_args+=(--prewalk-source "$prewalk_checkout")
fi
if [[ -f "$settings_target" && ! -L "$settings_target" ]]; then
  render_settings_args+=(--existing-settings "$settings_target")
fi
while IFS=$'\t' read -r key; do
  render_settings_args+=(--managed-key "$key")
done < <(manifest list settingsManagedKeys)
render_settings_args+=(--package-source "$repo_real_dir")
rendered_settings="$("${render_settings_args[@]}")"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
backup_dir="${agent_dir}/backups/${timestamp}"
assert_safe_target_parent "$agent_dir" "backups/${timestamp}"

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

while IFS=$'\t' read -r relative backup_relative; do
  target_path="${agent_dir}/${relative}"
  if [[ -e "$target_path" || -L "$target_path" ]]; then
    run mkdir -p "${backup_dir}/$(dirname "$backup_relative")"
    run mv "$target_path" "${backup_dir}/${backup_relative}"
  fi
done < <(manifest list retired pi)
while IFS=$'\t' read -r relative backup_relative; do
  target_path="${shared_skills_dir}/${relative}"
  if [[ -e "$target_path" || -L "$target_path" ]]; then
    run mkdir -p "${backup_dir}/$(dirname "$backup_relative")"
    run mv "$target_path" "${backup_dir}/${backup_relative}"
  fi
done < <(manifest list retired shared)
while IFS=$'\t' read -r relative backup_relative; do
  target_path="${commands_dir}/${relative}"
  if [[ -e "$target_path" || -L "$target_path" ]]; then
    run mkdir -p "${backup_dir}/$(dirname "$backup_relative")"
    run mv "$target_path" "${backup_dir}/${backup_relative}"
  fi
done < <(manifest list retired commands)

if [[ -f "$settings_target" && ! -L "$settings_target" ]] && cmp -s <(printf '%s\n' "$rendered_settings") "$settings_target"; then
  echo "unchanged: ${rendered_target} (managed setup settings + live Pi preferences)"
else
  if [[ -e "$settings_target" || -L "$settings_target" ]]; then
    run mkdir -p "$backup_dir"
    run mv "$settings_target" "${backup_dir}/${rendered_target}"
  fi
  if "$dry_run"; then
    echo "would render: ${rendered_target} (managed setup settings + live Pi preferences)"
  else
    settings_tmp="${settings_target}.tmp.$$"
    printf '%s\n' "$rendered_settings" > "$settings_tmp"
    mv "$settings_tmp" "$settings_target"
  fi
fi

while IFS=$'\t' read -r source relative _backup; do
  source_path="${repo_dir}/${source}"
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
done < <(manifest list copied)

if "$manage_macos_launch_agents"; then
  while IFS=$'\t' read -r source relative backup_relative; do
    source_path="${repo_dir}/${source}"
    target_path="${macos_launch_agents_dir}/${relative}"

    if [[ -f "$target_path" && ! -L "$target_path" ]] && cmp -s "$source_path" "$target_path"; then
      echo "unchanged: macOS LaunchAgent ${relative}"
      continue
    fi

    if [[ -e "$target_path" || -L "$target_path" ]]; then
      run mkdir -p "${backup_dir}/$(dirname "$backup_relative")"
      run mv "$target_path" "${backup_dir}/${backup_relative}"
    fi

    run mkdir -p "$macos_launch_agents_dir"
    run cp -p "$source_path" "$target_path"
  done < <(manifest list macosLaunchAgents)
fi

link_owned() {
  local source_path="$1"
  local target_path="$2"
  local backup_relative="$3"
  local description="$4"

  if [[ -L "$target_path" ]] && [[ "$(readlink "$target_path")" == "$source_path" ]]; then
    echo "unchanged: ${description} -> ${source_path}"
    return
  fi

  if [[ -e "$target_path" || -L "$target_path" ]]; then
    run mkdir -p "${backup_dir}/$(dirname "$backup_relative")"
    run mv "$target_path" "${backup_dir}/${backup_relative}"
  fi
  run mkdir -p "$(dirname "$target_path")"
  run ln -s "$source_path" "$target_path"
}

while IFS=$'\t' read -r source target backup_relative; do
  link_owned "${repo_dir}/${source}" "${agent_dir}/${target}" "${backup_relative}" "${target}"
done < <(manifest list linked pi)
while IFS=$'\t' read -r source target backup_relative; do
  link_owned "${repo_dir}/${source}" "${commands_dir}/${target}" "${backup_relative}" "command/${target}"
done < <(manifest list commands)
while IFS=$'\t' read -r source target backup_relative; do
  link_owned "${repo_dir}/${source}" "${shared_skills_dir}/${target}" "${backup_relative}" "shared/${target}"
done < <(manifest list shared)

echo "Setup complete: Pi at $agent_dir; shared skills at $shared_skills_dir; commands at $commands_dir"
if "$manage_macos_launch_agents"; then
  echo "macOS tmux LaunchAgent installed."
  run "${repo_dir}/scripts/activate-macos-tmux-gui-server.sh" --auto
fi
