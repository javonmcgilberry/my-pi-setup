# Repository contract

This repository is the lightweight source of truth for Javon's portable Pi
configuration. It does not own product extensions or the Webflow browser skill.

## Ownership

| Component | Editable repository |
| --- | --- |
| Portable Pi configuration and bootstrap | `~/Developer/my-pi-setup` |
| Personal Pi extensions and dashboard | `~/Developer/javon-pi-extensions` |
| Webflow Designer browser skill and validation | `~/Developer/webflow-designer-agent-browser` |
| Prewalk | `~/Developer/pi-prewalk` |
| Pi core | `~/Developer/pi` |

Do not copy product source back into this repository. Declare product packages
in `settings.json` and keep their tests in their owning repositories.

Pi's live files under `~/.pi/agent` are authoritative for user preferences,
including `settings.json`, extension JSON configuration, and global prompt or
agent-policy files. Do not change tracked defaults for a routine preference
update. Tracked preference files seed a clean install only and must never
overwrite an existing live file. Setup manages only the `packages` key inside
`settings.json`, which is needed for package inventory and local-checkout
selection. Trusted project settings in `<project>/.pi/settings.json` may
override the global settings for that project.

## Workflow

1. Preserve existing work and inspect `git status --short --branch`.
2. Update `config/manifest.json` before changing managed files or targets.
3. Run `./scripts/check.sh` for normal configuration changes.
4. Run `./scripts/check.sh --full` only when setup, drift, restore, or manifest
   behavior changes.
5. Commit through `./scripts/land.sh --message <text> [--push]`.
6. Close every Pi session and run `pi-update-all` to apply clean committed
   configuration. The updater never commits and never runs product tests.

While Pi is active, use one temporary root for `PI_AGENT_DIR`,
`PI_CODING_AGENT_DIR`, and `AGENTS_SKILLS_DIR` when testing setup or drift.

Keep credentials, auth files, sessions, browser profiles, cookies, caches,
package clones, generated artifacts, and runtime databases out of Git.

## Slack research

Whenever Slack information is needed, use the globally installed `slack-cli`.
Never use or configure a Slack MCP server. Confirm access with
`slack-cli auth status`, then use commands such as
`slack-cli search messages '<query>' --limit <count>` or
`slack-cli search all '<query>'`; the CLI returns JSON. Do not start a separate
OAuth flow unless the CLI reports that its existing Slack desktop credentials
are unavailable.

## Subagent execution

- Let ordinary single subagent runs use Pi's 30-minute default. Set an explicit
  timeout only when the task has a measured runtime, and leave enough margin
  for the child to write its result. A 5- or 10-minute timeout is not suitable
  for a repository review on a high-reasoning model.
- Split broad research into milestones. Have the child save a source inventory
  or draft before the halfway point, then resume it for synthesis. Long-running
  writers must report a checkpoint with changed files, validation state, and
  remaining work before their deadline.
- Bound a tightly scoped read-only review with
  `toolBudget: { soft: 12, hard: 18, block: "*" }` and tell the child to
  synthesize at the soft limit. The wildcard is the string `"*"`, not
  `["*"]`. A mutation-only block list does not bound a read-only review.
- Use active-run notices and one clear steer to stop gathering evidence and
  finalize before a long run's deadline. A timeout is a last-resort failure
  boundary, not a completion or mutation-safety boundary.
- Keep routine scouts at low thinking, researchers and delegates at medium,
  workers and reviewers at high, and reserve max thinking for the oracle or an
  explicit hard decision.
- Omit acceptance for read-only reviewers. Mutation-capable children use
  checked acceptance without hard tool or turn budgets. Give report-writing
  children one authoritative output path; do not combine a repository output
  path with a conflicting artifact-only destination.
