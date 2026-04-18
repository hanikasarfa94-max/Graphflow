#!/usr/bin/env bash
# Phase 11 AC — "AI-slop sniff test". Grep the built CSS for purple,
# violet, indigo, or blue-to-purple gradients. Zero matches wins.
# Source comments are allowed (they exist to document the rule);
# this checks the compiled output only.

set -euo pipefail

CSS_DIR=".next/static/css"
if [ ! -d "$CSS_DIR" ]; then
  echo "$CSS_DIR not found. Run 'next build' first." >&2
  exit 2
fi

PATTERNS='purple|violet|indigo|linear-gradient\s*\(\s*[^)]*(purple|violet|indigo)'

if grep -rEi "$PATTERNS" "$CSS_DIR"; then
  echo ""
  echo "AI-slop sniff test FAILED — found forbidden color tokens above." >&2
  exit 1
fi

echo "AI-slop sniff test passed (no purple/violet/indigo in built CSS)."
