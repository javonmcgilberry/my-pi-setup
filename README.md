# My Pi setup

This repository is the portable, maintained source for my
[Pi](https://github.com/earendil-works/pi) setup. It records the configuration,
extensions, skills, and package sources I want to keep. Credentials, chats,
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
- `settings.json` for tracked defaults and floating package locators
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
The fast tier finishes in seconds; run the full checks before you call a change
done. `drift.sh` is read-only.

Commit through `land.sh`, the single supported commit path:

```sh
./scripts/land.sh --message "feat: add a thing"
./scripts/land.sh --message "chore: update setup" --push
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

Close every Pi session, then run one command from any directory:

```sh
pi-update-all
```

If you changed this setup repository, pass the commit message in the same
command:

```sh
pi-update-all "describe the change"
```

With a dirty setup repository, the message is required. The command runs the
full checks, commits and pushes the setup, applies it, updates extensions, and
verifies drift. With a clean repository, it skips the commit and performs the
apply and update. It refuses to run while Pi is open, so it never replaces code
that a session has already loaded.

### Updating extensions

Exit Pi before replacing extensions it has already loaded, then run:

```sh
pi-update-all
```

Every routine package entry in `settings.json` is a stable, unversioned locator.
The command applies those locators, invokes Pi's native
`pi update --extensions` updater, and verifies the live setup. npm packages move
to their current registry releases and Git packages move to their remote default
branches. Restart Pi afterward.

Prewalk follows the same update rule. Your explicit local replacement wins on
this machine; clean installs follow the current remote default branch. To share
Prewalk work, commit and push its own repository. No setup edit is required.

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
from the tracked defaults. An explicit `packageReplacements` entry always wins
over the tracked remote locator. Pi does not guess based on nearby checkout
names, because a stale or retired clone must not silently replace the intended
package. Add a replacement only for a checkout you are actively developing.

### Prewalk development and installation

Prewalk is a separate package with its own owning checkout. There are two
sources, and the local replacement wins when it is present:

1. **Your development install:** ignored `settings.local.json` points Pi at the
   owning local `pi-prewalk` checkout. Edit that checkout and restart Pi to load
   source-only changes.
2. **A clean or public install:** tracked `settings.json` points Pi at the
   floating remote package:

```text
git:github.com/javonmcgilberry/pi-prewalk
```

If the local replacement is present, Pi does **not** use the managed Git
checkout. If it is absent, Pi installs and updates the remote default branch in
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

For source-only edits in the local checkout, restart Pi. To share those changes,
commit and push the Prewalk repository. The setup repository needs no matching
version change.

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
enforces the nested-chat and policy opt-in safeguards; the runtime helper also
requires the dedicated consumer lease before a live cookie injection.
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
`--dry-run`, while an `agent_browser` consumer lease is held. For the direct
helper, run `claim --consumer agent_browser` first and pass its returned
`leaseId` to the live transfer and matching
`release --consumer agent_browser --lease-id ...`.
It snapshots only the normal Chrome Cookies database and SQLite
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
All remote package sources float. Ignored
`packageReplacements` can substitute an explicitly chosen local checkout during
development. The root `package.json` describes this repository's own Pi package,
and `package-lock.json` covers only dependencies needed by that package itself.

Context Mode now follows upstream's published npm releases. The previous nested
Code Mode trace patch remains parked in the `javonmcgilberry/context-mode` fork
at commit `19b8f73`, but this setup does not load it. Prewalk has its own Code
Mode mutation tracking and does not depend on that patch.

| Component | What it does | Configuration and source |
| --- | --- | --- |
| [`pi-mcp-adapter`](https://github.com/nicobailon/pi-mcp-adapter) | Connects Pi to MCP servers and exposes their tools. | Servers are defined in [`mcp.json`](mcp.json). The linked repository owns the package README. |
| [`pi-web-access`](https://github.com/nicobailon/pi-web-access) | Adds web search, URL fetching, repository/PDF extraction, and video analysis. | Provider credentials and runtime choices stay local. The linked repository owns the package README. |
| [`context-mode`](https://www.npmjs.com/package/context-mode) | Keeps large reads, command output, logs, and web payloads out of model context; indexes compact session memory for later search. | Follows upstream npm releases and is registered through `mcp.json`. Pi owns the installed package. |
| [`pi-subagents`](https://github.com/nicobailon/pi-subagents) | Runs delegated agents and script-based workflows, including parallel work and managed Git worktrees. | Child model and role defaults are in `settings.json`. Multi-agent workflows use `workflowScript`; the old top-level task/chain arrays and `/chain`, `/parallel`, and `/run-chain` commands are gone. Scheduled workflows are enabled by the package default. Uses the unchanged, floating upstream package. |
| [`pi-intercom`](https://www.npmjs.com/package/pi-intercom) | Sends direct messages between local Pi sessions and supports parent/child coordination. | No tracked config. Its installed README is the reference; runtime broker state is local. |
| [`pi-anthropic-oauth`](https://github.com/leohenon/pi-anthropic-oauth) | Adds Claude Pro/Max browser OAuth and token refresh. | OAuth credentials stay in Pi's local auth store. The linked repository owns the package README. |
| [`pi-cursor-sdk`](https://github.com/fitchmultz/pi-cursor-sdk) | Adds models backed by Cursor's local and cloud agent libraries. | Requires Pi `0.84.0` or newer and uses Cursor SDK `1.0.23`. Authorization and generated model data stay local. The linked repository owns the package README. |
| [`@howaboua/pi-codex-conversion`](https://github.com/IgorWarzocha/howaboua-pi-stuff/tree/main/packages/pi-codex-conversion) | Adapts Pi prompts, tools, communication, and status for Codex models. | [`pi-codex-conversion.json`](pi-codex-conversion.json). The linked package README has the full command and option reference. |
| [`@howaboua/pi-auto-trees`](https://github.com/IgorWarzocha/howaboua-pi-stuff/tree/main/packages/pi-auto-trees) | Adds marker/end commands and automatic summaries for long-running incremental sessions. | [`pi-auto-trees.json`](pi-auto-trees.json) uses Luna with low reasoning for summaries. The linked package README has the command reference. |
| [`@howaboua/pi-smart-btw`](https://github.com/IgorWarzocha/howaboua-pi-stuff/tree/main/packages/pi-smart-btw) | Runs side questions in ephemeral child Pi processes and injects answers only when requested. | [`pi-smart-btw.json`](pi-smart-btw.json) selects Luna, low reasoning, and the `Alt+Z/C/X/J/K/H/L` controls. The linked package README explains its slots and queues. |
| [`pi-lens`](https://github.com/apmantza/pi-lens) | Runs live Language Server Protocol (LSP), lint, formatting, type, security, and structural checks around edits. | Package defaults plus Pi's generated diagnostic state. The linked repository owns the package README and rule documentation. |
| [`pi-agent-browser-native`](https://github.com/fitchmultz/pi-agent-browser-native) | Exposes `agent-browser` as Pi's native browser automation tool. | Uses the global `agent-browser` CLI and local browser state. [`agent-browser-policy.json`](agent-browser-policy.json) and the policy extension keep nested chat and cookie transfer fail-closed without restricting the active Pi model. The linked repository owns the package README. |
| [`pi-autoname`](https://github.com/ssdiwu/pi-autoname) | Gives a new session a short name, then checks periodically whether the topic has changed enough to rename it. | [`pi-autoname.json`](pi-autoname.json) uses Luna, waits 10 minutes between checks, and preserves names set with `/name`. |
| Compound Engineering | Provides planning, implementation, review, debugging, shipping, and learning skills. | Follows the default branch of [EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin). The package owns its skill documentation. |
| [`pi-ask-user`](https://github.com/edlsh/pi-ask-user) | Adds the interactive `ask_user` decision UI with search, choices, and freeform input. | No tracked config. The linked repository owns the package README. |
| Prewalk | The chosen planner starts a coding task; later turns go to a configured executor in the same session. | Uses the owning local checkout when `settings.local.json` provides a replacement; clean installs follow the default branch of [`pi-prewalk`](https://github.com/javonmcgilberry/pi-prewalk). [`prewalk.json`](prewalk.json) selects Luna at max reasoning and enables local analytics. |
| Context budget | Keeps the full skill catalog and the largest optional tool schemas out of the first request, then loads them when needed. | [`packages/context-budget`](packages/context-budget), loaded as part of this Pi package. Deferred groups are browser, intercom, MCP, and subagents. |
| [`@vanillagreen/pi-tool-renderer`](https://github.com/vanillagreencom/vstack/tree/main/pi-extensions/pi-tool-renderer) | Replaces noisy tool output with compact, readable renderers. | Renderer modes are under `vstack.extensionManager.config` in `settings.json`. The linked package README has the renderer options. |
| [`pi-render-cache`](https://github.com/axelbaumlisto/pi-render-cache) | Reduces terminal-interface (TUI) streaming work with bounded render caches. | No tracked config. If a release does not recognize Pi's current renderer hash, it disables that cache and leaves normal uncached rendering available. This is a performance cache, not a conversation backup. The linked repository owns the package README. |
| [`@vanillagreen/pi-extension-manager`](https://github.com/vanillagreencom/vstack/tree/main/pi-extensions/pi-extension-manager) | Adds package browsing, update/uninstall actions, diagnostics, and settings editing based on package schemas. | Reads Pi package state and the `vstack` settings namespace. Routine package entries float, and `pi update --extensions` is the shell updater. The linked package README has the command and settings reference. |
| [`pi-model-control`](https://www.npmjs.com/package/pi-model-control) | Adds model-variant and thinking-level commands. | No tracked config. Pi manages the floating npm package. |
| [`@kliebhan/pi-prompt-autocomplete`](https://github.com/KLIEBHAN/pi-extensions/tree/main/extensions/prompt-autocomplete) | Provides privacy-conscious inline AI completion while typing prompts. | If a requested model is missing or unauthenticated, autocomplete stays off instead of sending the draft to another provider. Provider text and diagnostics are cleaned before terminal display. No tracked config; the linked package README explains the bounded context sent with each request and the in-memory cache. |
| [`@davecodes/pi-skill-tags`](https://github.com/Davidcreador/pi-skill-tags) | Adds inline skill tags and skill-name autocomplete. | No tracked config. The linked repository owns the package README. |
| [`pi-fzf`](https://github.com/kaofelix/pi-fzf) | Adds configurable fuzzy-search commands. | [`fzf.json`](fzf.json) defines an `@` file picker, preview command, overlay placement, and scroll keys. The linked repository owns the package README. |
| [`@juicesharp/rpiv-warp`](https://github.com/juicesharp/rpiv-mono/tree/main/packages/rpiv-warp) | Sends Pi lifecycle notifications to Warp through OSC 777. | It does nothing outside Warp. The linked package README explains terminal requirements. The separate private Warp gateway links are described below. |

### Extensions maintained here

| Component | What it does | Configuration and source |
| --- | --- | --- |
| Pretty footer | Shows session cost, context use, token totals, prompt-cache totals, model reasoning, the Prewalk route, and extension status with clear labels. | [`extensions/pretty-footer.ts`](extensions/pretty-footer.ts) and [`extensions/pretty-footer-view.ts`](extensions/pretty-footer-view.ts), loaded from this Pi package. |
| Herdr agent state | Reports Pi session identity and working, blocked, or idle state to Herdr over its local socket. It does nothing unless `HERDR_ENV=1`, `HERDR_SOCKET_PATH`, and `HERDR_PANE_ID` are all set. | [`extensions/herdr-agent-state.ts`](extensions/herdr-agent-state.ts), loaded from this Pi package. Herdr owns the generated integration format. |
| Agent Browser Policy | Keeps model-assisted browser usage on the configured Pi model and gates nested chat and cookie transfer. | [`agent-browser-policy.json`](agent-browser-policy.json), [`extensions/agent-browser-policy.ts`](extensions/agent-browser-policy.ts), and the shared Webflow skill. Cookie transfer is off by default. |
| Session Spend Dashboard | Runs an opt-in read-only localhost dashboard for provider-reported spend, token use, projects, sessions, and subagent activity. | [`extensions/session-spend-dashboard`](extensions/session-spend-dashboard), configured by [`session-spend-dashboard.json`](session-spend-dashboard.json). See its [README](extensions/session-spend-dashboard/README.md). |
| Warp session title | Shows the current Pi session name and project in the active Warp tab. It does nothing in other terminals. | [`extensions/warp-session-title.ts`](extensions/warp-session-title.ts), loaded from this Pi package. |
| Clear status | Older compact usage/status implementation retained for reference but not loaded or packaged. | [`disabled-extensions/clear-status.ts`](disabled-extensions/clear-status.ts). |
| Warp gateway links | Private Warp gateway and fallback extensions maintained in a separate repository. | Live links are `extensions/warp-gateway.ts` and `extensions/warp-link-fallback.ts`; edit `~/webdev/warp-pi-gateway`. |

The `SESSION` row shows cost and current context use. Context includes tokens
used, tokens left, and a percentage, so it is clear that the percentage means
used space. `SESSION TOKENS` contains the cumulative input, output, and
reasoning totals. `PROMPT CACHE` shows reused tokens, stored tokens, and the hit
rate. A subscription says `Included (subscription)`, while missing rates say
`Unavailable` instead of looking like a real `$0.000` cost. On a narrow
terminal, each labelled group wraps instead of dropping information from the
right side.

`REALTIME-SYSTEM-PROMPT.md` is tracked prompt configuration, not an extension.
It changes the realtime conversational mode used by Pi Codex Conversion.

### Managed setup files

The tables above explain the components. This table lists the files and command
that setup installs, plus the macOS host file used only for a live default
setup.

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
| `pi-update-all` | Links `scripts/pi-update-all` into `~/.local/bin`; updates a clean setup immediately or accepts one commit message when setup changes need to be validated and pushed first. |
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

## Shared agent skills

Tracked shared skills live under [`skills/`](skills) and are linked once into
`~/.agents/skills`. Pi and other compatible agent tools discover the same
installation. They are deliberately not duplicated under `~/.pi/agent/skills`,
which would cause skill-name collisions.

### TUI and CLI design

[`skills/tui-cli-design`](skills/tui-cli-design) is the automatic design and
review skill for keyboard-first terminal interfaces. It guides agents through
focus ownership, searchable pickers, keybindings, Escape and cancellation,
draft and save behavior, dynamic lists, narrow terminals, scriptable commands,
and lifecycle tests. The folder also contains concrete examples, a test matrix,
a review checklist, and links to the UX and Pi sources behind the guidance.

### Webflow browser

The tracked [`skills/webflow-designer-agent-browser`](skills/webflow-designer-agent-browser)
directory provides the shared Webflow Designer browser workflow. It exists to
separate a real Designer surface from login pages, error documents, empty local
shells, and the wrong iframe before any QA action changes state.

The configured lifecycle facade owns the transaction
`prepare` -> browser interaction -> `verify` -> authorized work -> `finish`.
The private receipt binds the transaction to the runtime identity and lease.
`finish` must prove `runtimeOwned: false`, `cdpReady: false`, `consumer: null`,
`leasePresent: false`, and `status: stopped`. After an interruption, `status`
classifies the runtime and `reconcile` handles only safe stale states.

For compact native browser results, the recommended host integration is
[`pi-agent-browser-native`](https://pi.dev/packages/pi-agent-browser-native?name=agent-browser-native).
The [standalone CLI reference](skills/webflow-designer-agent-browser/references/standalone-cli.md)
documents direct JSON use with `agent-browser`. A Playwright or Selenium
adapter is not included. All paths use a dedicated Chrome for Testing profile
and keep it separate from normal Chrome. The skill never stores credentials,
cookies, tokens, raw DOM, or customer data in the repository.

Before the first isolated run, Chrome for Testing opens visibly so the user can
sign in with a dedicated Webflow test user that has only the access needed for
QA. Its profile keeps the login for later runs. If an account must remain active
in another browser, the workflow asks to attach to that tab instead.
`browser-runtime.py` is the only process that starts or stops Chrome. The
automation client closes its session only after the runtime reports that Chrome
has stopped. Cleanup never signs out or clears cookies. When service endpoints
are not supplied, `https://wfdev.io:8443/` is the default probe for both `hud`
and `designer_service`; failed probes stop the run.

For a recorded result, generate and validate a mode-specific report with
`skills/webflow-designer-agent-browser/scripts/automation-evidence.py`. The
report includes the five readiness checks, sanitized semantic evidence, the
ownership boundary, and stopped-runtime proof.

The skill also has a maintenance-only, evidence-backed test-knowledge path.
`skills/webflow-designer-agent-browser/test-corpus-policy.json` selects a
small set of operation sources from the Webflow monorepo; the disposable
`test-corpus-index.py` command extracts commit-bound operation cards with
bounded provenance, confidence, holdouts, and negative evidence. It does not
copy test bodies or add a Playwright runtime transport. The companion
`ensure-test-aws.py` command validates the local AWS profile and the temporary
credentials inherited by `wf-app`, refreshing SSO and restarting only the stale
`server` HUD task, which owns `entrypoints/server`. It verifies the replacement
process, starts the task when it is missing, and keeps a credential-free PID
and expiration receipt in the private runtime directory. The companion
`test-scenario-eval.py` command validates a declared scenario contract and
emits a plan-only external setup/browser/assertion/teardown handoff. Existing
Webflow Playwright scenario helpers still own their browser contexts, so a
scenario cannot be treated as an agent-browser handoff until an explicitly
reviewed adapter provides a sanitized target and teardown artifact. The corpus
`evaluate` command checks held-out semantic evidence and overlap without
promoting a candidate.

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

Run `/spend-dashboard open` in Pi to start the dashboard and open it in your
browser. While you type, the command menu shows this shortcut. It also describes
each available action.

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
| Update command | `scripts/pi-update-all` | `~/.local/bin/pi-update-all` |
| Personal Pi package and extensions | This repo | Loaded from this checkout by the rendered owner settings, or from Pi's managed Git checkout for a public install |
| Shared agent skills | This repo | `~/.agents/skills/tui-cli-design` and `~/.agents/skills/webflow-designer-agent-browser` |
| Prewalk | Owning `pi-prewalk` checkout for development; floating GitHub source for clean installs | Local replacement when configured; otherwise `~/.pi/agent/git/github.com/javonmcgilberry/pi-prewalk` |
| Context budget | This repo | Loaded as part of this Pi package |
| Context Mode | [`mksglu/context-mode`](https://github.com/mksglu/context-mode), distributed as [`context-mode`](https://www.npmjs.com/package/context-mode) | npm package managed by Pi |
| pi-subagents | [`nicobailon/pi-subagents`](https://github.com/nicobailon/pi-subagents) | The unchanged release from the upstream npm package |
| Pi core | `~/Developer/pi` ([my fork](https://github.com/javonmcgilberry/pi)) | Separate development checkout; the normal `pi` command uses the installed release |
| Warp gateway | Private `warp-pi-gateway` repository | Edit `~/webdev/warp-pi-gateway`; live extensions are links |
| macOS tmux LaunchAgent | `config/com.javonmcgilberry.pi-tmux-gui-server.plist` | `~/Library/LaunchAgents/com.javonmcgilberry.pi-tmux-gui-server.plist` on a live default macOS install |
| Sessions | Pi runtime | `~/.pi/agent/sessions` by default; `PI_CODING_AGENT_SESSION_DIR` overrides it |
| Dashboard metrics | Session Spend Dashboard runtime | `~/.pi/agent/session-metrics/metrics.sqlite` by default; agent-directory overrides move it |

`config/manifest.json` is the authoritative list of global files, shell
commands, shared links, and macOS LaunchAgents managed by bootstrap. Package resources are declared separately in
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

The check validates JSON, tests the tracked local-settings example, checks shell
syntax and dependency metadata, verifies the tracked-file boundary, and looks
for common secret patterns. It never reads or copies `auth.json`.

Add `--fast` to skip the setup matrix (`scripts/setup.test.mjs`) when you want a
quick gate; run it without `--fast` before calling a change done.
