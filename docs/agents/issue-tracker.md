# Issue tracker: local Markdown

Issues and specifications created by the engineering skills live only in this
repository under `.scratch/`. Do not publish them to Linear, GitHub Issues, or
another remote tracker unless the user explicitly changes this repository-local
policy.

## Conventions

- One effort per directory: `.scratch/<feature-slug>/`.
- The specification is `.scratch/<feature-slug>/spec.md`.
- Implementation issues are one file per ticket at
  `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01` in
  dependency order.
- Triage state is a `Status:` line near the top of each issue file. Use the
  values in `triage-labels.md`.
- Append discussion to the relevant file under `## Comments`.

When a skill says to publish to the issue tracker, create or update a file under
the corresponding `.scratch/<feature-slug>/` directory. When it says to fetch a
ticket, read the referenced local file.

## Wayfinding operations

Wayfinder uses a map with one child file per decision ticket:

- Map: `.scratch/<effort>/map.md`.
- Child ticket: `.scratch/<effort>/issues/<NN>-<slug>.md`.
- Type: a `Type:` line containing `research`, `prototype`, `grilling`, or
  `task`.
- Status: a `Status:` line containing `claimed` or `resolved`; an unclaimed
  open ticket omits either terminal state.
- Blocking: a `Blocked by: NN, NN` line. A ticket is unblocked when every
  listed file is resolved.
- Frontier: open, unblocked, unclaimed files under the effort's `issues/`
  directory, ordered by ticket number.
- Claim: write `Status: claimed` before beginning work.
- Resolve: append the result under `## Answer`, write `Status: resolved`, and
  add a linked one-line gist to the map's `Decisions so far` section.

These files are ignored by Git. They are local planning state, not shipped
repository documentation.
