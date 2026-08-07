#!/usr/bin/env bash
# The one supported way to commit in this repository.
#
# Every caller — Pi's /sync-me, a terminal, another agent — goes through here,
# so no commit can skip validation. scripts/check.sh already carries the secret
# scan, the forbidden-path scan, and the manifest inventory check, so running it
# before staging is what makes a commit trustworthy. Hand-rolled `git commit`
# skips all of that.
#
# Non-interactive by design: the message arrives as an argument, never a prompt.
# Idempotent: a clean tree succeeds and does nothing.
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

message=""
push=0
full=0
paths=()

usage() {
	cat >&2 <<'USAGE'
usage: scripts/land.sh --message <text> [--path <pathspec>]... [--push] [--full]

  --message, -m  Commit message. Required unless the tree is already clean.
  --path         Restrict the commit to a pathspec. Repeatable. Default: all changes.
  --push         Push to the tracked upstream after a successful commit.
  --full         Run the complete check suite instead of check.sh --fast.
USAGE
	exit 2
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--message | -m)
		[[ $# -ge 2 ]] || usage
		message="$2"
		shift 2
		;;
	--path)
		[[ $# -ge 2 ]] || usage
		paths+=("$2")
		shift 2
		;;
	--push)
		push=1
		shift
		;;
	--full)
		full=1
		shift
		;;
	*) usage ;;
	esac
done

# Idempotent: nothing staged, nothing changed, nothing untracked means there is
# nothing to commit. --push is still honored below, so `land.sh --push` always
# means "make the remote match local" rather than silently doing nothing.
if [[ -z "$(git status --porcelain -- "${paths[@]:-.}")" ]]; then
	echo "land: nothing to commit."
else
	[[ -n "$message" ]] || usage

	echo "land: validating before staging anything..."
	if [[ "$full" -eq 1 ]]; then
		./scripts/check.sh
	else
		./scripts/check.sh --fast
	fi

	git add -- "${paths[@]:-.}"

	# Re-check: check.sh can reformat files, and `git add` may have staged nothing
	# when the only pathspec matches an ignored file.
	if git diff --cached --quiet; then
		echo "land: nothing staged after validation; no commit created."
	else
		git commit -m "$message"
		echo "land: committed $(git rev-parse --short HEAD)."
	fi
fi

if [[ "$push" -eq 1 ]]; then
	if [[ -z "$(git log --branches --not --remotes --oneline)" ]]; then
		echo "land: nothing to push."
		exit 0
	fi
	echo "land: pushing..."
	GIT_TERMINAL_PROMPT=0 git push
	echo "land: pushed to $(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || echo upstream)."
fi
