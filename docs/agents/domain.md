# Domain docs

Engineering skills should read this repository's domain documentation before
exploring or changing an affected area.

## Sources

- Read root `CONTEXT.md` for the shared glossary.
- Read relevant records under `docs/adr/` when that directory exists.
- If a future `CONTEXT-MAP.md` appears, follow it to the context relevant to the
  work.

Missing ADR directories are not errors. `/domain-modeling`,
`/grill-with-docs`, and `/improve-codebase-architecture` create records only
when a real term or hard-to-reverse decision needs one.

## Vocabulary

Use terms as defined in `CONTEXT.md` in tickets, plans, tests, and architecture
work. If a needed concept is missing or overloaded, resolve it through domain
modeling rather than introducing an unrecorded synonym.

## ADR conflicts

If proposed work contradicts an ADR, identify that conflict explicitly. Do not
silently replace the recorded decision.

This repository uses a single root context. Add a multi-context layout only if
the repository later develops genuinely independent domain contexts.
