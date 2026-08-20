#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/.." && pwd)"
cd "$ROOT"

python3 -B -m py_compile \
  skills/webflow-designer-agent-browser/scripts/test-corpus-index.py \
  skills/webflow-designer-agent-browser/scripts/webflow-scale-benchmark.py

python3 -B skills/webflow-designer-agent-browser/scripts/webflow-scale-benchmark.py \
  --repo "$ROOT" --format metrics
