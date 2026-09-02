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

## Agent skills

### Issue tracker

This repository uses local Markdown issues under `.scratch/`; no remote issue
tracker is configured for agent-planned work. See
`docs/agents/issue-tracker.md`.

### Triage labels

Local issue status uses the five canonical triage labels. See
`docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. Read root `CONTEXT.md` and relevant ADRs
under `docs/adr/`. See `docs/agents/domain.md`.
