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

Use the temporary-install workflow below to test without touching the live
setup. It isolates the Pi directory, shared skills, and session state together.

## Daily workflow

The main rule is: edit the owning checkout, never the generated live install.

For setup-package work, start Pi from this repository and check the repository
state first:

```sh
cd ~/Developer/my-pi-setup
git status --short --branch
pi
```

Edit:

- `extensions/` and `packages/context-budget/` for local extensions
- `settings.json` for tracked defaults and exact package pins
- `package.json` for this setup package
- `config/manifest.json` before changing bootstrap-managed files
- `README.md` when behavior, ownership, paths, or safety rules change

Validate the full setup/package boundary, not just the file you edited:

```sh
./scripts/check.sh
./scripts/drift.sh
npm pack --dry-run
```

`./scripts/check.sh --fast` skips `scripts/setup.test.mjs`, the setup matrix
that shells out to `setup.sh` repeatedly and accounts for most of the runtime.
The fast tier finishes in seconds and is what `/sync-me` runs before shutdown;
run the full checks before you call a change done. `drift.sh` is read-only.

Commit through `land.sh`, the single supported commit path:

```sh
./scripts/land.sh --message "feat: add a thing"
./scripts/land.sh --message "chore: bump pins" --path settings.json --push
```

It runs `check.sh` **before** staging anything, so the secret scan, the
forbidden-path scan, and the manifest inventory check cannot be skipped by a
commit. A hand-rolled `git commit` skips all of them. A clean tree makes the
script a no-op that exits 0, so it is always safe to run. `--full` swaps the
fast tier for the complete suite; `--push` publishes after a successful commit.

Code-only changes generally need a Pi restart to load.
Changes to rendered settings, copied configuration, or bootstrap inventory
require rerunning `setup.sh`. Git commits, pushes, tags, and package upgrades
are separate explicit operations.

### Testing without touching the live install

When any Pi session is active, use one temporary directory for the complete test
installation and start Pi with the same variables:

```sh
tmp="$(mktemp -d)"
export PI_AGENT_DIR="$tmp/agent"
export AGENTS_SKILLS_DIR="$tmp/skills"
export PI_CODING_AGENT_DIR="$PI_AGENT_DIR"

./setup.sh
./scripts/drift.sh
pi
```

This keeps temporary settings, package checkouts, sessions, and shared skill
links out of the live setup. Remove the temporary directory after testing.

### Applying changes live

Close every Pi session first. From the setup repository, apply and verify the
current source state:

```sh
env -u PI_AGENT_DIR -u AGENTS_SKILLS_DIR -u PI_CODING_AGENT_DIR ./setup.sh
./scripts/drift.sh
```

Restart Pi afterward. `setup.sh` refuses to replace the live configuration while
Pi is running; it never changes Git state or upgrades packages. `./sync` is
retired. Setup application, validation, Git commits and pushes, and dependency
upgrades remain separate operations.

From an interactive Pi started in this repository, `/sync-me` automates that
same safe apply boundary. It first refuses to apply silently over uncommitted
work: it lists the dirty files and offers to land them through `land.sh`, since
applying a dirty tree puts source into your live setup that exists in no commit.
After confirmation, it fast-forwards clean local Git
package replacements, runs `check.sh --fast` and a package dry run, schedules a
detached helper, and shuts down the current Pi. The helper waits for every Pi
process to exit, runs the **full** `check.sh`, runs `setup.sh`, and verifies
`drift.sh`. Failing full checks abort the helper before `setup.sh` runs, so
nothing is applied. It does not pull the setup repository, force-close another
session, push, commit, or upgrade pinned packages. Dirty or divergent local
package checkouts stop the command rather than being overwritten.

While the command runs, a footer status line shows the current step and elapsed
seconds. Everything after shutdown goes to `~/.pi/agent/sync-me.log`
(`$PI_AGENT_DIR/sync-me.log` when that variable is set), rewritten each run:

