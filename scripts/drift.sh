#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
agent_dir="${PI_AGENT_DIR:-${HOME}/.pi/agent}"
shared_skills_dir="${AGENTS_SKILLS_DIR:-${HOME}/.agents/skills}"
manifest_script="${repo_dir}/scripts/manifest.mjs"
repo_real_dir="$(cd -P "$repo_dir" && pwd)"
assert_read_root() {
  local root="$1"
  if [[ -L "$root" ]]; then
    echo "Refusing symlinked comparison root: $root" >&2
    exit 1
  fi
  local probe="${root%/}"
  [[ -z "$probe" ]] && probe="/"
  while [[ "$probe" != "/" ]]; do
    if [[ -L "$probe" && "$probe" != "/tmp" && "$probe" != "/var" ]]; then
      echo "Refusing symlinked comparison ancestor: $probe" >&2
      exit 1
    fi
    probe="$(dirname "$probe")"
  done
}
assert_read_root "$agent_dir"
assert_read_root "$shared_skills_dir"
assert_read_target_parent() {
  local root="$1"
  local relative="$2"
  local current="$root"
  local parts=()
  IFS='/' read -r -a parts <<< "$relative"
  local last_index=$((${#parts[@]} - 1))
  for ((index = 0; index < last_index; index += 1)); do
    current="${current}/${parts[index]}"
    if [[ -L "$current" ]]; then
      echo "Refusing symlinked comparison target parent: $current" >&2
      exit 1
    fi
  done
}
while IFS=$'\t' read -r _source target _backup; do
  assert_read_target_parent "$agent_dir" "$target"
done < <(node "$manifest_script" list rendered)
while IFS=$'\t' read -r _source target _backup; do
  assert_read_target_parent "$agent_dir" "$target"
done < <(node "$manifest_script" list copied)
while IFS=$'\t' read -r _source target _backup; do
  assert_read_target_parent "$agent_dir" "$target"
done < <(node "$manifest_script" list linked pi)
while IFS=$'\t' read -r target _backup; do
  assert_read_target_parent "$agent_dir" "$target"
done < <(node "$manifest_script" list retired pi)
while IFS=$'\t' read -r target; do
  assert_read_target_parent "$agent_dir" "$target"
done < <(node "$manifest_script" list externalLinks)
while IFS=$'\t' read -r _source target _backup; do
  assert_read_target_parent "$shared_skills_dir" "$target"
done < <(node "$manifest_script" list shared)
while IFS=$'\t' read -r target _backup; do
  assert_read_target_parent "$shared_skills_dir" "$target"
done < <(node "$manifest_script" list retired shared)
tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/my-pi-drift.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT
PI_AGENT_DIR="$tmp_dir/agent" AGENTS_SKILLS_DIR="$tmp_dir/shared-skills" "$repo_dir/setup.sh" >/dev/null
manifest() {
  node "$manifest_script" "$@"
}
found=false
check_copied() {
  local source="$1"
  local relative="$2"
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
}

while IFS=$'\t' read -r _source relative _backup; do
  check_copied "$_source" "$relative"
done < <(manifest list rendered)
while IFS=$'\t' read -r source relative _backup; do
  check_copied "$source" "$relative"
done < <(manifest list copied)

while IFS=$'\t' read -r source relative _backup; do
  target="$agent_dir/$relative"
  if [[ ! -e "$repo_dir/$source" ]]; then
    echo "different: $relative (repository source is missing)"; found=true
  elif [[ ! -L "$target" ]]; then
    echo "different: $relative (expected repository link)"; found=true
  elif [[ "$(readlink "$target")" != "$repo_dir/$source" ]]; then
    echo "different: $relative -> $(readlink "$target")"; found=true
  fi
done < <(manifest list linked pi)

while IFS=$'\t' read -r source relative _backup; do
  target="$shared_skills_dir/$relative"
  if [[ ! -e "$repo_dir/$source" ]]; then
    echo "different: shared/${relative} (repository source is missing)"; found=true
  elif [[ ! -L "$target" ]]; then
    echo "different: shared/${relative} (expected repository link)"; found=true
  elif [[ "$(readlink "$target")" != "$repo_dir/$source" ]]; then
    echo "different: shared/${relative} -> $(readlink "$target")"; found=true
  fi
done < <(manifest list shared)

while IFS=$'\t' read -r relative; do
  target="$agent_dir/$relative"
  if [[ -L "$target" ]] && resolved="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$target")" && [[ "$resolved" == "$repo_real_dir" || "$resolved" == "$repo_real_dir/"* ]]; then
    echo "different: external target unexpectedly points into this repository: $relative"; found=true
  fi
done < <(manifest list externalLinks)

while IFS=$'\t' read -r relative _backup; do
  target="$agent_dir/$relative"
  if [[ -e "$target" || -L "$target" ]]; then
    echo "obsolete: $relative (declared retired target still exists)"; found=true
  fi
done < <(manifest list retired pi)
while IFS=$'\t' read -r relative _backup; do
  target="$shared_skills_dir/$relative"
  if [[ -e "$target" || -L "$target" ]]; then
    echo "obsolete: shared/$relative (declared retired target still exists)"; found=true
  fi
done < <(manifest list retired shared)
[[ "$found" == false ]] && echo "No managed file drift detected."
