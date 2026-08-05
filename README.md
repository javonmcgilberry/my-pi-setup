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
- Local footer and Herdr state extensions
- The npm dependencies that install the rest of the Pi toolchain

## Install

```sh
git clone --recurse-submodules https://github.com/javonmcgilberry/my-pi-setup.git pi
cd pi
./setup.sh --dry-run
./setup.sh
```

## Daily workflow

Start Pi from this checkout so it automatically reads the repository workflow
in `AGENTS.md`:

```sh
cd ~/Developer/my-pi-setup
pi
```

Ask Pi to make the setup change here, not under `~/.pi/agent`. A useful prompt
is:

> Update my canonical Pi setup to ____. Validate it, but wait for my approval
> before syncing it live.

After reviewing the change, close every Pi session and run one command:

```sh
./sync
```

That command pulls, validates, commits, pushes, and applies the setup. It refuses
to touch the live agent directory while Pi sessions are running. To explicitly
upgrade npm dependencies, Git pins, and the Prewalk submodule first, run:

```sh
./sync --update
```

Use `./sync` for normal configuration changes. Use `./sync --update` only when
you intentionally want newer dependencies or tracked revisions. Both commands
commit, push, and apply changes, so they are publication commands rather than
read-only checks.

The installer renders tracked defaults plus an optional local override into
`${PI_AGENT_DIR:-~/.pi/agent}` and backs up files before replacing them. Pi
installs configured packages in its managed `npm/` and `git/` directories when
it starts; setup does not create a duplicate root `node_modules` tree.

Prewalk, pretty-footer, and Herdr are linked to this checkout. Edit them here,
not under `~/.pi/agent`. Context Mode uses a pinned commit from my fork;
pi-subagents uses the unmodified upstream npm release.

Use `./scripts/drift.sh` to inspect live-file drift without changing anything.
Every apply backs up replaced files under a unique directory in
`~/.pi/agent/backups`; restore one with `./scripts/restore.sh <backup-dir>`.

Machine-only choices go in `settings.local.json`, which Git ignores. Copy
`settings.local.example.json` to start. The `settings` object merges into the
tracked defaults. Arrays replace tracked arrays. `packageReplacements` swaps a
pinned package source for a local checkout without copying the whole package
list.

```json
{
  "settings": {
    "defaultProjectTrust": "always"
  },
  "packageReplacements": {}
}
```

Run the dry run before reinstalling. It shows every live file that differs from
the tracked copy, which helps catch local experiments before they get replaced.

Useful options:

```sh
./setup.sh --dry-run
PI_AGENT_DIR=/tmp/pi-agent ./setup.sh
```

## Verify

```sh
./scripts/check.sh
```

The check validates JSON, the local-settings merge, shell syntax, dependency
metadata, the tracked-file boundary, and common secret patterns. It does not
inspect or copy `auth.json`.

## Where the code lives

| Part | Source of truth | Live install |
| --- | --- | --- |
| Global config | This repo plus ignored `settings.local.json` | Generated files under `~/.pi/agent` |
| Footer and Herdr extensions | This repo | Symlinks under `~/.pi/agent/extensions` |
| Prewalk | [`pi-prewalk`](https://github.com/javonmcgilberry/pi-prewalk), pinned here as a submodule | `~/.pi/agent/packages/prewalk` symlink |
| Context Mode changes | [`context-mode`](https://github.com/javonmcgilberry/context-mode) | Pinned Pi-managed Git checkout; edit `~/webdev/context-mode` |
| pi-subagents | [`nicobailon/pi-subagents`](https://github.com/nicobailon/pi-subagents) | Exact upstream npm package in `settings.json`; no Prewalk fork policy |
| Pi changes | [`pi`](https://github.com/javonmcgilberry/pi) | Separate development checkout; the normal `pi` command remains the global install |
| Warp gateway | Private `warp-pi-gateway` repo | Edit `~/webdev/warp-pi-gateway`; live extension is a symlink |

Do not edit `~/.pi/agent/npm/node_modules` or `~/.pi/agent/git`. Pi owns those
install directories and may replace them during an update. Runtime folders such
as `sessions`, `prewalk/analytics`, `backups`, `cache`, `intercom`, and Ayu
checkpoints are data, not source code.

## Deliberately excluded

- `auth.json`, API keys, cookies, and trust state
- session transcripts and run history
- caches, generated model lists, databases, logs, and intercom state
- downloaded binaries and `node_modules`
- package-managed plugin source checkouts
- local development checkouts and worktrees
