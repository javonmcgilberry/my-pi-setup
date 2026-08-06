# Complete Pi setup documentation brief

## Outcome

The root README explains the full Pi setup in one place. A reader can see what
is installed, what each component does, where it is configured, where its
source lives, and what local data it keeps. The root AGENTS.md requires future
setup changes to keep that documentation current and to finish prose changes
with Humanizer followed by Chill.

## Current behavior

- `README.md` explains installation, ownership, syncing, and the main locally
  maintained components, but it does not catalog every package in
  `settings.json`, every MCP server, disabled integration, or config file.
- `AGENTS.md` defines source ownership and validation rules but does not make a
  README update part of the setup-change workflow.
- `settings.json` currently loads 22 package or local sources. The manifest
  also declares linked extensions, a disabled extension, a shared skill,
  external Warp links, and runtime exclusions.
- Pi sessions are append-only JSONL files with no stock automatic expiration.
  Compaction changes the active model context but preserves older transcript
  entries.
- Provider prompt caching and Codex WebSocket reuse are temporary remote or
  transport behavior, not session backups.
- The current dashboard configuration keeps chats for 7 days and content-free
  metrics for 365 days. Dashboard viewing does not delete chats; transcript
  deletion requires the explicit maintenance command and refuses to run while
  Pi is active.
- Setup backups cover managed configuration files. Sessions, caches,
  credentials, analytics databases, browser state, and other runtime data are
  intentionally excluded.
- The working tree already contains session-spend-dashboard retention changes.
  Documentation work must preserve and accurately describe those changes
  without rewriting their implementation.

## Decisions

1. The README will document everything that forms part of the working setup:
   Pi defaults, every loaded package, local and external extensions, MCP
   servers, shared skills, Prewalk, disabled items, and the relevant runtime
   data rules.
2. The catalog will use a consistent compact shape for each item: status,
   purpose, configuration, source of truth, live installation, and persistent
   or cached data when applicable.
3. The README will have one plain-language section covering provider caches,
   session files, compaction, dashboard retention, setup backups, and what
   `./sync` does not preserve.
4. Detailed package manuals remain in their owning READMEs. The root README is
   the complete map and links to those manuals rather than copying every
   command or internal detail.
5. AGENTS.md will stay concise. It will require a same-change README update
   whenever a setup change affects installed components, configuration,
   commands, ownership, live paths, user-visible behavior, or data handling.
6. Documentation changes will be checked against repository evidence, then
   edited with Humanizer and finally Chill. Those passes may simplify wording
   but must not remove paths, settings, commands, safety constraints, or
   uncertainty.
7. `PRODUCT.md` remains the product authority. README.md is the user-facing
   operating manual, while AGENTS.md is the agent workflow contract.
8. No credential, cookie, transcript content, private endpoint, or other
   machine-only state will be copied into documentation.

## Scope

### In scope

- `/Users/javonmcgilberry/Developer/my-pi-setup/README.md`
- `/Users/javonmcgilberry/Developer/my-pi-setup/AGENTS.md`
- The package, manifest, MCP, config, extension, skill, and owning-package
  documentation needed to verify the catalog

### Out of scope

- Changing extension behavior or configuration
- Publishing, syncing, committing, or installing the setup
- Rewriting detailed component READMEs that are already accurate
- Changing session cleanup, cache policy, compaction, or backup behavior
- Editing Pi-managed package source under `~/.pi/agent/npm` or
  `~/.pi/agent/git`

## Acceptance criteria

1. README.md accounts for every entry in `settings.json`'s `packages` array and
   every managed, linked, shared, external, disabled, and retired component in
   `config/manifest.json`.
2. README.md accounts for every server in `mcp.json` and clearly marks disabled
   integrations.
3. Each catalog entry states what it does, where its configuration lives, who
   owns its source, and where users should look for deeper documentation.
4. README.md plainly distinguishes provider cache reuse, local session
   persistence, compaction, dashboard retention, and setup backups.
5. The retention section states the configured 7-day chat and 365-day metrics
   windows, that cleanup is explicit rather than dashboard-triggered, and that
   active or unreadable session trees are protected.
6. README.md does not claim that compaction deletes transcript history or that
   `./sync` backs up runtime data.
7. AGENTS.md requires documentation updates in the same change and records the
   Humanizer-then-Chill order without duplicating the full catalog.
8. Existing working-tree changes remain intact.
9. `./scripts/check.sh` passes, and `./scripts/drift.sh` is run only as a
   read-only comparison.
10. A final inventory comparison finds no undocumented package, integration,
    or manifest item.

## Implementation units

### U1. Build the verified setup inventory

Compare `settings.json`, `package.json`, `config/manifest.json`, `mcp.json`,
the tracked config files, local extension READMEs, and installed package
metadata. Record only behavior that can be verified from those sources.

### U2. Rewrite the root README as the operating manual

Keep the useful installation and daily workflow material, add the complete
component catalog, and add the cache/session/retention/backup explanation.
Link to deeper component documentation instead of duplicating it.

### U3. Tighten the root agent contract

Add a short documentation-maintenance rule to AGENTS.md. Require the README
update and evidence check in the same setup change, followed by Humanizer and
Chill.

### U4. Review and verify

Run the two prose passes, compare the finished catalog against the package and
manifest inventories, run repository checks, inspect drift without applying
it, and review the final diff for private or machine-specific data.

## Execution

- [x] U1. Built the inventory from settings, the manifest, MCP/config files,
  local source, and installed package metadata.
- [x] U2. Rewrote the root README with the full component catalog and the
  cache, session, compaction, retention, and backup rules.
- [x] U3. Added the same-change README requirement and Humanizer-then-Chill
  order to the root agent contract.
- [x] U4. Ran both prose passes, matched all 47 package/MCP/manifest inventory
  items, verified all 18 local README links, passed `./scripts/check.sh` (67
  tests), and ran `./scripts/drift.sh` read-only. Drift remains for unsynced
  `settings.json` and `AGENTS.md`; no live files were changed.

## Verification

```sh
./scripts/check.sh
./scripts/drift.sh
```

Also compare the final README catalog against:

```sh
jq -r '.packages[]' settings.json
jq -r '.mcpServers | keys[]' mcp.json
jq -r '.copied[], .linked | keys[], .sharedSkills | keys[], .externalLinks[], .retired.pi[], .retired.shared[]' config/manifest.json
```

## Open blockers

None. The documentation scope is confirmed as the complete setup.

## Approval

Approved 2026-08-06
