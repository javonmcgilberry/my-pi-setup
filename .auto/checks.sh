#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$BASH_SOURCE")/.." && pwd)"
cd "$ROOT"

unexpected="$({
  git diff --name-only
  git diff --cached --name-only
  git ls-files --others --exclude-standard
} | sort -u | while IFS= read -r path; do
  if [[ "$path" == .auto/* ||
    "$path" == skills/webflow-designer-agent-browser/scripts/test-corpus-index.py ||
    "$path" == skills/webflow-designer-agent-browser/scripts/webflow-scale-benchmark.py ||
    "$path" == skills/webflow-designer-agent-browser/scripts/test_webflow_scale_benchmark.py ]]; then
    continue
  fi
  printf '%s\n' "$path"
done)"
if [ -n "$unexpected" ]; then
  printf 'out-of-scope changed paths:\n%s\n' "$unexpected" >&2
  exit 1
fi

python3 -B -m py_compile \
  skills/webflow-designer-agent-browser/scripts/test-corpus-index.py \
  skills/webflow-designer-agent-browser/scripts/webflow-scale-benchmark.py \
  skills/webflow-designer-agent-browser/scripts/test_webflow_scale_benchmark.py

python3 -B -m unittest \
  skills/webflow-designer-agent-browser/scripts/test_test_corpus_index.py \
  skills/webflow-designer-agent-browser/scripts/test_webflow_scale_benchmark.py \
  skills/webflow-designer-agent-browser/scripts/test_webflow_hardening_benchmark.py \
  2>&1 | tail -100

python3 -B skills/webflow-designer-agent-browser/scripts/webflow-scale-benchmark.py \
  --repo "$ROOT" --format verify

python3 -B skills/webflow-designer-agent-browser/scripts/webflow-hardening-benchmark.py \
  --repo "$ROOT" --format verify

git diff --check
