#!/usr/bin/env bash
set -euo pipefail
[[ $# == 1 ]] || { echo "Usage: ./scripts/restore.sh /path/to/backup" >&2; exit 2; }
backup_dir="$1"
agent_dir="${PI_AGENT_DIR:-${HOME}/.pi/agent}"
shared_skills_dir="${AGENTS_SKILLS_DIR:-${HOME}/.agents/skills}"
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
manifest_script="${repo_dir}/scripts/manifest.mjs"
[[ -d "$backup_dir" ]] || { echo "Backup directory not found: $backup_dir" >&2; exit 1; }
[[ -L "$backup_dir" ]] && {
  echo "Refusing symlinked backup root: $backup_dir" >&2
  exit 1
}
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
}
assert_safe_backup_parent() {
  local relative="$1"
  local parent_relative="${relative%/*}"
  [[ "$parent_relative" == "$relative" ]] && parent_relative="."
  if ! python3 - "$backup_dir" "$parent_relative" <<'PY'
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
    echo "Refusing backup entry outside backup root: ${backup_dir}/${relative}" >&2
    exit 1
  fi
}
restore_pi() {
  local relative="$1"
  local backup_relative="$2"
  local source="$backup_dir/$backup_relative"
  local target="$agent_dir/$relative"
  assert_safe_target_parent "$agent_dir" "$relative"
  assert_safe_backup_parent "$backup_relative"
  if [[ -e "$source" || -L "$source" ]]; then
    mkdir -p "$(dirname "$target")"
    if [[ -e "$target" || -L "$target" ]]; then
      mv "$target" "${target}.before-restore.$$"
    fi
    mv "$source" "$target"
  fi
}
restore_shared() {
  local relative="$1"
  local backup_relative="$2"
  local source="$backup_dir/$backup_relative"
  local target="$shared_skills_dir/$relative"
  assert_safe_target_parent "$shared_skills_dir" "$relative"
  assert_safe_backup_parent "$backup_relative"
  if [[ -e "$source" || -L "$source" ]]; then
    mkdir -p "$(dirname "$target")"
    if [[ -e "$target" || -L "$target" ]]; then
      mv "$target" "${target}.before-restore.$$"
    fi
    mv "$source" "$target"
  fi
}
restore_lists="$(mktemp -d "${TMPDIR:-/tmp}/my-pi-restore.XXXXXX")"
trap 'rm -rf "$restore_lists"' EXIT
node "$manifest_script" list rendered > "$restore_lists/rendered"
node "$manifest_script" list copied > "$restore_lists/copied"
node "$manifest_script" list linked pi > "$restore_lists/linked"
node "$manifest_script" list retired pi > "$restore_lists/retired"
node "$manifest_script" list shared > "$restore_lists/shared"
node "$manifest_script" list retired shared > "$restore_lists/shared-retired"
while IFS=$'\t' read -r _source relative backup_relative; do
  restore_pi "$relative" "$backup_relative"
done < "$restore_lists/rendered"
while IFS=$'\t' read -r _source relative backup_relative; do
  restore_pi "$relative" "$backup_relative"
done < "$restore_lists/copied"
while IFS=$'\t' read -r _source relative backup_relative; do
  restore_pi "$relative" "$backup_relative"
done < "$restore_lists/linked"
while IFS=$'\t' read -r relative backup_relative; do
  restore_pi "$relative" "$backup_relative"
done < "$restore_lists/retired"
while IFS=$'\t' read -r _source relative backup_relative; do
  restore_shared "$relative" "$backup_relative"
done < "$restore_lists/shared"
while IFS=$'\t' read -r relative backup_relative; do
  restore_shared "$relative" "$backup_relative"
done < "$restore_lists/shared-retired"
echo "Restored backup into $agent_dir"
