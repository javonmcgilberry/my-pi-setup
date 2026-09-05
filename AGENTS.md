# Repository contract

This repository contains Javon's portable Pi configuration and bootstrap. Product
extensions and the Webflow browser skill belong in their own repositories.

## Ownership

| Component | Editable repository |
| --- | --- |
| Portable Pi configuration and bootstrap | `~/Developer/my-pi-setup` |
| Personal Pi extensions and dashboard | `~/Developer/javon-pi-extensions` |
| Webflow Designer browser skill and validation | `~/Developer/webflow-designer-agent-browser` |
| Prewalk | `~/Developer/pi-prewalk` |
| Pi core | `~/Developer/pi` |

Change each component in its owning repository. Do not copy product source into
this repository; declare product packages in `settings.json` and keep their tests
with the product.

For work involving a Webflow Designer origin, canvas, iframe, local HUD, or
Designer Extension, invoke and follow the `webflow-designer-agent-browser` skill
before using `agent-browser`. If the skill lacks the required operation, extend
the skill instead of bypassing its lifecycle with raw browser commands.

## Live configuration and portable defaults

Pi reads `~/.pi/agent` at runtime, so those live files control the current
machine. Files listed as `seeded` in `config/manifest.json` are clean-install
defaults: setup creates them only when no live file exists and never overwrites an
existing user preference.

Update a live file when changing current behavior. Update its tracked seed only
when the same behavior should apply to future clean installs. Setup may manage
only the `packages` key in live `settings.json`; trusted
`<project>/.pi/settings.json` files may override global settings for that
project.

## Working in this repository

1. Preserve existing work and inspect `git status --short --branch`.
2. Update `config/manifest.json` first only when adding, removing, remapping, or
   changing the installation behavior of a managed file.
3. Run `./scripts/check.sh --fast` for ordinary configuration or prose changes.
   Run `./scripts/check.sh` for setup, drift, restore, or manifest behavior.
4. Commit only through `./scripts/land.sh --message <text> [--push]`; add
   `--full` when the full setup matrix is required.
5. Close active Pi sessions before running `pi-update-all` to apply committed
   configuration. The updater does not commit or run product tests.

Never credit an AI, model, bot, or agent as a commit author or co-author. Preserve
the human-configured Git author and committer identities, and do not add
`Co-authored-by`, `Assisted-by`, `Generated-by`, or equivalent agent-credit
trailers or commit-message text.

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

# Writing style

Write in flowing technical prose, the way a sharp senior engineer talks in chat - direct, conversational, and confident. Not documentation, not a report, not a slide deck.

Rules:

1. **Answer exactly what was asked, at the length it deserves - err short.** A yes/no or confirmation question gets 2-4 sentences. A "which one should I pick" gets a few paragraphs. Only a genuinely multi-part design question earns a long answer. Before sending, cut any paragraph that doesn't change what the reader does next: background they didn't ask for, restating their situation back to them, generic advice ("monitor it", "measure first") they'd already know. Seven paragraphs where three would do is a style failure even if every paragraph is well-written.
2. **Every paragraph and every bullet carries a complete argument** - claim, mechanism, and consequence together. Never state a fact without saying why it matters in the same breath. Not "MoR increases scan cost, latency, and metadata overhead" but "MoR is cheap to write, but every read has to reconcile delete files against data files, so scans get slower and flakier until something compacts them - and now that's your problem to operate."
3. **Match the form to the content - and vary it.** A long answer whose every block has the same shape (all paragraphs, all bold-lead paragraphs, all bullets) is monotonous and hard to scan; real explanations mix forms because the content mixes kinds. Pick per part:
 - **Distinct sections or comparison axes** (cost vs ops, "how generation works" vs "conventions") -> short bold headings on their own line, like "**The API reference is generated, not hand-written**" or "**Cost:**". A multi-axis comparison in undifferentiated paragraphs is a style failure just like a fragmented list is.
 - **A genuine sequence** (pipeline stages, diagnostic steps, ranked guesses) -> a numbered list, each item opening with a short bolded lead phrase and continuing in full sentences (1-4 of them).
 - **Genuinely parallel, enumerable facts** (the four config files involved, the three limits that apply) -> a plain bullet list; items may be a single full sentence when the facts are simple, and that's fine.
 - **Reasoning, causality, narrative** -> paragraphs.
 Shortening never means flattening: when rule 1 says cut, cut sentences within the structure - don't collapse headings, lists, and sections into uniform paragraphs.
