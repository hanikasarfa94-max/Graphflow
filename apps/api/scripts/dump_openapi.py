"""Dump the FastAPI OpenAPI schema deterministically (C1-A).

Import-only: builds the schema from the module-top `app` via `app.openapi()`,
which walks the registered routes and touches NO database, Redis, or LLM client
(all of that lives inside `lifespan`, which only runs on real startup). So this
is safe to run in CI with no services.

MUST run with WORKGRAPH_ENV != "dev": the dev-only `/_debug/boom` route is
registered only when env == "dev" (main.py), so a dev-mode dump would poison the
canonical schema and make the drift gate flap. We fail loudly rather than emit a
dev-shaped schema.

Output is `json.dumps(..., sort_keys=True, indent=2)` so the committed artifact is
byte-stable and `git diff --exit-code` is a reliable drift signal.

Usage:
    WORKGRAPH_ENV=staging uv run python apps/api/scripts/dump_openapi.py [OUT]
    # OUT defaults to apps/api/openapi.json; "-" writes to stdout.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Default output: apps/api/openapi.json (this file is apps/api/scripts/…).
_DEFAULT_OUT = Path(__file__).resolve().parents[1] / "openapi.json"


def main() -> None:
    if (os.environ.get("WORKGRAPH_ENV") or "dev").lower() == "dev":
        sys.stderr.write(
            "refusing to dump in dev mode: set WORKGRAPH_ENV=staging so the "
            "dev-only /_debug/boom route is excluded from the canonical schema.\n"
        )
        raise SystemExit(2)

    from workgraph_api.main import app

    schema = app.openapi()
    text = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    arg = sys.argv[1] if len(sys.argv) > 1 else str(_DEFAULT_OUT)
    if arg == "-":
        sys.stdout.write(text)
    else:
        Path(arg).write_text(text, encoding="utf-8")
        sys.stderr.write(f"wrote {arg} ({len(schema['paths'])} paths)\n")


if __name__ == "__main__":
    main()
