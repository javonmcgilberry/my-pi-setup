# my Pi setup

This repo is the portable part of my [Pi](https://github.com/earendil-works/pi)
setup. It tracks the settings and extensions I actually want to maintain. It
does not track credentials, conversations, caches, analytics, or other local
runtime data.

[`PRODUCT.md`](PRODUCT.md) is the shared product authority for tracked skills,
extensions, terminal/TUI behavior, and localhost interfaces in this workbench.
Scoped product records may refine it but should not silently contradict it.

Inspired by [davis7dotsh/my-pi-setup](https://github.com/davis7dotsh/my-pi-setup).

## What's included

- OpenAI Codex defaults and model preferences
- Compaction, retry, and subagent defaults
- Context Mode MCP configuration and my Context Mode fork
- Pi Codex Conversion, Auto Trees, Smart BTW, and Prewalk settings
- The exact Prewalk revision, pinned as a Git submodule while Prewalk keeps its own history
- Local footer, session-spend dashboard, and Herdr state extensions
- The Webflow Designer Chrome-for-Testing skill and its deterministic runtime helpers
- The npm dependencies that install the rest of the Pi toolchain

## Install

```sh
git clone --recurse-submodules https://github.com/javonmcgilberry/my-pi-setup.git ~/Developer/my-pi-setup
cd ~/Developer/my-pi-setup
./setup.sh --dry-run
./setup.sh
```

### Webflow browser prerequisites

The tracked Webflow skill deliberately does not install or control normal
Google Chrome. Pi should use its native `agent_browser` extension when that
tool is available; other compatible harnesses can invoke the `agent-browser`
CLI directly. The current native extension delegates to the same executable,
so install the pinned CLI runtime for either invocation path:

```sh
npm install -g agent-browser@0.33.2
npx --yes puppeteer browsers install chrome@stable
```

The currently verified Chrome for Testing build is `151.0.7922.71`; the runtime
selects the newest installed Puppeteer build and refuses to fall back to
`/Applications/Google Chrome.app`. Verify the local prerequisites with:

```sh
agent-browser --version
python3 skills/webflow-designer-agent-browser/scripts/browser-runtime.py plan
```

Initialize the dedicated profile once. Fully quit normal Chrome before copying
its profile; the helper refuses a locked source. The default source is
`~/Library/Application Support/Google/Chrome/Default`. Pass
`--source-profile "Profile 1"` (or the applicable directory name) when the
desired Chrome profile is not `Default`.

```sh
runtime=skills/webflow-designer-agent-browser/scripts/browser-runtime.py
python3 "$runtime" bootstrap --confirm-sensitive-copy
python3 "$runtime" start --headed
# Complete Webflow login in the visible Chrome for Testing window.
python3 "$runtime" stop
```

The copied profile is private machine state, not repository content. Chrome for
Testing may still require its own one-time Webflow login. Bootstrap excludes
`Local State`, cookie databases, saved-login databases, and Web Data; never
extract or move cookies or credentials to avoid that login.

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

Validate before publishing:

```sh
./scripts/check.sh
./scripts/drift.sh
```

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
`${PI_AGENT_DIR:-~/.pi/agent}` and links cross-harness skills into
`${AGENTS_SKILLS_DIR:-~/.agents/skills}`. It backs up files before replacing
them. Pi installs configured packages in its managed `npm/` and `git/`
directories when it starts; setup does not create a duplicate root
`node_modules` tree.

`config/manifest.json` is the authoritative managed install inventory. The
installer, drift checker, and repository checks all validate and consume that
same manifest; do not add a managed path to only one script.

Prewalk, pretty-footer, and Herdr are linked to this checkout. Edit them here,
not under `~/.pi/agent`. Context Mode uses a pinned commit from my fork;
pi-subagents uses the unmodified upstream npm release.

The Webflow skill is installed once under `~/.agents/skills` so Pi and other
compatible harnesses can discover the same implementation without duplicate
skill-name collisions. It uses the global `agent-browser` CLI and a locally
installed Chrome for Testing binary. Its authenticated browser profile,
cookies, leases, and runtime records stay under
`~/.config/webflow-designer-agent-browser` and are intentionally not copied
into this repository.

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
PI_AGENT_DIR=/tmp/pi-agent AGENTS_SKILLS_DIR=/tmp/agents-skills ./setup.sh
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
| Session-spend dashboard | `extensions/session-spend-dashboard` in this repo | `~/.pi/agent/extensions/session-spend-dashboard` symlink |
| Webflow Designer browser skill | `skills/webflow-designer-agent-browser` in this repo | `~/.agents/skills/webflow-designer-agent-browser` symlink shared across compatible harnesses |
| Prewalk | [`pi-prewalk`](https://github.com/javonmcgilberry/pi-prewalk), pinned here as a submodule | `~/.pi/agent/packages/prewalk` symlink |
| Context Mode changes | [`context-mode`](https://github.com/javonmcgilberry/context-mode) | Pinned Pi-managed Git checkout; edit `~/webdev/context-mode` |
| pi-subagents | [`nicobailon/pi-subagents`](https://github.com/nicobailon/pi-subagents) | Exact upstream npm package in `settings.json`; no Prewalk fork policy |
| Pi core changes | `~/Developer/pi` ([`javonmcgilberry/pi`](https://github.com/javonmcgilberry/pi)) | Separate development checkout; the normal `pi` command remains the global install |
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
