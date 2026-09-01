# Test knowledge maintenance

Use this branch only during skill maintenance, corpus review, or
scenario-backed validation planning. The Webflow monorepo's Playwright and
Cypress tests are evidence, not an unrestricted instruction set.

## Build and inspect the corpus

Build a disposable, commit-bound corpus index from the tracked policy:

```sh
tmp="$(mktemp -d)"
python3 scripts/test-corpus-index.py discover \
  --repo /path/to/webflow \
  --output "$tmp/designer-discovery.json"
python3 scripts/test-corpus-index.py validate-discovery \
  --repo /path/to/webflow \
  --discovery "$tmp/designer-discovery.json"
python3 scripts/test-corpus-index.py build \
  --repo /path/to/webflow \
  --output "$tmp/designer-corpus.json"
python3 scripts/test-corpus-index.py validate \
  --repo /path/to/webflow \
  --index "$tmp/designer-corpus.json"
python3 scripts/test-corpus-index.py lookup \
  --repo /path/to/webflow \
  --index "$tmp/designer-corpus.json" \
  --operation designer.page.switch
python3 scripts/test-corpus-index.py evaluate \
  --repo /path/to/webflow \
  --index "$tmp/designer-corpus.json"
```

`discover` is the offline compiler's broad inventory pass. It uses a
brace-aware structural extractor to bound evidence to individual test or
helper bodies, records only non-sensitive action and selector classes and
source ranges, and clusters fragments only when a hashed behavior anchor
matches. Generic actions without an anchor stay isolated and cannot establish
corroboration or a holdout. Holdouts also require independent helper or
scenario lineage. Discovery never creates executable cards or promotes a
candidate. Validate the generated report with `validate-discovery` before
reviewing it.

`build` is the narrower curation pass. It retains bounded provenance,
selectors, context, postconditions, confidence, utility, novelty, holdouts,
and negative evidence. Quarantined, skipped, stale, unsafe, or fixed-duration
wait evidence cannot become positive executable knowledge. `evaluate` checks
held-out semantic assertions and positive/holdout path separation without
promoting a candidate. The source commit and source-file manifest must still
match before lookup.

Discovery and promotion are offline maintenance work. The runtime can emit a
sanitized drift or failure receipt, but maintenance owns every policy,
selector, and promotion change. Read [the automation maintenance loop](compounding-loop.md)
before promoting any repeated browser sequence.

The same validated index is available through the `webflow_designer` Code Mode
operation `test_knowledge`. Use `view:"status"` for compact freshness and
portfolio counts, or pass one `operationId` or capability `category` for a
bounded card lookup.

## Plan scenario-backed validation

Scenario contracts are plan-only handoffs between an external test-data
adapter and the managed browser lifecycle:

```sh
python3 scripts/ensure-test-aws.py --repo /path/to/webflow
python3 scripts/test-scenario-eval.py plan \
  --scenario /path/to/scenario.json \
  --operation /path/to/operation-card.json \
  --dry-run
```

Run `ensure-test-aws.py` before scenario-backed local tests. It validates the
`dev-publish-only` profile without trusting inherited AWS variables, performs
`aws sso login --sso-session wf-session` only when required, checks the exact
temporary credentials held by every running `wf-app`, and restarts only the
`server` HUD task, which owns `entrypoints/server`, when those credentials are
missing or stale. If the server is not running, the preflight starts it.
Because `wf-app` hides its environment when it replaces its visible command
line, the check follows the process ancestry. The JSON output never includes
credential values. After a repair, the command stores only the server PID and
credential expiration in the private runtime directory. Later checks use that
receipt to avoid restarting a server that already has fresh credentials. Use
this preflight instead of researching the local AWS setup or starting a second
server.

This command does not run Playwright, create accounts, open a browser, or
execute generated shell text. Existing Webflow Playwright scenario helpers own
their browser contexts. A future external adapter must provide a sanitized
Designer-target handoff and teardown artifact before a managed
`prepare -> interaction -> verify -> finish` run can use it. A scenario plan is
not authorization to mutate a shared or customer surface.
