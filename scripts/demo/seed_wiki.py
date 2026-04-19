"""Seed Moonshot wiki pages from workgraph-mock-data-v2 into the KB.

Loads both en + zh-CN lanes as MembraneSignalRows (source_kind='wiki'),
pre-approved, tagged with language so the KB surface can filter per
viewer locale. Idempotent — existing rows matched by source_identifier
are left alone.

Usage:
    uv run python scripts/demo/seed_wiki.py

Assumes the dev API is running at http://127.0.0.1:8000 and Moonshot
has already been seeded (raj / aiko / etc. + project). This script
talks to the DB directly via the persistence layer.
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Project root imports.
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packages" / "persistence" / "src"))
sys.path.insert(0, str(REPO / "apps" / "api" / "src"))

from workgraph_persistence.db import build_engine, build_sessionmaker  # noqa: E402
from workgraph_persistence.orm import (  # noqa: E402
    MembraneSignalRow,
    ProjectRow,
    UserRow,
)

MOCK = REPO / "workgraph-mock-data-v2" / "datasets" / "wiki" / "stable" / "moonshot"
EN_YAML = MOCK / "pages.yaml"
ZH_YAML = MOCK / "pages.zh-CN.yaml"

DB_URL = f"sqlite+aiosqlite:///{REPO / 'data' / 'workgraph.sqlite'}"


async def _all_project_ids(session: AsyncSession) -> list[str]:
    rows = (await session.execute(select(ProjectRow))).scalars().all()
    return [r.id for r in rows]


async def _user_by_username(session: AsyncSession, username: str) -> UserRow | None:
    return (
        await session.execute(
            select(UserRow).where(UserRow.username == username)
        )
    ).scalar_one_or_none()


async def _existing_source_ids(session: AsyncSession, project_id: str) -> set[str]:
    rows = (
        (
            await session.execute(
                select(MembraneSignalRow.source_identifier).where(
                    MembraneSignalRow.project_id == project_id,
                    MembraneSignalRow.source_kind == "wiki",
                )
            )
        )
        .scalars()
        .all()
    )
    return {r for r in rows if r}


async def _insert_page(
    session: AsyncSession,
    *,
    project_id: str,
    page: dict[str, Any],
    language: str,
) -> None:
    owner = await _user_by_username(session, page["owner_user_id"])
    tags = list(page.get("tags") or []) + [f"lang:{language}"]
    classification = {
        "is_relevant": True,
        "tags": tags,
        "summary": page["title"],
        "proposed_target_user_ids": [owner.id] if owner else [],
        "proposed_action": "ambient-log",
        "confidence": 1.0,
        "safety_notes": "",
        "wiki": {
            "page_id": page["page_id"],
            "language": language,
            "visibility": page.get("visibility", "project"),
            "links": list(page.get("links") or []),
            "stale": bool(page.get("stale", False)),
            "updated_at": str(page.get("updated_at", "")),
        },
    }
    row = MembraneSignalRow(
        id=str(uuid.uuid4()),
        project_id=project_id,
        source_kind="wiki",
        source_identifier=f"{page['page_id']}::{language}",
        raw_content=page["body_md"],
        classification_json=classification,
        status="approved",
        ingested_by_user_id=owner.id if owner else None,
        approved_by_user_id=owner.id if owner else None,
    )
    session.add(row)


async def main() -> int:
    engine = build_engine(DB_URL)
    sessionmaker = build_sessionmaker(engine)

    en_pages = yaml.safe_load(EN_YAML.read_text(encoding="utf-8"))["pages"]
    zh_pages = yaml.safe_load(ZH_YAML.read_text(encoding="utf-8"))["pages"]

    async with sessionmaker() as session:
        project_ids = await _all_project_ids(session)
        if not project_ids:
            print("[FAIL] no project in DB — seed Moonshot first.")
            return 1

        results: list[dict] = []
        for project_id in project_ids:
            existing = await _existing_source_ids(session, project_id)
            inserted_en = 0
            inserted_zh = 0
            for page in en_pages:
                if f"{page['page_id']}::en" in existing:
                    continue
                await _insert_page(
                    session, project_id=project_id, page=page, language="en"
                )
                inserted_en += 1
            for page in zh_pages:
                if f"{page['page_id']}::zh" in existing:
                    continue
                await _insert_page(
                    session, project_id=project_id, page=page, language="zh"
                )
                inserted_zh += 1
            results.append(
                {
                    "project_id": project_id,
                    "inserted_en": inserted_en,
                    "inserted_zh": inserted_zh,
                    "skipped": len(existing),
                }
            )

        await session.commit()

    await engine.dispose()
    print(f"[OK] seeded wiki across {len(project_ids)} project(s)")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
