#!/usr/bin/env bash
set -euo pipefail
[[ $# == 1 ]] || { echo "Usage: ./scripts/restore.sh /path/to/backup" >&2; exit 2; }
backup_dir="$1"
agent_dir="${PI_AGENT_DIR:-${HOME}/.pi/agent}"
[[ -d "$backup_dir" ]] || { echo "Backup directory not found: $backup_dir" >&2; exit 1; }
while IFS= read -r -d '' source; do
  relative="${source#"$backup_dir"/}"
  target="$agent_dir/$relative"
  mkdir -p "$(dirname "$target")"
  [[ -e "$target" || -L "$target" ]] && mv "$target" "${target}.before-restore.$$"
  mv "$source" "$target"
done < <(find "$backup_dir" -type f -print0)
echo "Restored backup into $agent_dir"