```sh
tail -f ~/.pi/agent/sync-me.log
```

If another Pi session stays open, the helper waits for it and names the process
IDs it is waiting on in that log, so a long wait is visible rather than silent.
Start Pi normally to apply the live setup, or use the same temporary environment
variables above to apply only to a temporary test setup.

### Updating tracked pins

`pi update` and the extension manager write to the live
`~/.pi/agent/settings.json`, which `setup.sh` regenerates from the tracked
`settings.json` in this repository. Their updates are therefore lost at the next
apply. Tracked `settings.json` is the only source of truth for versions.

`/sync-me update` refreshes that tracked file instead. It first works out what
should move:

1. For each local Git package replacement, it readies the checkout so its HEAD
   can be pinned. A clean checkout is pushed; a dirty one prompts for a commit
   message and needs explicit confirmation of the commit and push. Empty message
   or declined confirmation leaves the checkout untouched and skips that pin.
2. It asks the npm registry for the current release of every `npm:` pin. A
   failed lookup offers no update rather than failing the command.
3. It shows every proposed change and writes them to tracked `settings.json`
   only after you confirm.

It then walks the rest of the work without leaving Pi, one gate at a time.
Continuing from the steps above:

1. It shows the resulting `settings.json` diff and asks whether to run
   `check.sh --fast`.
2. It offers a commit, pre-filled with a message naming every pin that moved.
   The commit runs through `land.sh --path settings.json`, so validation runs
   before staging and nothing but `settings.json` is committed.
3. It offers to apply, which runs the same shutdown-and-apply path as plain
   `/sync-me`.

Declining any gate stops the chain and leaves the edited `settings.json` in
place, so you can always finish by hand:

```sh
git diff settings.json
./scripts/check.sh
git commit -m "chore: update tracked pins" -- settings.json
```

It never writes live settings, never pushes this repository, and never commits
anything but `settings.json`. A Git pin only ever moves to a commit that is
already on a remote branch, so a pin can never point at unpushed local work.

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

### Prewalk development and installation

Prewalk is a separate package with its own owning checkout. There are two
sources, and the local replacement wins when it is present:

1. **Your development install:** ignored `settings.local.json` points Pi at the
   owning local `pi-prewalk` checkout. Edit that checkout and restart Pi to load
   source-only changes.
2. **A clean or public install:** tracked `settings.json` points Pi at this
   exact remote commit:

```text
git:github.com/javonmcgilberry/pi-prewalk@ea1d8df39249502b3ca68ea89316d9533b8861e4
```

If the local replacement is present, Pi does **not** use the managed Git
checkout. If it is absent, Pi installs the pinned commit into
`~/.pi/agent/git/github.com/javonmcgilberry/pi-prewalk`. That checkout is
generated package state; do not edit it.

The local replacement looks like this:

```json
{
  "packageReplacements": {
    "git:github.com/javonmcgilberry/pi-prewalk":
      "/absolute/path/to/pi-prewalk"
  }
}
```

The unpinned locator is intentional: the local override remains valid when the
tracked remote SHA changes.

For source-only edits in the local checkout, restart Pi. To bring a clean local
checkout up to date with GitHub and apply the setup, use `/sync-me`; it performs
the fast-forward pull for you. It stops instead of pulling when the checkout
has uncommitted or divergent changes. You do **not** update the tracked SHA for
every local edit. Only update that SHA when publishing a new default remote
version, after the commit has been pushed. `check.sh` fetches every tracked Git
pin from its remote, so a local-only commit is not a valid default pin.

`/sync-me update` performs that publish step: it pushes the checkout (prompting
for a commit message first when the checkout is dirty) and then rewrites the
tracked SHA to the pushed HEAD. Hand-editing the SHA is no longer necessary.

## Core Pi settings

The main defaults live in [`settings.json`](settings.json):

- This setup targets Pi `0.84.0`. The regular TUI remains the default.
  Fullscreen mode is optional, and interactive transcripts can render Mermaid
  diagrams and LaTeX.
