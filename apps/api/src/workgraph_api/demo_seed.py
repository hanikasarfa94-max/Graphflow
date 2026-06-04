"""Canonical demo seed helper (Phase 13).

One reusable walker for the canonical event-registration demo path, shared
by three callers:

  1. `tests/test_canonical_event_registration.py` — the authoritative
     Python E2E fixture that pins the demo cadence under 90s.
  2. `POST /api/demo/seed` — a dev/staging-only endpoint that lets the
     Playwright spec and demo-day dry runs boot a fresh DB into "just
     shipped the canonical project" state in one call.
  3. Future: reset tooling for demo-day kiosks.

The walker drives the real API via an httpx client (no direct service
calls) so the flow is identical to what a user would exercise through
the UI. This is important — the whole point of the demo fixture is
"exercised through the same surface the audience sees."

The helper is *provider-agnostic* — whatever agents are wired on
`app.state` run the flow. Tests wire stub agents; the seed endpoint
hits whatever the lifespan bound (DeepSeek in dev, stubs in CI).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient

CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)
DEFAULT_USERNAME = "demo_owner"
DEFAULT_PASSWORD = "hunter22"  # dev-only; the seed endpoint is 403 in prod.
DEFAULT_SOURCE_EVENT_ID = "demo-canonical-seed"


@dataclass(frozen=True)
class SeedResult:
    """What the walker produced — enough for tests and the API to cite."""

    project_id: str
    requirement_version: int
    clarification_ids: list[str]
    conflict_id: str
    decision_id: str
    delivery_id: str
    delivery_trace_id: str
    completed_scope_items: list[str]
    elapsed_seconds: float


async def _register_or_login(
    client: AsyncClient, *, username: str, password: str
) -> None:
    """Register the seed user; fall back to login if the row already exists.

    Cookies accumulate on the client, so a successful register is enough
    to authenticate subsequent calls on the same client.
    """
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    if r.status_code == 200:
        return
    # Typical failure: username taken. Try login.
    r = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    r.raise_for_status()


async def run_canonical_demo(
    client: AsyncClient,
    *,
    app_state,
    username: str = DEFAULT_USERNAME,
    password: str = DEFAULT_PASSWORD,
    source_event_id: str = DEFAULT_SOURCE_EVENT_ID,
) -> SeedResult:
    """Walk the canonical demo end-to-end.

    `client` must be an httpx AsyncClient pointed at the API (base_url).
    `app_state` is the FastAPI `app.state` object — we use it only to
    `drain()` the conflict service between phases so the walker is
    deterministic without sleeps. In-process tests use the real app
    state; an HTTP-only caller (Playwright) hits the endpoint in the
    same process so the drain still works.
    """
    import time

    start = time.monotonic()

    await _register_or_login(client, username=username, password=password)

    # --- 1. intake ---------------------------------------------------
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": source_event_id},
    )
    r.raise_for_status()
    project_id = r.json()["project"]["id"]

    # --- 2. clarification: generate + answer every question ---------
    r = await client.post(f"/api/projects/{project_id}/clarify")
    r.raise_for_status()
    questions = r.json()["questions"]
    clarification_ids: list[str] = [q["id"] for q in questions]

    final_body: dict[str, Any] = {}
    for q in questions:
        r = await client.post(
            f"/api/projects/{project_id}/clarify-reply",
            json={
                "question_id": q["id"],
                "answer": f"demo answer to: {q['question']}",
            },
        )
        r.raise_for_status()
        final_body = r.json()
    requirement_version = int(
        final_body.get("requirement_version", 1)
    )

    # --- 3. planning --------------------------------------------------
    r = await client.post(f"/api/projects/{project_id}/plan")
    r.raise_for_status()
    # Planning triggers an async conflict recheck — wait for it.
    await app_state.conflict_service.drain()

    # --- 4. conflict + decision --------------------------------------
    r = await client.get(f"/api/projects/{project_id}/conflicts")
    r.raise_for_status()
    conflicts = r.json()["conflicts"]
    if not conflicts:
        raise RuntimeError(
            "canonical demo: planning produced no conflicts — the stub/"
            "live plan should surface at least one missing_owner."
        )
    target = conflicts[0]
    r = await client.post(
        f"/api/conflicts/{target['id']}/decision",
        json={"option_index": 0, "rationale": "Demo-day approved path."},
    )
    r.raise_for_status()
    decision_id = r.json()["decision"]["id"]
    await app_state.conflict_service.drain()

    # --- 5. delivery --------------------------------------------------
    r = await client.post(f"/api/projects/{project_id}/delivery")
    r.raise_for_status()
    delivery_trace_id = r.headers["x-trace-id"]
    delivery = r.json()["delivery"]
    completed = [c["scope_item"] for c in delivery["content"]["completed_scope"]]

    elapsed = time.monotonic() - start
    return SeedResult(
        project_id=project_id,
        requirement_version=requirement_version,
        clarification_ids=clarification_ids,
        conflict_id=target["id"],
        decision_id=decision_id,
        delivery_id=delivery["id"],
        delivery_trace_id=delivery_trace_id,
        completed_scope_items=completed,
        elapsed_seconds=elapsed,
    )


# ---------------------------------------------------------------------------
# Disappearing-broker alpha-slice seed.
# ---------------------------------------------------------------------------

BROKER_SENDER = "demo_sender"
BROKER_RECIPIENT = "demo_recipient"
BROKER_SKILLS = ["backend", "data-export", "crm"]


@dataclass(frozen=True)
class BrokerSeedResult:
    """A 2-person project ready for the disappearing-broker loop demo."""

    project_id: str
    sender_username: str
    sender_id: str
    recipient_username: str
    recipient_id: str
    recipient_display_name: str
    password: str


async def run_broker_demo(
    client: AsyncClient,
    *,
    app_state,
    sender: str = BROKER_SENDER,
    recipient: str = BROKER_RECIPIENT,
    password: str = DEFAULT_PASSWORD,
    recipient_skills: list[str] | None = None,
    source_event_id: str = "demo-broker-seed",
) -> BrokerSeedResult:
    """Seed exactly two users in one project for the routing-loop demo.

    Produces: a sender (project owner) and a recipient who is the only
    skilled teammate — so the grounding gate either grounds on them or
    degrades gracefully, never 422. Backfills personal streams for both so
    My-AI posting works immediately. Does NOT send a route itself; the
    operator drives that live through the UI.
    """
    from workgraph_persistence import backfill_streams_from_projects

    recipient_skills = recipient_skills or list(BROKER_SKILLS)

    # Recipient first so we can capture their id + display name.
    await _register_or_login(client, username=recipient, password=password)
    me_r = (await client.get("/api/auth/me")).json()
    recipient_id = me_r["id"]
    recipient_display = me_r.get("display_name") or recipient

    # Sender registers (becomes the active cookie) and creates the project.
    await _register_or_login(client, username=sender, password=password)
    sender_id = (await client.get("/api/auth/me")).json()["id"]

    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": source_event_id},
    )
    r.raise_for_status()
    project_id = r.json()["project"]["id"]

    r = await client.post(
        f"/api/projects/{project_id}/invite", json={"username": recipient}
    )
    r.raise_for_status()

    # Owner-edit the recipient's skill tags so they are a grounded target.
    r = await client.patch(
        f"/api/projects/{project_id}/members/{recipient_id}/skills",
        json={"skill_tags": recipient_skills},
    )
    r.raise_for_status()

    # Personal streams for both users (My-AI + routing inbound need them).
    await backfill_streams_from_projects(app_state.sessionmaker)

    return BrokerSeedResult(
        project_id=project_id,
        sender_username=sender,
        sender_id=sender_id,
        recipient_username=recipient,
        recipient_id=recipient_id,
        recipient_display_name=recipient_display,
        password=password,
    )