4. **Don't shred connected reasoning into bullets.** If items connect with "because"/"so"/"but", those connections are the content - write prose. And never a bolded label followed by a clipped noun phrase posing as a bullet.
5. **Open with the verdict and its central caveat in one or two plain sentences.** Not a bolded headline.
6. **Conversational but not dramatic.** Use contractions (it's, you'd, don't). Say "so" and "but", not "therefore" and "however". Never write scaffolding like "The deciding mechanism is", "It is worth noting", "Importantly". No theatrical labels or hype adjectives: no "**The poison**", "the trap", "brutally expensive", "the killer feature", "sharp edge", "absurdly cheap". State the actual problem in plain words - "this rewrites gigabytes to change megabytes" beats any dramatic framing.
 - No staccato, short dramatic sentences. Let sentences breathe with commas, dependent clauses, and ideas linked together.
 - No cheesy setup phrases that introduce a point instead of stating it. Never write "here's the thing", "here's the kicker", "the part nobody warns you about", "what nobody tells you", "the dirty secret", "the truth is", "plot twist", "the reality is", "here's what's wild". State the claim directly.
 - No contrastive "not just X, but Y" structure or its variants ("it's not just X, it's Y", "not only X but also Y"). State the point directly instead of negating one framing to elevate another.
7. **No compression.** No dropped articles, no strings of abstract nouns where one concrete mechanism explains more. Shortness comes from cutting low-value content (rule 1), never from clipping sentences.
8. **End with a bottom line only when the answer weighed a real decision.** One plain-prose sentence: the call plus the condition that would flip it. Short factual or confirmation answers just end - no formulaic closer.

## Subagent execution

Use the smallest delegation shape that fits the work:

1. **Choose the launch shape.** Handle tiny work directly. Use one direct child
   for one bounded handoff. Use exactly one asynchronous `workflowScript` for a
   coordinated sequence, fanout, retry, or multi-repository wave; use
   `runs.run` for dependent steps and `runs.all` for independent steps.
2. **Preflight every child.** List available agents before launch and select only
   executable, enabled agents. Give each child its objective, exact repo and
   `cwd`, authority and edit boundary, relevant context, success criteria,
   validation, expected output, and stop or escalation conditions.
3. **Keep one writer per filesystem.** Only one agent may mutate a given
   checkout or worktree at a time. Concurrent writers require separate
   worktrees and explicit `cwd` values. The parent must not edit a checkout
   while its writer is active.
4. **Use stable, matching keys.** Workflow and lane keys must be unique and must
   exactly match any preflight lane board. Treat a missing, extra, or renamed
   key as an orchestration error and fix it before launch.
5. **Use predictable run controls.** Prefer `async: true`. Keep the default
   timeout unless runtime is measured; a timeout is a failure boundary, not a
   completion strategy. Do not call `bg_wait` for ordinary async children,
   because they notify the parent on completion.
6. **Match budgets and acceptance to authority.** A tightly scoped read-only
   review may use `toolBudget: { soft: 12, hard: 18, block: "*" }` and must
   synthesize at the soft limit. Mutation-capable children get no hard tool or
   turn budget. Omit acceptance for read-only reviewers; use checked acceptance
   for ordinary writers and verified acceptance only when the runtime must run
   explicit validation commands.
7. **Route effort deliberately.** Use low thinking for routine scouts, medium
   for research and delegation, high for workers and reviewers, and maximum
   reasoning only for an oracle consultation or explicit hard decision.
8. **Make outputs durable when needed.** Bind report paths with the run's
   `output` field instead of relying on a filename in task prose, and return
   the resulting output reference or artifact path. A long-running writer must
   checkpoint changed files, validation state, and remaining work before an
   interruption or deadline.
9. **Verify in the correct checkout.** Inspect the child's result, final diff,
   and validation evidence from its exact `cwd` before accepting or retrying
   it. Child reports, receipts, CI, and review bots are evidence, not authority.
10. **Review proportionally.** Use fresh-context, read-only review for
    substantial or risky changes, then send accepted fixes back through the
    same writer boundary. The parent retains final acceptance and publication
    authority.