- OpenAI Codex is the default provider and `gpt-5.6-luna` is the default model.
- `openai-codex/gpt-5.6-luna` is the only model in the model-selection list.
- The default thinking level is `max`.
- Auto-compaction is enabled with 32,768 tokens reserved for the response and
  a 20,000-token recent-history target.
- Automatic retry is enabled.
- Subagent workers inherit the parent context; reviewers start fresh. The
  default child model is Luna with max reasoning.
- Cache-miss notices are visible.

### Browser policy and authentication

[`agent-browser-policy.json`](agent-browser-policy.json) is the tracked,
fail-closed policy for sensitive `agent_browser` features. Ordinary browser
commands can run from any active Pi model and reasoning level. The policy
disables nested upstream `agent-browser chat` and keeps cookie transfer
disabled. The companion
[`extensions/agent-browser-policy.ts`](extensions/agent-browser-policy.ts)
enforces only those nested-chat and cookie-transfer safeguards.
`/agent-browser-policy` shows the effective safeguards without displaying secrets.

Cookie transfer is a separate, explicit opt-in. Create a private policy file
outside the repository with `cookieTransfer.enabled: true` and exact
`allowedDomains`, then pass it with `--policy` or set
`PI_AGENT_BROWSER_POLICY_CONFIG` to that file. With the dedicated runtime
already ready, inspect first:

```json
{
  "version": 1,
  "upstreamChat": { "enabled": false, "allowedModels": [] },
  "cookieTransfer": {
    "enabled": true,
    "allowedDomains": ["webflow.com", "wfdev.io"]
  }
}
```

```sh
python3 skills/webflow-designer-agent-browser/scripts/browser-runtime.py \
  transfer-cookies --policy /private/path/policy.json \
  --confirm-cookie-transfer --dry-run
```

Only after reviewing the count should the same command run without
`--dry-run`. It snapshots only the normal Chrome Cookies database and SQLite
sidecars, derives the macOS Chrome key through Keychain, decrypts matching
unexpired cookies in memory, and injects them through loopback CDP. It never
copies or launches the normal Chrome profile, writes plaintext cookie files,
logs cookie values, or accepts wildcard domains. Manual headed login remains
the default recovery path.

`pi-agent-browser-native` requires Pi `0.84.0` or newer. It turns off periodic
restore autosave for headed sessions started by the wrapper because autosave can
flash temporary tabs and delay daemon checks. The browser tool's `close` command
still saves state. Closing the window by hand can lose newer state. Set
`AGENT_BROWSER_AUTOSAVE_INTERVAL_MS` before a fresh launch when periodic saves
matter.

Pi Codex Conversion has its own tracked config in
[`pi-codex-conversion.json`](pi-codex-conversion.json). It uses path mode,
compact tool rendering, Code Mode, fast OpenAI requests, cached WebSockets, and
low response verbosity. Native Responses API compaction is disabled, so normal
Pi compaction handles the conversation. Realtime voice seeds its startup context
from the selected session model and reasoning level. It shows the summary in a
display-only Voice Context entry and rebuilds it after an explicit voice
restart. Voice sessions survive a device handoff.

The local [`context-budget`](packages/context-budget) package keeps the first
request smaller without uninstalling anything. Pi still discovers every skill,
but the model sees a short `skills_catalog` instruction instead of the full
skill list. It can search the catalog and read one skill when needed. Browser,
intercom, MCP, and subagent tools also start inactive; the model can load their
tool group with `activate_capability`. Normal file, shell, web, and diagnostic
tools stay active. When global and project `AGENTS.md` files contain the same
text, only the project copy is sent. Setup loads this package after its
dependencies so these prompt and tool changes run last.

## Installed packages and extensions

The `packages` array in `settings.json` lists the packages Pi loads.
Those npm and Git sources are pinned there for clean, reproducible installs.
Ignored `packageReplacements` can substitute a local checkout during
development. The root `package.json` describes this repository's own Pi
package, and `package-lock.json` covers only dependencies needed by that
package itself.

