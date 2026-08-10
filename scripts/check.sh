#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

fast=0
for argument in "$@"; do
	case "$argument" in
	--fast) fast=1 ;;
	*)
		echo "usage: scripts/check.sh [--fast]" >&2
		exit 2
		;;
	esac
done

bash -n setup.sh scripts/check.sh scripts/drift.sh scripts/restore.sh scripts/land.sh scripts/pi-update-all scripts/activate-macos-tmux-gui-server.sh
if command -v plutil >/dev/null 2>&1; then
	plutil -lint config/com.javonmcgilberry.pi-tmux-gui-server.plist >/dev/null
fi
node --check scripts/render-settings.mjs
node --check scripts/json-equal.mjs
node --check scripts/manifest.mjs
node --check scripts/session-maintenance.mjs

json_files=(
	settings.json
	mcp.json
	pi-autoname.json
	pi-auto-trees.json
	pi-codex-conversion.json
	pi-smart-btw.json
	prewalk.json
	package.json
	package-lock.json
	settings.local.example.json
	agent-browser-policy.json
	config/manifest.json
	fzf.json
	session-spend-dashboard.json
	skills/webflow-designer-agent-browser/capabilities.json
	skills/webflow-designer-agent-browser/config/attachment.json
)

node -e 'for (const file of process.argv.slice(1)) JSON.parse(require("fs").readFileSync(file, "utf8"))' "${json_files[@]}"
node scripts/render-settings.mjs settings.json settings.local.example.json >/dev/null
node scripts/manifest.mjs validate >/dev/null

python3 -B -m unittest discover \
	-s skills/webflow-designer-agent-browser/scripts \
	-p 'test_*.py'
python3 -B skills/webflow-designer-agent-browser/scripts/capability-catalog.py validate
node --test scripts/manifest.test.mjs
node --test scripts/render-settings.test.mjs
if [[ "$fast" -eq 1 ]]; then
	echo "Fast mode: skipping scripts/setup.test.mjs (the full setup.sh matrix)"
else
	node --test scripts/setup.test.mjs
fi
node --test scripts/macos-tmux-gui-server.test.mjs
node --test scripts/session-metadata-backfill.test.mjs
node --test packages/context-budget/context-budget.test.mjs packages/context-budget/index.test.ts
node --test extensions/agent-browser-policy.test.mjs
node --test extensions/warp-session-title.test.mjs
node --test scripts/land.test.mjs
node --check skills/webflow-designer-agent-browser/scripts/cdp-frame-eval.mjs
node --check skills/webflow-designer-agent-browser/scripts/cookie-transfer.mjs
node --test skills/webflow-designer-agent-browser/scripts/cookie-transfer.test.mjs
node --test extensions/session-spend-dashboard/test/*.test.ts

file_inventory="$(git ls-files --cached --others --exclude-standard)"
if ! node scripts/manifest.mjs check-inventory <<<"$file_inventory"; then
	echo "Repository files include a manifest-declared runtime exclusion" >&2
	exit 1
fi
forbidden_paths='\.(db|sqlite|pem|key|pyc)$'
if grep -E "$forbidden_paths" <<<"$file_inventory"; then
	echo "Repository files include forbidden runtime, browser-profile, or credential material" >&2
	exit 1
fi

if git grep -nEI "(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|authorization[[:space:]]*:[[:space:]]*bearer)" -- . ':!scripts/check.sh'; then
	echo "Potential secret found in tracked content" >&2
	exit 1
fi

git diff --check
if [[ "$fast" -eq 1 ]]; then
	echo "Fast checks passed. Run scripts/check.sh without --fast for the setup matrix."
else
	echo "All checks passed."
fi
