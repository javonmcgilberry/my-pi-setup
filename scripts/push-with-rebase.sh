#!/usr/bin/env bash
set -euo pipefail

repo_dir="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$repo_dir"

branch="$(git symbolic-ref --quiet --short HEAD || true)"
if [[ -z "$branch" ]]; then
	echo "land: cannot push from a detached HEAD." >&2
	exit 1
fi

upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
if [[ -z "$upstream" ]]; then
	echo "land: branch $branch has no tracked upstream." >&2
	exit 1
fi

remote="$(git config --get "branch.$branch.remote" || true)"
if [[ -z "$remote" || "$remote" == "." ]]; then
	echo "land: branch $branch does not track a pushable remote." >&2
	exit 1
fi

max_attempts=3
attempt=1

while (( attempt <= max_attempts )); do
	echo "land: fetching $remote before push..."
	GIT_TERMINAL_PROMPT=0 git fetch --prune "$remote"

	if ! git merge-base --is-ancestor "$upstream" HEAD; then
		if [[ -n "$(git status --porcelain)" ]]; then
			echo "land: $upstream moved, but the worktree has uncommitted changes." >&2
			echo "land: commit or stash them, then run scripts/land.sh --push again." >&2
			exit 1
		fi

		echo "land: rebasing unpublished commits onto $upstream..."
		if ! GIT_EDITOR=true git rebase "$upstream"; then
			git rebase --abort >/dev/null 2>&1 || true
			echo "land: automatic rebase conflicted and was aborted; your local commits are unchanged." >&2
			echo "land: resolve the remote changes manually, then run scripts/land.sh --push again." >&2
			exit 1
		fi
	fi

	echo "land: pushing..."
	if GIT_TERMINAL_PROMPT=0 git push; then
		echo "land: pushed to $(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || echo upstream)."
		exit 0
	fi

	# A writer can publish after our fetch but before our push. Retry only when
	# the tracked branch actually advanced; authentication and network failures
	# should fail immediately instead of being repeated.
	GIT_TERMINAL_PROMPT=0 git fetch --prune "$remote"
	if git merge-base --is-ancestor "$upstream" HEAD; then
		echo "land: push failed without a remote branch update; not retrying." >&2
		exit 1
	fi

	if (( attempt == max_attempts )); then
		echo "land: the remote kept changing; stopped after $max_attempts attempts." >&2
		exit 1
	fi

	attempt=$((attempt + 1))
	echo "land: $upstream changed during the push; retrying ($attempt/$max_attempts)..."
done
