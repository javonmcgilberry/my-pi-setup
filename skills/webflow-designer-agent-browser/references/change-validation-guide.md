---
title: "Webflow Designer change validation guide"
---

# Webflow Designer change validation guide

Use this guide when a Webflow Designer change is ready to check. It explains the normal path. Read the [architecture reference](evidence-compiler-architecture.md) for the compiler, contracts, receipts, and PICO rationale.

## What this validator does

The validator reads every relevant changed file. When it finds a reviewed match, it chooses that test and reports what the test proved. It avoids a reassuring but weak result such as "the click worked."

A successful result means the selected fixed test reached its declared end state and proved its teardown. It does not mean every part of Webflow is correct.

## Normal path

Ask Pi to validate the current Webflow changes. Pi calls the Webflow Designer custom tool with validate_change in route mode. Give it the read-only path to the Webflow checkout.

The route result has one of four meanings:

| Result | What it means | What to do |
|---|---|---|
| Trusted and ready | Every relevant changed file matches one reviewed runner. No model proposal is needed. | Run trusted validation. |
| Passed | The fixed runner completed its semantic check and teardown. | Report the receipt. |
| Approval required | A path is not in the reviewed mapping, but the validator can describe a tightly bounded candidate. | Review the proposed action graph, target, oracle, cleanup, and budget. Approve one exact run only if they are safe. |
| Insufficient evidence or routing ambiguous | The validator does not have one safe, clear runner. The exact statuses are `insufficient_evidence` and `routing_ambiguous`. | Report the named gap. Do not guess a test or force a pass. |

## What Pi does for a trusted change

For a trusted route, Pi runs the fixed scenario listed in the tracked policy. The policy owns the test path, grep string, worker count, timeout, and AWS preflight requirement. The agent does not invent a command. It does not loosen a test to make it pass.

Known routes normally use no model call. This is the cheapest path and the one to prefer.

## When a candidate needs approval

An unknown change may produce one candidate contract. It is data, not an arbitrary script. It can use only reviewed operations and selector keys, one fixed adapter, a typed check of the visible end state, and adapter teardown. It has a small action limit, one retry at most, and the selected runner's fixed timeout.

Before it can run, Pi shows the evidence, target, actions, expected end state, cleanup, and budget. The user must approve the exact 64-character digest. After approval, the Pi host issues a short-lived one-time confirmation token; Code Mode consumes that token with the digest, and the approval cannot be reused after the run.

Declining is a valid result. So is stopping because the evidence is not strong enough.

## How to read the receipt

| Receipt field | Meaning |
|---|---|
| status: passed | The selected fixed runner completed. |
| semanticOracle: passed | The run reached the state that the contract asked it to prove. |
| cleanup: proved | The run proved its declared teardown. |
| cleanup: not_proved | The process failed or stopped before it could prove teardown. This is not a claim that cleanup failed. |
| cleanup: failed | The runner explicitly reported a teardown failure. |
| failureClass | A short category such as timeout, infrastructure failure, scenario setup failure, semantic assertion failure, or teardown failure. |

Runner output stays private. The receipt reports only the small facts needed to understand the result.

## Things not to do

- Do not treat ready as passed. Ready means the validator found a trusted route but has not run it.
- Do not ignore an unknown or ambiguous changed path.
- Do not approve a candidate because it sounds plausible. Read its target, actions, oracle, cleanup, and budget.
- Do not weaken selectors, assertions, fixtures, worker counts, or verification assets to make a test pass.
- Do not claim teardown completed after a failed process unless the receipt says proved.
- Do not use corpus discovery as routine end-of-work validation. It is an offline maintenance activity.

## When to use the other references

- Read [standalone CLI](standalone-cli.md#change-validation) when Pi is unavailable or CI needs the same deterministic path.
- Read [compounding loop](compounding-loop.md) when reviewing repeated evidence for a new operation or mapping. Runtime receipts never promote a candidate by themselves.
- Read [architecture reference](evidence-compiler-architecture.md) when you need the offline compiler, contract rules, PICO rationale, or exact paper references.

The safe default is simple: run a trusted route when one exists, stop when it does not, and treat every receipt as evidence with a clear limit.