| Component | What it does | Configuration and source |
| --- | --- | --- |
| [`pi-mcp-adapter`](https://github.com/nicobailon/pi-mcp-adapter) | Connects Pi to MCP servers and exposes their tools. | Servers are defined in [`mcp.json`](mcp.json). The linked repository owns the package README. |
| [`pi-web-access`](https://github.com/nicobailon/pi-web-access) | Adds web search, URL fetching, repository/PDF extraction, and video analysis. | Provider credentials and runtime choices stay local. The linked repository owns the package README. |
| `context-mode` | Keeps large reads, command output, logs, and web payloads out of model context; indexes compact session memory for later search. | Loaded from a pinned commit of [my Context Mode fork](https://github.com/javonmcgilberry/context-mode) and registered through `mcp.json`. Edit the source checkout, not Pi's copy. |
| [`pi-subagents`](https://github.com/nicobailon/pi-subagents) | Runs delegated agents and script-based workflows, including parallel work and managed Git worktrees. | Child model and role defaults are in `settings.json`. Multi-agent workflows use `workflowScript`; the old top-level task/chain arrays and `/chain`, `/parallel`, and `/run-chain` commands are gone. Scheduled workflows are enabled by the package default. Uses the unchanged upstream package and its README. |
| [`pi-intercom`](https://www.npmjs.com/package/pi-intercom) | Sends direct messages between local Pi sessions and supports parent/child coordination. | No tracked config. Its installed README is the reference; runtime broker state is local. |
| [`pi-anthropic-oauth`](https://github.com/leohenon/pi-anthropic-oauth) | Adds Claude Pro/Max browser OAuth and token refresh. | OAuth credentials stay in Pi's local auth store. The linked repository owns the package README. |
| [`pi-cursor-sdk`](https://github.com/fitchmultz/pi-cursor-sdk) | Adds models backed by Cursor's local and cloud agent libraries. | Requires Pi `0.84.0` or newer and uses Cursor SDK `1.0.23`. Authorization and generated model data stay local. The linked repository owns the package README. |
| [`@howaboua/pi-codex-conversion`](https://github.com/IgorWarzocha/howaboua-pi-stuff/tree/main/packages/pi-codex-conversion) | Adapts Pi prompts, tools, communication, and status for Codex models. | [`pi-codex-conversion.json`](pi-codex-conversion.json). The linked package README has the full command and option reference. |
| [`@howaboua/pi-auto-trees`](https://github.com/IgorWarzocha/howaboua-pi-stuff/tree/main/packages/pi-auto-trees) | Adds marker/end commands and automatic summaries for long-running incremental sessions. | [`pi-auto-trees.json`](pi-auto-trees.json) uses Luna with low reasoning for summaries. The linked package README has the command reference. |
| [`@howaboua/pi-smart-btw`](https://github.com/IgorWarzocha/howaboua-pi-stuff/tree/main/packages/pi-smart-btw) | Runs side questions in ephemeral child Pi processes and injects answers only when requested. | [`pi-smart-btw.json`](pi-smart-btw.json) selects Luna, low reasoning, and the `Alt+Z/C/X/J/K/H/L` controls. The linked package README explains its slots and queues. |
| [`pi-lens`](https://github.com/apmantza/pi-lens) | Runs live Language Server Protocol (LSP), lint, formatting, type, security, and structural checks around edits. | Package defaults plus Pi's generated diagnostic state. The linked repository owns the package README and rule documentation. |
| [`pi-agent-browser-native`](https://github.com/fitchmultz/pi-agent-browser-native) | Exposes `agent-browser` as Pi's native browser automation tool. | Uses the global `agent-browser` CLI and local browser state. [`agent-browser-policy.json`](agent-browser-policy.json) and the policy extension keep nested chat and cookie transfer fail-closed without restricting the active Pi model. The linked repository owns the package README. |
| [`pi-autoname`](https://github.com/ssdiwu/pi-autoname) | Gives a new session a short name, then checks periodically whether the topic has changed enough to rename it. | Pinned at `0.6.8`. [`pi-autoname.json`](pi-autoname.json) uses Luna, waits 10 minutes between checks, and preserves names set with `/name`. |
| Compound Engineering | Provides planning, implementation, review, debugging, shipping, and learning skills. | Loaded from [EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin). The package owns its skill documentation. |
| [`pi-ask-user`](https://github.com/edlsh/pi-ask-user) | Adds the interactive `ask_user` decision UI with search, choices, and freeform input. | No tracked config. The linked repository owns the package README. |
| Prewalk | The chosen planner starts a coding task; later turns go to a configured executor in the same session. | Uses the owning local checkout when `settings.local.json` provides a replacement; clean installs use the exact [`pi-prewalk`](https://github.com/javonmcgilberry/pi-prewalk) commit in `settings.json`. [`prewalk.json`](prewalk.json) selects Luna at max reasoning and enables local analytics. |
| Context budget | Keeps the full skill catalog and the largest optional tool schemas out of the first request, then loads them when needed. | [`packages/context-budget`](packages/context-budget), loaded as part of this Pi package. Deferred groups are browser, intercom, MCP, and subagents. |
| [`@vanillagreen/pi-tool-renderer`](https://github.com/vanillagreencom/vstack/tree/main/pi-extensions/pi-tool-renderer) | Replaces noisy tool output with compact, readable renderers. | Renderer modes are under `vstack.extensionManager.config` in `settings.json`. The linked package README has the renderer options. |
| [`pi-render-cache`](https://github.com/axelbaumlisto/pi-render-cache) | Reduces terminal-interface (TUI) streaming work with bounded render caches. | Loaded at version `1.1.0`; no tracked config. On Pi `0.84.0`, the text-segmentation cache loads but the Markdown cache rejects the new renderer hash and stays off, so normal uncached Markdown rendering continues with a startup warning. This is a performance cache, not a conversation backup. The linked repository owns the package README. |
| [`@vanillagreen/pi-extension-manager`](https://github.com/vanillagreencom/vstack/tree/main/pi-extensions/pi-extension-manager) | Adds package browsing, update/uninstall actions, diagnostics, and settings editing based on package schemas. | Reads Pi package state and the `vstack` settings namespace. This repository still owns the exact pins. The manager runs npm updates directly, so stale peer ranges can stop its update action even when Pi's managed installer can reconcile the same pins. The linked package README has the command and settings reference. |
| [`@kliebhan/pi-prompt-autocomplete`](https://github.com/KLIEBHAN/pi-extensions/tree/main/extensions/prompt-autocomplete) | Provides privacy-conscious inline AI completion while typing prompts. | If a requested model is missing or unauthenticated, autocomplete stays off instead of sending the draft to another provider. Provider text and diagnostics are cleaned before terminal display. No tracked config; the linked package README explains the bounded context sent with each request and the in-memory cache. |
| [`@davecodes/pi-skill-tags`](https://github.com/Davidcreador/pi-skill-tags) | Adds inline skill tags and skill-name autocomplete. | No tracked config. The linked repository owns the package README. |
| [`pi-fzf`](https://github.com/kaofelix/pi-fzf) | Adds configurable fuzzy-search commands. | [`fzf.json`](fzf.json) defines an `@` file picker, preview command, overlay placement, and scroll keys. The linked repository owns the package README. |
| [`@juicesharp/rpiv-warp`](https://github.com/juicesharp/rpiv-mono/tree/main/packages/rpiv-warp) | Sends Pi lifecycle notifications to Warp through OSC 777. | It does nothing outside Warp. The linked package README explains terminal requirements. The separate private Warp gateway links are described below. |

### Extensions maintained here

| Component | What it does | Configuration and source |
| --- | --- | --- |
| Pretty footer | Replaces the footer with model, context, usage, cache, cost, task, and extension status. | [`extensions/pretty-footer.ts`](extensions/pretty-footer.ts), loaded from this Pi package. |
| Herdr agent state | Reports Pi session identity and working, blocked, or idle state to Herdr over its local socket. It does nothing unless `HERDR_ENV=1`, `HERDR_SOCKET_PATH`, and `HERDR_PANE_ID` are all set. | [`extensions/herdr-agent-state.ts`](extensions/herdr-agent-state.ts), loaded from this Pi package. Herdr owns the generated integration format. |
| Agent Browser Policy | Keeps model-assisted browser usage on the configured Pi model and gates nested chat and cookie transfer. | [`agent-browser-policy.json`](agent-browser-policy.json), [`extensions/agent-browser-policy.ts`](extensions/agent-browser-policy.ts), and the shared Webflow skill. Cookie transfer is off by default. |
| Session Spend Dashboard | Runs an opt-in read-only localhost dashboard for provider-reported spend, token use, projects, sessions, and subagent activity. | [`extensions/session-spend-dashboard`](extensions/session-spend-dashboard), configured by [`session-spend-dashboard.json`](session-spend-dashboard.json). See its [README](extensions/session-spend-dashboard/README.md). |
| `/sync-me` | Updates clean local package checkouts, runs the fast checks, and schedules a safe setup apply after Pi sessions close. | [`extensions/setup-sync.js`](extensions/setup-sync.js). The full checks run in the detached helper; progress appears in the footer and in `~/.pi/agent/sync-me.log`. It does not pull this setup repository or change its Git state. |
| `/sync-me update` | Rewrites the tracked pins in `settings.json` to current npm releases and pushed local-checkout commits, then walks review, checks, commit, and apply in-session. | [`extensions/setup-sync.js`](extensions/setup-sync.js) with pin planning in [`extensions/setup-update.js`](extensions/setup-update.js). Every step is a separate confirmation; it never writes live settings, never pushes, and commits `settings.json` only. |
| Warp session title | Shows the current Pi session name and project in the active Warp tab. It does nothing in other terminals. | [`extensions/warp-session-title.ts`](extensions/warp-session-title.ts), loaded from this Pi package. |
| Clear status | Older compact usage/status implementation retained for reference but not loaded or packaged. | [`disabled-extensions/clear-status.ts`](disabled-extensions/clear-status.ts). |
| Warp gateway links | Private Warp gateway and fallback extensions maintained in a separate repository. | Live links are `extensions/warp-gateway.ts` and `extensions/warp-link-fallback.ts`; edit `~/webdev/warp-pi-gateway`. |

`REALTIME-SYSTEM-PROMPT.md` is tracked prompt configuration, not an extension.
It changes the realtime conversational mode used by Pi Codex Conversion.

### Managed setup files

The tables above explain the components. This table lists the files that setup
renders or copies into the live agent directory, plus the macOS host file it
installs only for a live default setup.

| File | Role |
| --- | --- |
| `settings.json` | Rendered from tracked defaults plus `settings.local.json`; controls models, packages, compaction, retry, subagents, and shared package settings. |
| `AGENTS.md` | Gives agents the source-ownership, validation, documentation, and publication rules for this setup. |
| `REALTIME-SYSTEM-PROMPT.md` | Supplies Pi Codex Conversion's realtime conversational prompt. |
| `agent-browser-policy.json` | Fail-closed model, nested-chat, and cookie-transfer defaults for the native browser extension. |
| `mcp.json` | Registers the MCP servers listed below. |
| `pi-codex-conversion.json` | Configures the Codex prompt/tool adapter, UI, Code Mode, transport, and native compaction choice. |
| `pi-autoname.json` | Selects the model and cooldown for automatic session names and keeps manual names unchanged. |
| `pi-auto-trees.json` | Configures automatic tree summaries. |
| `pi-smart-btw.json` | Configures side-question models and keyboard controls. |
| `prewalk.json` | Configures the Prewalk executor and analytics. |
| `fzf.json` | Configures fuzzy-search commands and presentation. |
| `session-spend-dashboard.json` | Configures chat and metrics retention windows. |
| `config/com.javonmcgilberry.pi-tmux-gui-server.plist` | Installs to `~/Library/LaunchAgents` on macOS so Moshi attaches to a GUI-owned default tmux server with Keychain access. |

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

### MCP OAuth from Moshi and tmux on macOS

Linear and Buildkite OAuth credentials live in macOS Keychain. A tmux server
created by Moshi's remote SSH or Mosh login inherits that remote security
session, even after tmux is reparented to `launchd`. macOS then rejects Keychain
writes with `User interaction is not allowed`, so `/mcp-auth` fails before it
can open the browser. Repeatedly typing a Mac password inside tmux is neither
necessary nor the fix.

The managed LaunchAgent at
[`config/com.javonmcgilberry.pi-tmux-gui-server.plist`](config/com.javonmcgilberry.pi-tmux-gui-server.plist)
starts the normal default tmux server in the macOS GUI login session and keeps
that empty server alive. Moshi still uses its normal default socket. `moshi .`
still creates or attaches to the session for the requested directory; the
LaunchAgent does not create, rename, select, or attach to a Moshi session. It
only makes the server process, and every pane created later, belong to the GUI
login session that can use Keychain.

A live default `setup.sh` install copies the plist to
`~/Library/LaunchAgents`. Temporary installs using `PI_AGENT_DIR` and
`AGENTS_SKILLS_DIR` do not touch that directory. Setup also handles activation:

- From a local Mac Terminal or Warp tab, with no sessions on the default tmux
  server, `setup.sh` activates the LaunchAgent immediately.
- From Moshi, SSH, Mosh, tmux, or while tmux sessions still exist, setup installs
  the plist and safely defers activation. The next macOS login starts it
  automatically before the first `moshi .` call.

There is no separate command to remember during the normal setup workflow. The
usual live setup command is enough:

```sh
cd ~/Developer/my-pi-setup
env -u PI_AGENT_DIR -u AGENTS_SKILLS_DIR -u PI_CODING_AGENT_DIR ./setup.sh
```

[`scripts/activate-macos-tmux-gui-server.sh`](scripts/activate-macos-tmux-gui-server.sh)
remains available for troubleshooting or a manual retry, but setup calls it
automatically. The helper never kills active Moshi or tmux sessions. After
activation, start `moshi .` normally and run `/mcp-auth linear` or
`/mcp-auth buildkite`. A future Moshi configuration that uses a custom tmux
socket (`-L`, `-S`, or a different `TMUX_TMPDIR`) would need a matching
LaunchAgent; the current Moshi installation uses the default socket.

## Shared Webflow browser skill

The tracked
[`skills/webflow-designer-agent-browser`](skills/webflow-designer-agent-browser)
directory is linked once into `~/.agents/skills`, and Pi and other compatible
agent tools share that installation. It is deliberately not duplicated under
`~/.pi/agent/skills`, which would cause a skill-name collision.

Before local or authenticated Designer QA, the skill uses two subagents in
sequence. The first runs on the active default model at the highest available
reasoning level. It reuses or starts the documented HUD and Designer services,
checks the exact target in managed Chrome for Testing, and releases the browser.
Only then can the browser executor run the feature tests. The handoff is valid
when `scripts/readiness-gate.py` prints `"qaLaunchAllowed": true`. This keeps
service startup, stale tabs, expired logins, and stale browser leases out of the
actual QA run.

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

Older unnamed sessions can be backfilled with
[`scripts/session-metadata-backfill.mjs`](scripts/session-metadata-backfill.mjs).
Its `prepare` step extracts bounded user and assistant text, removes tool
payloads, redacts common secret patterns, and skips active or temporary
sessions. Luna agents produce a short title and summary from those private
extracts. The `apply` step refuses files that changed after preparation,
appends the title as normal Pi session metadata, and records an autoname marker
so the title remains stable. Summaries stay in private metadata files under
`~/.pi/agent/session-metadata/summaries/`; setup does not copy them, and the
spend metrics database does not store them.

In Warp, [`extensions/warp-session-title.ts`](extensions/warp-session-title.ts)
sets the tab title to `π - <session name> - <project>` whenever Pi starts or
resumes a session and whenever its name changes. It sets the saved title again
after startup and after Pi finishes working, so a reopened tab does not keep
Warp's command title. It uses Pi's terminal-title API, which sends the OSC 0
sequence supported by Warp. While the installed `rpiv-warp` activity spinner is
running, the local extension keeps the session name in each animated title and
restores the saved title when Pi stops working. If Warp's shell integration
later replaces the title, start Pi with
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
directory's `backups/` folder instead. Replaced managed LaunchAgent files use
the same backup and restore flow. Restore does not reload a running launchd job
or restart tmux; a restored plist takes effect at the next macOS login.

These are configuration backups, not machine backups. Sessions, provider
caches, dashboard metrics, credentials, trust decisions, browser state,
analytics, private session summaries, package installs, and generated data are
excluded. `setup.sh` does not copy or restore them.

## Source ownership and live paths

| Part | Source of truth | Live installation or data |
| --- | --- | --- |
| Global configuration | This repo plus ignored `settings.local.json` | Generated files under `~/.pi/agent` |
| Personal Pi package and extensions | This repo | Loaded from this checkout by the rendered owner settings, or from Pi's managed Git checkout for a public install |
| Shared Webflow skill | This repo | `~/.agents/skills/webflow-designer-agent-browser` |
| Prewalk | Owning `pi-prewalk` checkout for development; exact remote commit in `settings.json` for clean installs | Local replacement when configured; otherwise `~/.pi/agent/git/github.com/javonmcgilberry/pi-prewalk` |
| Context budget | This repo | Loaded as part of this Pi package |
| Context Mode | [`context-mode`](https://github.com/javonmcgilberry/context-mode), pinned in `settings.json` | Git checkout managed by Pi; edit `~/webdev/context-mode` |
| pi-subagents | [`nicobailon/pi-subagents`](https://github.com/nicobailon/pi-subagents) | The unchanged release from the upstream npm package |
| Pi core | `~/Developer/pi` ([my fork](https://github.com/javonmcgilberry/pi)) | Separate development checkout; the normal `pi` command uses the installed release |
| Warp gateway | Private `warp-pi-gateway` repository | Edit `~/webdev/warp-pi-gateway`; live extensions are links |
| macOS tmux LaunchAgent | `config/com.javonmcgilberry.pi-tmux-gui-server.plist` | `~/Library/LaunchAgents/com.javonmcgilberry.pi-tmux-gui-server.plist` on a live default macOS install |
| Sessions | Pi runtime | `~/.pi/agent/sessions` by default; `PI_CODING_AGENT_SESSION_DIR` overrides it |
| Dashboard metrics | Session Spend Dashboard runtime | `~/.pi/agent/session-metrics/metrics.sqlite` by default; agent-directory overrides move it |

`config/manifest.json` is the authoritative list of global files, shared
links, and macOS LaunchAgents managed by bootstrap. Package resources are declared separately in
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
npm pack --dry-run
```

The check validates JSON, tests the tracked local-settings example, checks shell syntax and
dependency metadata, fetches every exact Git package ref in a temporary
directory, verifies the tracked-file boundary, and looks for common secret
patterns. The remote check catches a pin that exists only in an unpublished
local checkout. It never reads or copies `auth.json`.

Add `--fast` to skip the setup matrix (`scripts/setup.test.mjs`) when you want a
quick gate; run it without `--fast` before calling a change done.
