# my pi setup

My portable, opinionated [Pi](https://github.com/badlogic/pi-mono) configuration.
It keeps the parts I intentionally maintain—settings, package declarations, and
local extensions—without committing credentials, sessions, caches, or other
machine-local state.

Inspired by [davis7dotsh/my-pi-setup](https://github.com/davis7dotsh/my-pi-setup).

## What's included

- OpenAI Codex defaults and model preferences
- Compaction, retry, and subagent defaults
- Context-mode MCP configuration
- The Context Mode fork with Pi Code Mode trace accounting
- Pi Codex Conversion, Auto Trees, Explore Subagents, Smart BTW, and Prewalk settings
- The exact Prewalk revision, pinned as a Git submodule while Prewalk keeps its own history
- Local footer and Herdr state extensions
- The npm dependencies that install the rest of the Pi toolchain

## Install

```sh
git clone --recurse-submodules https://github.com/javonmcgilberry/my-pi-setup.git pi
cd pi
./setup.sh --dry-run
./setup.sh
```

The installer copies the managed files into `${PI_AGENT_DIR:-~/.pi/agent}`. If a
different file already exists, it is backed up under
`~/.pi/agent/backups/<timestamp>/` before replacement. Package installation runs
through npm unless `--skip-install` is supplied. The installer links
`~/.pi/agent/packages/prewalk` to this checkout, so local Prewalk edits are
immediately testable without copying source into a hidden directory.
Context Mode is loaded from `javonmcgilberry/context-mode`, while pi-subagents
remains the unmodified upstream npm package.

Useful options:

```sh
./setup.sh --dry-run
./setup.sh --skip-install
PI_AGENT_DIR=/tmp/pi-agent ./setup.sh --skip-install
```

## Verify

```sh
./scripts/check.sh
```

The check validates JSON and shell syntax, the tracked-file boundary, dependency
metadata, and common secret patterns. It intentionally does not inspect or copy
your existing `auth.json`.

## Deliberately excluded

- `auth.json`, API keys, cookies, and trust state
- session transcripts and run history
- caches, generated model lists, databases, logs, and intercom state
- downloaded binaries and `node_modules`
- package-managed plugin source checkouts
