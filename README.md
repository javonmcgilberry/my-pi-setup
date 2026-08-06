# My Pi setup

This repository is the portable, maintained source for my
[Pi](https://github.com/earendil-works/pi) setup. It records the configuration,
extensions, skills, and package versions I want to keep. Credentials, chats,
caches, analytics databases, browser profiles, and other machine state stay
local.

It is also an installable Pi package, but it is personal rather than a supported
general-purpose distribution. Other people can inspect, fork, or try it without
an expectation that my machine-specific integrations will work for them.

[`PRODUCT.md`](PRODUCT.md) defines the shared product principles for this
workbench. This README is the operating manual: what is installed, what it
does, where it is configured, and where its source lives.

Inspired by [davis7dotsh/my-pi-setup](https://github.com/davis7dotsh/my-pi-setup).

## Install

```sh
git clone https://github.com/javonmcgilberry/my-pi-setup.git ~/Developer/my-pi-setup
cd ~/Developer/my-pi-setup
./setup.sh --dry-run
./setup.sh
```

The installer combines the defaults in this repository with the optional, ignored
`settings.local.json` and writes the result to `${PI_AGENT_DIR:-~/.pi/agent}`. Shared skills are
linked into `${AGENTS_SKILLS_DIR:-~/.agents/skills}`. Existing files managed by this setup
are backed up before replacement. Pi installs configured packages in its own
managed `npm/` and `git/` directories when it starts. The rendered settings load
this checkout as one local Pi package; setup does not copy its extensions or
create a second root `node_modules` tree.

Someone who only wants the packaged extensions can install a pinned Git commit
without using my global settings or bootstrap:

```sh
pi install git:github.com/javonmcgilberry/my-pi-setup@<commit>
```

Use a temporary install to test without touching the live setup:

```sh
PI_AGENT_DIR=/tmp/pi-agent AGENTS_SKILLS_DIR=/tmp/agents-skills ./setup.sh
```

## Daily workflow

Start Pi in the repository you are changing. Use this checkout only for changes
to the setup package itself:

```sh
cd ~/Developer/my-pi-setup
pi
```

Make setup changes here, not under `~/.pi/agent`. Validate them with:

```sh
./scripts/check.sh
./scripts/drift.sh
```

`drift.sh` is read-only. Git commits, pushes, tags, and package upgrades are
separate explicit operations. When a setup change is ready, close every Pi
session, apply it, and verify the result:

```sh
./setup.sh
./scripts/drift.sh
```

`setup.sh` refuses to replace the live `~/.pi/agent` configuration while Pi is
running. It never changes Git state or upgrades packages.

Keep machine-only choices in ignored `settings.local.json`:

```json
{
  "settings": {
    "defaultProjectTrust": "always"
  },
  "packageReplacements": {}
}
```

Nested settings objects are combined. Arrays replace the corresponding arrays
from the tracked defaults. `packageReplacements` can point a tracked package to
a local checkout without copying the entire package list.

## Core Pi settings

The main defaults live in [`settings.json`](settings.json):

- OpenAI Codex is the default provider and `gpt-5.6-sol` is the default model.
- `openai-codex/gpt-5.6-terra`, `openai-codex/gpt-5.6-sol`,
  `openai-codex/gpt-5.6-luna`, selected Anthropic models, and Cursor's Grok
  models appear in the model-selection list.
- The default thinking level is `medium`.
- Auto-compaction is enabled with 32,768 tokens reserved for the response and
  a 20,000-token recent-history target.
- Automatic retry is enabled.
- Subagent workers inherit the parent context; reviewers start fresh. The
  default child model is Luna with high reasoning.
- Cache-miss notices are visible.

Pi Codex Conversion has its own tracked config in
[`pi-codex-conversion.json`](pi-codex-conversion.json). It uses path mode,
compact tool rendering, Code Mode, fast OpenAI requests, cached WebSockets, and
low response verbosity. Native Responses API compaction is disabled, so normal
Pi compaction handles the conversation.

The local [`context-budget`](packages/context-budget) package keeps the first
request smaller without uninstalling anything. Pi still discovers every skill,
but the model sees a short `skills_catalog` instruction instead of the full
skill list. It can search the catalog and read one skill when needed. Browser,
intercom, MCP, and subagent tools also start inactive; the model can load their
tool group with `activate_capability`. Normal file, shell, web, and diagnostic
tools stay active. When global and project `AGENTS.md` files contain the same
text, only the project copy is sent.

## Installed packages and extensions

The `packages` array in `settings.json` lists the packages Pi loads.
Those npm and Git sources are pinned there because Pi installs them in its own
managed package directories. The root `package.json` describes this repository's
own Pi package, and `package-lock.json` covers only dependencies needed by that
package itself.

| Component | What it does | Configuration and source |
| --- | --- | --- |
| [`pi-mcp-adapter`](https://github.com/nicobailon/pi-mcp-adapter) | Connects Pi to MCP servers and exposes their tools. | Servers are defined in [`mcp.json`](mcp.json). The linked repository owns the package README. |
| [`pi-web-access`](https://github.com/nicobailon/pi-web-access) | Adds web search, URL fetching, repository/PDF extraction, and video analysis. | Provider credentials and runtime choices stay local. The linked repository owns the package README. |
| `context-mode` | Keeps large reads, command output, logs, and web payloads out of model context; indexes compact session memory for later search. | Loaded from a pinned commit of [my Context Mode fork](https://github.com/javonmcgilberry/context-mode) and registered through `mcp.json`. Edit the source checkout, not Pi's copy. |
| [`pi-subagents`](https://github.com/nicobailon/pi-subagents) | Runs delegated agents, parallel tasks, chains, checkpoints, and separate Git worktrees. | Child model and role defaults are in `settings.json`. Uses the unchanged upstream package and its README. |
| [`pi-intercom`](https://www.npmjs.com/package/pi-intercom) | Sends direct messages between local Pi sessions and supports parent/child coordination. | No tracked config. Its installed README is the reference; runtime broker state is local. |
| [`pi-anthropic-oauth`](https://github.com/leohenon/pi-anthropic-oauth) | Adds Claude Pro/Max browser OAuth and token refresh. | OAuth credentials stay in Pi's local auth store. The linked repository owns the package README. |
| [`pi-cursor-sdk`](https://github.com/fitchmultz/pi-cursor-sdk) | Adds models backed by Cursor's local and cloud agent libraries. | Authorization and generated model data stay local. The linked repository owns the package README. |
| [`@howaboua/pi-codex-conversion`](https://github.com/IgorWarzocha/howaboua-pi-stuff/tree/main/packages/pi-codex-conversion) | Adapts Pi prompts, tools, communication, and status for Codex models. | [`pi-codex-conversion.json`](pi-codex-conversion.json). The linked package README has the full command and option reference. |
| [`@howaboua/pi-auto-trees`](https://github.com/IgorWarzocha/howaboua-pi-stuff/tree/main/packages/pi-auto-trees) | Adds marker/end commands and automatic summaries for long-running incremental sessions. | [`pi-auto-trees.json`](pi-auto-trees.json) uses Luna with low reasoning for summaries. The linked package README has the command reference. |
| [`@howaboua/pi-smart-btw`](https://github.com/IgorWarzocha/howaboua-pi-stuff/tree/main/packages/pi-smart-btw) | Runs side questions in ephemeral child Pi processes and injects answers only when requested. | [`pi-smart-btw.json`](pi-smart-btw.json) selects Luna, low reasoning, and the `Alt+Z/C/X/J/K/H/L` controls. The linked package README explains its slots and queues. |
| [`pi-lens`](https://github.com/apmantza/pi-lens) | Runs live Language Server Protocol (LSP), lint, formatting, type, security, and structural checks around edits. | Package defaults plus Pi's generated diagnostic state. The linked repository owns the package README and rule documentation. |
| [`pi-agent-browser-native`](https://github.com/fitchmultz/pi-agent-browser-native) | Exposes `agent-browser` as Pi's native browser automation tool. | Uses the global `agent-browser` CLI and local browser state. The linked repository owns the package README. |
| [`pi-autoname`](https://github.com/ssdiwu/pi-autoname) | Gives a new session a short name, then checks periodically whether the topic has changed enough to rename it. | Pinned at `0.6.8`. [`pi-autoname.json`](pi-autoname.json) uses Luna, waits 10 minutes between checks, and preserves names set with `/name`. |
| Compound Engineering | Provides planning, implementation, review, debugging, shipping, and learning skills. | Loaded from [EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin). The package owns its skill documentation. |
| [`pi-ask-user`](https://github.com/edlsh/pi-ask-user) | Adds the interactive `ask_user` decision UI with search, choices, and freeform input. | No tracked config. The linked repository owns the package README. |
| Prewalk | The chosen planner starts a coding task; later turns go to a configured executor in the same session. | Installed from an exact commit of [`pi-prewalk`](https://github.com/javonmcgilberry/pi-prewalk). [`prewalk.json`](prewalk.json) selects Luna at max reasoning and enables local analytics. |
| Context budget | Keeps the full skill catalog and the largest optional tool schemas out of the first request, then loads them when needed. | [`packages/context-budget`](packages/context-budget), loaded as part of this Pi package. Deferred groups are browser, intercom, MCP, and subagents. |
| [`@vanillagreen/pi-tool-renderer`](https://github.com/vanillagreencom/vstack/tree/main/pi-extensions/pi-tool-renderer) | Replaces noisy tool output with compact, readable renderers. | Renderer modes are under `vstack.extensionManager.config` in `settings.json`. The linked package README has the renderer options. |
| [`pi-render-cache`](https://github.com/axelbaumlisto/pi-render-cache) | Reduces terminal-interface (TUI) streaming work with bounded caches for text segmentation and unstyled Markdown rendering. | Loaded at version `1.1.0`; no tracked config. This is a render-performance cache, not a conversation backup. The linked repository owns the package README. |
| [`@vanillagreen/pi-extension-manager`](https://github.com/vanillagreencom/vstack/tree/main/pi-extensions/pi-extension-manager) | Adds package browsing, update/uninstall actions, diagnostics, and settings editing based on package schemas. | Reads Pi package state and the `vstack` settings namespace. The linked package README has the command and settings reference. |
| [`@kliebhan/pi-prompt-autocomplete`](https://github.com/KLIEBHAN/pi-extensions/tree/main/extensions/prompt-autocomplete) | Provides private inline AI completion while typing prompts. | No tracked config. The linked package README explains its privacy and completion behavior. |
| [`@davecodes/pi-skill-tags`](https://github.com/Davidcreador/pi-skill-tags) | Adds inline skill tags and skill-name autocomplete. | No tracked config. The linked repository owns the package README. |
| [`pi-fzf`](https://github.com/kaofelix/pi-fzf) | Adds configurable fuzzy-search commands. | [`fzf.json`](fzf.json) defines an `@` file picker, preview command, overlay placement, and scroll keys. The linked repository owns the package README. |
| [`@juicesharp/rpiv-warp`](https://github.com/juicesharp/rpiv-mono/tree/main/packages/rpiv-warp) | Sends Pi lifecycle notifications to Warp through OSC 777. | It does nothing outside Warp. The linked package README explains terminal requirements. The separate private Warp gateway links are described below. |

### Extensions maintained here

| Component | What it does | Configuration and source |
| --- | --- | --- |
| Pretty footer | Replaces the footer with model, context, usage, cache, cost, task, and extension status. | [`extensions/pretty-footer.ts`](extensions/pretty-footer.ts), loaded from this Pi package. |
| Herdr agent state | Reports Pi session identity and working, blocked, or idle state to Herdr over its local socket. It does nothing unless `HERDR_ENV=1`, `HERDR_SOCKET_PATH`, and `HERDR_PANE_ID` are all set. | [`extensions/herdr-agent-state.ts`](extensions/herdr-agent-state.ts), loaded from this Pi package. Herdr owns the generated integration format. |
| Session Spend Dashboard | Runs an opt-in read-only localhost dashboard for provider-reported spend, token use, projects, sessions, and subagent activity. | [`extensions/session-spend-dashboard`](extensions/session-spend-dashboard), configured by [`session-spend-dashboard.json`](session-spend-dashboard.json). See its [README](extensions/session-spend-dashboard/README.md). |
| Warp session title | Shows the current Pi session name and project in the active Warp tab. It does nothing in other terminals. | [`extensions/warp-session-title.ts`](extensions/warp-session-title.ts), loaded from this Pi package. |
| Clear status | Older compact usage/status implementation retained for reference but not loaded or packaged. | [`disabled-extensions/clear-status.ts`](disabled-extensions/clear-status.ts). |
| Warp gateway links | Private Warp gateway and fallback extensions maintained in a separate repository. | Live links are `extensions/warp-gateway.ts` and `extensions/warp-link-fallback.ts`; edit `~/webdev/warp-pi-gateway`. |

`REALTIME-SYSTEM-PROMPT.md` is tracked prompt configuration, not an extension.
It changes the realtime conversational mode used by Pi Codex Conversion.

### Managed setup files

The tables above explain the components. This table lists the files that setup
renders or copies into the live agent directory.

| File | Role |
| --- | --- |
| `settings.json` | Rendered from tracked defaults plus `settings.local.json`; controls models, packages, compaction, retry, subagents, and shared package settings. |
| `AGENTS.md` | Gives agents the source-ownership, validation, documentation, and publication rules for this setup. |
| `REALTIME-SYSTEM-PROMPT.md` | Supplies Pi Codex Conversion's realtime conversational prompt. |
| `mcp.json` | Registers the MCP servers listed below. |
| `pi-codex-conversion.json` | Configures the Codex prompt/tool adapter, UI, Code Mode, transport, and native compaction choice. |
| `pi-autoname.json` | Selects the model and cooldown for automatic session names and keeps manual names unchanged. |
| `pi-auto-trees.json` | Configures automatic tree summaries. |
| `pi-smart-btw.json` | Configures side-question models and keyboard controls. |
| `prewalk.json` | Configures the Prewalk executor and analytics. |
| `fzf.json` | Configures fuzzy-search commands and presentation. |
| `session-spend-dashboard.json` | Configures chat and metrics retention windows. |

### Retired paths

The manifest also lists paths that setup removes rather than installs:

- `pi-explore-subagents.json`, an older subagent configuration that is no
  longer part of this setup.
- the old per-extension links, local Prewalk and context-budget package links,
  and root package metadata that the package-first setup no longer installs;
  the first live migration backs these paths up before retiring them.
- `~/.pi/agent/skills/webflow-designer-agent-browser`, the old Pi-only copy of
  the Webflow skill. The shared `~/.agents/skills` link replaces it.

## Model Context Protocol (MCP) servers

[`mcp.json`](mcp.json) defines four servers:

| Server | Purpose | Status |
| --- | --- | --- |
| Context Mode | Sandboxed large-output processing, persistent indexing, and context diagnostics. | Enabled through the local `context-mode` command. |
| Linear | Linear issue and project access through Linear's hosted MCP service. | Enabled; authentication is kept outside tracked config. |
| Buildkite | Read-only Buildkite pipeline, build, job, and log access. | Enabled through Buildkite's read-only hosted endpoint. |
| Chrome DevTools | Chrome inspection through the Chrome DevTools Protocol using `chrome-devtools-mcp`. | Disabled by default. Its configured browser endpoint is localhost port 9333. |

## Shared Webflow browser skill

The tracked
[`skills/webflow-designer-agent-browser`](skills/webflow-designer-agent-browser)
directory is linked once into `~/.agents/skills`, and Pi and other compatible
agent tools share that installation. It is deliberately not duplicated under
`~/.pi/agent/skills`, which would cause a skill-name collision.

When available, the skill uses Pi's native `agent_browser` tool. Otherwise, it
uses the global `agent-browser` CLI. Install the pinned CLI and the stable
Chrome for Testing runtime it uses with:

```sh
npm install -g agent-browser@0.33.2
npx --yes puppeteer browsers install chrome@stable
agent-browser --version
python3 skills/webflow-designer-agent-browser/scripts/browser-runtime.py plan
```

The currently verified Chrome for Testing build is `151.0.7922.71`. The helper
selects the newest installed Puppeteer build and refuses to fall back to normal
Google Chrome.

Initialize the dedicated Chrome for Testing profile once. Quit normal Chrome
completely first; the helper refuses to copy a locked profile.

```sh
runtime=skills/webflow-designer-agent-browser/scripts/browser-runtime.py
python3 "$runtime" bootstrap --confirm-sensitive-copy
python3 "$runtime" start --headed
# Complete Webflow login in the visible Chrome for Testing window.
python3 "$runtime" stop
```

The profile, cookies, leases, and runtime records stay under
`~/.config/webflow-designer-agent-browser`. They are never tracked here.
Bootstrap excludes Chrome's `Local State`, cookie databases, saved-login
databases, and Web Data. It never copies credentials, so the login must be
completed once in the visible Chrome for Testing window.

## Cache, sessions, compaction, and retention

They are related, but each system preserves something different.

### Provider and render caches

Provider prompt caching temporarily lets the provider reuse the beginning of a
prompt. Normal requests keep cached data for a brief provider-defined period.
Setting `PI_CACHE_RETENTION=long` requests longer retention when the provider
supports it: up to 24 hours for OpenAI prompt caching or 1 hour for Anthropic.
A cache hit can reduce input sent or billed, but it is never a backup and is not
guaranteed.

For Codex, cached WebSockets can reuse conversation state and send only what
changed instead of replaying the full chat. A cached connection expires after
5 minutes idle or 55 minutes total. Pi reconnects or falls back to a regular
HTTP event stream when reuse is not available. A session ID can help the
provider route related requests, but that is separate from cache retention.

Compaction and branch-summary requests intentionally use fresh routing and no
prompt-cache retention. `pi-render-cache` is different again: it only avoids
repeating local TUI rendering work.

### Session files and compaction

Pi automatically appends sessions to newline-delimited JSON (JSONL) files. The
default directory is `~/.pi/agent/sessions/`, grouped by working directory.
`PI_CODING_AGENT_SESSION_DIR` can replace the sessions path; otherwise the base
agent directory can be changed with `PI_CODING_AGENT_DIR` or `PI_AGENT_DIR`.
Use `pi --no-session` for an ephemeral session. Useful commands include:

```text
/session              show the current file, ID, tokens, and cost
/resume               reopen a saved session
/new                  start a new session
/tree                 move within the current session tree
/fork                 create a separate session from an earlier user turn
/clone                copy the active branch into a new session
/compact [prompt]     summarize older active context
```

Stock Pi does not automatically expire session files. Compaction appends a
summary and no longer sends older entries to the model, but the old entries stay
in the JSONL transcript. It reduces active model context; it does not erase
chat history.

### Automatic session names

`pi-autoname` names a session after the first completed exchange. After that,
it can reconsider the name when Pi becomes idle and the 10-minute cooldown has
passed. It keeps the current name unless the recent topic has clearly
changed. Run `/autoname` to request a new name right away. Names set with
Pi's `/name` command stay unchanged because `respectManualName` is enabled.

Naming uses `openai-codex/gpt-5.6-luna`. Each request includes a short excerpt
from recent user and assistant messages rather than the full transcript. The
extension removes common API-key, token, password, and private-key patterns
before sending that excerpt. Model failures do not block the session; the
extension can fall back to a local name derived from the conversation.

The package currently reads `~/.pi/agent/pi-autoname.json` directly instead of
honoring `PI_AGENT_DIR`. This repository still owns and installs that file. To
test the extension against another agent directory, use an isolated `HOME` as
well as matching `PI_AGENT_DIR` and `AGENTS_SKILLS_DIR` values.

In Warp, [`extensions/warp-session-title.ts`](extensions/warp-session-title.ts)
sets the tab title to `π - <session name> - <project>` when a session starts or
its name changes. It uses Pi's terminal-title API, which sends the OSC 0
sequence supported by Warp. The installed `rpiv-warp` activity spinner pushes
that title before animation and restores it when Pi stops working. If Warp's
shell integration later replaces the title, start Pi with
`WARP_DISABLE_AUTO_TITLE=true`; Warp documents that variable on its
[Tabs page](https://docs.warp.dev/terminal/windows/tabs/).

Context Mode keeps a separate searchable SQLite knowledge base for compact
session memory. Its indexed memory is not the Pi transcript and can be deleted
with Context Mode's own tools.

### Dashboard retention

[`session-spend-dashboard.json`](session-spend-dashboard.json) is configured to keep
chat trees for 7 days and metrics without chat content for 365 days. A chat
tree is a root Pi session plus its nested child-agent runs.

The dashboard imports metadata, provider-reported usage, cost, and tool-call
counts with duplicate records removed. By default it writes
`~/.pi/agent/session-metrics/metrics.sqlite`; the same agent-directory
overrides move that database with the session root.

The database does not store prompts, responses, tool names, arguments, results,
or raw session JSON.

Opening the dashboard never deletes chats. `/spend-dashboard maintain` imports
metrics and previews cleanup. Actual transcript deletion requires every Pi
session to be closed and this explicit command from the setup repository:

```sh
node scripts/session-maintenance.mjs --apply
```

A root session and its child-run directory count as one cleanup unit. Cleanup
deletes the unit only when every file is older than the cutoff. It refuses to
continue if Pi is active or if a session is unreadable, malformed, truncated,
outside scan coverage, or becomes active during deletion. Metrics can outlive
their deleted chats until the 365-day metrics cutoff.

### Setup backups

`setup.sh` creates a timestamped backup only when it replaces or retires a
managed path. Restore one of those backups with:

```sh
./scripts/restore.sh <backup-dir>
```

With the default agent directory, each backup is under
`~/.pi/agent/backups`. If `PI_AGENT_DIR` is set, the backup goes under that
directory's `backups/` folder instead.

These are configuration backups, not machine backups. Sessions, provider
caches, dashboard metrics, credentials, trust decisions, browser state,
analytics, package installs, and generated data are excluded. `setup.sh` does
not copy or restore them.

## Source ownership and live paths

| Part | Source of truth | Live installation or data |
| --- | --- | --- |
| Global configuration | This repo plus ignored `settings.local.json` | Generated files under `~/.pi/agent` |
| Personal Pi package and extensions | This repo | Loaded from this checkout by the rendered owner settings, or from Pi's managed Git checkout for a public install |
| Shared Webflow skill | This repo | `~/.agents/skills/webflow-designer-agent-browser` |
| Prewalk | [`pi-prewalk`](https://github.com/javonmcgilberry/pi-prewalk), installed by Pi at the exact commit in `settings.json` | `~/.pi/agent/git/github.com/javonmcgilberry/pi-prewalk` |
| Context budget | This repo | Loaded as part of this Pi package |
| Context Mode | [`context-mode`](https://github.com/javonmcgilberry/context-mode), pinned in `settings.json` | Git checkout managed by Pi; edit `~/webdev/context-mode` |
| pi-subagents | [`nicobailon/pi-subagents`](https://github.com/nicobailon/pi-subagents) | The unchanged release from the upstream npm package |
| Pi core | `~/Developer/pi` ([my fork](https://github.com/javonmcgilberry/pi)) | Separate development checkout; the normal `pi` command uses the installed release |
| Warp gateway | Private `warp-pi-gateway` repository | Edit `~/webdev/warp-pi-gateway`; live extensions are links |
| Sessions | Pi runtime | `~/.pi/agent/sessions` by default; `PI_CODING_AGENT_SESSION_DIR` overrides it |
| Dashboard metrics | Session Spend Dashboard runtime | `~/.pi/agent/session-metrics/metrics.sqlite` by default; agent-directory overrides move it |

`config/manifest.json` is the authoritative list of global files and shared
links managed by bootstrap. Package resources are declared separately in
`package.json`. Update the manifest before changing bootstrap, drift,
validation, retirement, or restore behavior.
Never edit Pi-managed code under `~/.pi/agent/npm/node_modules` or
`~/.pi/agent/git`.

## Deliberately excluded

- `auth.json`, API keys, cookies, and trust decisions
- session transcripts, run history, caches, databases, logs, and intercom state
- browser profiles and downloaded binaries
- generated model lists and package-managed source checkouts
- `node_modules`, local development checkouts, and worktrees

The full exclusion list is in [`config/manifest.json`](config/manifest.json).

## Verify

```sh
./scripts/check.sh
./scripts/drift.sh
```

The check validates JSON, merges local settings, checks shell syntax and
dependency metadata, verifies the tracked-file boundary, and looks for common
secret patterns. It never reads or copies `auth.json`.
