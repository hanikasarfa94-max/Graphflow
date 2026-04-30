"""Backfill membrane_signals → kb_items — Stage F2 of the fold.

Revision ID: 0023_backfill_signals_to_kb
Revises: 0022_kb_items_absorb_signals
Create Date: 2026-04-26

Stage F1 widened kb_items to fit the signal shape. This migration
copies every membrane_signals row into kb_items as a fully-formed
ingest row, preserving the id so any future references stay valid.

Mapping (membrane_signals → kb_items):
  id                    → id
  project_id            → project_id
  folder_id             → folder_id
  ingested_by_user_id   → owner_user_id  (also kept verbatim in
                          ingested_by_user_id; signals had a single
                          "who dropped this" person, kb_items wants
                          both the legacy view (ingested_by) and the
                          new owner abstraction. We mirror.)
  source_kind           → source_kind
  source_identifier     → source_identifier
  raw_content           → raw_content
  classification_json   → classification_json
  status                → status        (vocabularies kept distinct;
                          'pending-review'/'approved'/'rejected'/
                          'routed' all valid for source='ingest')
  approved_by_user_id   → approved_by_user_id
  approved_at           → approved_at
  trace_id              → trace_id
  created_at            → created_at
  (synth)               → updated_at = created_at
  (synth)               → source = 'ingest'
  (synth)               → scope  = 'group'    (signals were always
                          project-wide; preserves the membrane KB
                          tree visibility behavior)
  (synth)               → title  = classification_json.summary[:500]
                          OR raw_content[:80] OR source_identifier
                          OR 'Untitled signal'
  (synth)               → content_md = ''     (raw_content carries
                          the body for ingests; content_md is for
                          user-authored markdown)

Idempotent: INSERT OR IGNORE on the id PK collision means re-running
this migration after a partial backfill skips already-copied rows.
The same property lets the migration coexist with F3's write
cutover during the rollout window — if writes start landing in
kb_items before backfill finishes, the existing-id rows just
short-circuit instead of doubling up.

Reversible: downgrade deletes every kb_items row with source='ingest'.
This is safe ONLY when run before F3 (write cutover). After F3,
new ingests live in kb_items as the source of truth and the
downgrade would wipe live data — at that point the membrane_signals
table is already drained and the downgrade window has closed.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0023_backfill_signals_to_kb"
down_revision: str | Sequence[str] | None = "0022_kb_items_absorb_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Title-pick uses JSON_EXTRACT on classification_json. Both SQLite
# (3.38+) and PostgreSQL (12+ with the json_extract_path_text variant
# below) ship this; SQLAlchemy's `func.json_extract` would route to
# the dialect-specific form, but Alembic data migrations run in the
# raw connection so we write SQLite-flavored SQL and rely on the
# PostgreSQL adapter's compatibility shim if/when we move off SQLite.
# (PG path: replace `json_extract(classification_json, '$.summary')`
# with `classification_json ->> 'summary'`.)
_BACKFILL_SQL = """
INSERT OR IGNORE INTO kb_items (
    id,
    project_id,
    folder_id,
    owner_user_id,
    scope,
    title,
    content_md,
    status,
    source,
    source_kind,
    source_identifier,
    raw_content,
    classification_json,
    ingested_by_user_id,
    approved_by_user_id,
    approved_at,
    trace_id,
    created_at,
    updated_at
)
SELECT
    s.id,
    s.project_id,
    s.folder_id,
    s.ingested_by_user_id,
    'group',
    COALESCE(
        NULLIF(SUBSTR(json_extract(s.classification_json, '$.summary'), 1, 500), ''),
        NULLIF(SUBSTR(s.raw_content, 1, 80), ''),
        SUBSTR(s.source_identifier, 1, 500),
        'Untitled signal'
    ),
    '',
    s.status,
    'ingest',
    s.source_kind,
    s.source_identifier,
    s.raw_content,
    COALESCE(s.classification_json, '{}'),
    s.ingested_by_user_id,
    s.approved_by_user_id,
    s.approved_at,
    s.trace_id,
    s.created_at,
    s.created_at
FROM membrane_signals s
"""


def upgrade() -> None:
    op.execute(_BACKFILL_SQL)


def downgrade() -> None:
    # Wipes ONLY the rows this migration could have created. User-
    # authored kb_items (source in 'manual'/'upload'/'llm') are
    # untouched. Safe to run pre-F3; destructive post-F3.
    op.execute("DELETE FROM kb_items WHERE source = 'ingest'")
