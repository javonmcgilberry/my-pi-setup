#!/usr/bin/env bash
set -euo pipefail
[[ $# == 1 ]] || { echo "Usage: ./scripts/restore.sh /path/to/backup" >&2; exit 2; }
backup_dir="$1"
agent_dir="${PI_AGENT_DIR:-${HOME}/.pi/agent}"
shared_skills_dir="${AGENTS_SKILLS_DIR:-${HOME}/.agents/skills}"
[[ -d "$backup_dir" ]] || { echo "Backup directory not found: $backup_dir" >&2; exit 1; }
shared_skill_backup="$backup_dir/external-agents-skills-webflow-designer-agent-browser"
if [[ -e "$shared_skill_backup" || -L "$shared_skill_backup" ]]; then
  shared_skill_target="$shared_skills_dir/webflow-designer-agent-browser"
  mkdir -p "$(dirname "$shared_skill_target")"
  if [[ -e "$shared_skill_target" || -L "$shared_skill_target" ]]; then
    mv "$shared_skill_target" "${shared_skill_target}.before-restore.$$"
  fi
  mv "$shared_skill_backup" "$shared_skill_target"
fi
while IFS= read -r -d '' source; do
  relative="${source#"$backup_dir"/}"
  target="$agent_dir/$relative"
  mkdir -p "$(dirname "$target")"
  [[ -e "$target" || -L "$target" ]] && mv "$target" "${target}.before-restore.$$"
  mv "$source" "$target"
done < <(find "$backup_dir" \( -type f -o -type l \) -print0)
echo "Restored backup into $agent_dir"
