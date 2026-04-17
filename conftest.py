"""Root conftest: load .env before any test module imports.

Without this, os.environ.get("DEEPSEEK_API_KEY") returns None at collection
time and smoke tests skip. pydantic-settings reads .env at Settings() call,
but our skip-markers evaluate earlier.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).parent
load_dotenv(_REPO_ROOT / ".env")
