# my Pi setup

This repo is the portable part of my [Pi](https://github.com/earendil-works/pi)
setup. It tracks the settings and extensions I actually want to maintain. It
does not track credentials, conversations, caches, analytics, or other local
runtime data.

Inspired by [davis7dotsh/my-pi-setup](https://github.com/davis7dotsh/my-pi-setup).

## What's included

- OpenAI Codex defaults and model preferences
- Compaction, retry, and subagent defaults
- Context Mode MCP configuration and my Context Mode fork
- Pi Codex Conversion, Auto Trees, Explore Subagents, Smart BTW, and Prewalk settings
- The exact Prewalk revision, pinned as a Git submodule while Prewalk keeps its own history
- Local footer and Herdr state extensions. These files are copied into the live
  Pi directory by the installer; the copies in this repo are the source of truth.
- The npm dependencies that install the rest of the Pi toolchain

## Install

```sh
git clone --recurse-submodules https://github.com/javonmcgilberry/my-pi-setup.git pi
cd pi
./setup.sh --dry-run
./setup.sh
```

The installer copies managed files into `${PI_AGENT_DIR:-~/.pi/agent}`. If a
different file is already there, it moves a backup to
`~/.pi/agent/backups/<timestamp>/` first. It runs npm unless you pass
`--skip-install`.

Prewalk is different: the installer links `~/.pi/agent/packages/prewalk` to the
Git submodule in this checkout. That makes local Prewalk changes available right
away. Context Mode loads from my GitHub fork. pi-subagents still comes from npm
in the portable setup, even when I temporarily point my live machine at a local
development checkout.

Run the dry run before reinstalling. It shows every live file that differs from
the tracked copy, which helps catch local experiments before they get replaced.

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

## Where the code lives

| Part | Source of truth | Live install |
| --- | --- | --- |
| Setup and copied extensions | This repo | Files under `~/.pi/agent` |
| Prewalk | [`pi-prewalk`](https://github.com/javonmcgilberry/pi-prewalk), pinned here as a submodule | `~/.pi/agent/packages/prewalk` symlink |
| Context Mode changes | [`context-mode`](https://github.com/javonmcgilberry/context-mode) | Pi-managed Git checkout |
| pi-subagents changes | [`pi-subagents`](https://github.com/javonmcgilberry/pi-subagents) | npm by default; local checkout only while developing |
| Pi changes | [`pi`](https://github.com/javonmcgilberry/pi) | Separate development checkout |

`warp-pi-gateway` is currently a separate local project. Its extension is linked
into the live Pi directory, but this repo does not install or publish it. Runtime
folders such as `sessions`, `prewalk/analytics`, `backups`, `cache`, `intercom`,
and Ayu checkpoints are data, not source code.

## Deliberately excluded

- `auth.json`, API keys, cookies, and trust state
- session transcripts and run history
- caches, generated model lists, databases, logs, and intercom state
- downloaded binaries and `node_modules`
- package-managed plugin source checkouts
- local development checkouts and worktrees
