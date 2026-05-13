"""Phase B.1 — v0.6.2 Conversations surface (API_CONTRACT §"Conversations").

Wraps `StreamService` (DMs, rooms, project streams) and a thin Topic
layer (TopicStatus-tracked focused threads) in the v0.6.2 shape.

The list endpoint enforces the **topic dedup invariant** from
INVARIANT_TESTS.md §"Topic deduplication":

    Recent = DMs + Rooms
    Active Topics = Topics whose status ∈ {open, needs_input, waiting}
    A conversation in `recent` MUST NOT also appear in `active_topics`.

The filter happens server-side; the FE never has to dedup.

Endpoints:

  * GET   /api/conversations?scope_id=...
  * GET   /api/conversations/{id}
  * POST  /api/conversations/{id}/messages
  * POST  /api/topics                                  (B.1 stub)
  * PATCH /api/topics/{id}/status                      (B.1 stub)
  * POST  /api/topics/{id}/propose-closure             (B.1 stub)

Topics surface is stub-shaped for B.1. We register the contract slots
now so frontend integration isn't blocked; Phase B.2 wires real Topic
primitives (TopicRow + TopicStatus column + StreamService.create_topic).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, StreamService

router = APIRouter(prefix="/api", tags=["conversations"])


# ---- enums (mirror schemas.graphflow.json) -------------------------------

ConversationTypeT = Literal["direct", "room", "topic"]
TopicStatusT = Literal["open", "needs_input", "waiting", "resolved", "archived"]

# Topic statuses that count as "active" — INVARIANT_TESTS.md §"Topic
# deduplication" implicitly defines this set as the inverse of
# resolved/archived.
_ACTIVE_TOPIC_STATUSES: set[str] = {"open", "needs_input", "waiting"}

_VALID_TOPIC_STATUSES: set[str] = {
    "open",
    "needs_input",
    "waiting",
    "resolved",
    "archived",
}


# ---- request shapes -------------------------------------------------------


class ConversationMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4000)


class CreateTopicRequest(BaseModel):
    """Create a Topic from selected source messages.

    A Topic is a focused thread carved out of a Conversation. It owns
    a TopicStatus lifecycle independent from the parent stream.
    """

    model_config = ConfigDict(extra="forbid")

    scope_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    source_conversation_id: str | None = Field(default=None, max_length=64)
    seed_message_ids: list[str] = Field(default_factory=list, max_length=50)


class UpdateTopicStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TopicStatusT


class ProposeTopicClosureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rationale: str = Field(default="", max_length=2000)


# ---- helpers --------------------------------------------------------------


def _service(request: Request) -> StreamService:
    return request.app.state.stream_service


def _classify_conversation_type(stream: dict[str, Any]) -> ConversationTypeT:
    """Map StreamService stream-kind onto v0.6.2 ConversationType.

    StreamService surfaces kinds like 'dm', 'room', 'project',
    'personal'. v0.6.2 collapses them onto three: direct (=dm),
    room (=room or project), topic (= a future TopicRow). We bias
    'project' → 'room' since v0.6.2 reads the team room as a Room.
    """
    kind = stream.get("kind") or stream.get("type") or ""
    if kind == "dm":
        return "direct"
    return "room"


# ---- conversations endpoints ---------------------------------------------


@router.get("/conversations")
async def get_conversations(
    request: Request,
    scope_id: str | None = Query(default=None, max_length=64),
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """List conversations the caller is in, partitioned for the FE.

    Response shape (INVARIANT_TESTS.md §"Topic deduplication"):

        {
          "recent": [...],          # DMs + Rooms
          "active_topics": [...]    # Topics with status ∈ active set
        }

    Dedup invariant: a conversation appears in **exactly one** of the
    two arrays. The server filters; the FE renders.
    """
    service = _service(request)
    streams = await service.list_for_user(user.id)

    # Scope-aware filter — v0.6.2 alias project_id → scope_id. DMs
    # have no scope, so the scope filter only narrows rooms/topics.
    if scope_id is not None:
        streams = [
            s
            for s in streams
            if s.get("project_id") in (None, scope_id) or s.get("scope_id") == scope_id
        ]
        # DMs survive the filter (project_id is None); rooms/topics
        # must match the requested scope.
        streams = [
            s
            for s in streams
            if s.get("kind") == "dm" or s.get("project_id") == scope_id
        ]

    recent: list[dict[str, Any]] = []
    active_topics: list[dict[str, Any]] = []

    for s in streams:
        conv_type = _classify_conversation_type(s)
        record = {
            "id": s.get("id"),
            "type": conv_type,
            "title": s.get("name") or s.get("title"),
            "scope_id": s.get("project_id"),
            "last_message_at": s.get("last_message_at"),
            "unread_count": s.get("unread_count", 0),
        }
        # TODO(Phase B.2): real Topic primitives. Today no stream is
        # of type='topic', so active_topics stays empty and the dedup
        # invariant holds trivially.
        if conv_type == "topic":
            topic_status = s.get("topic_status") or "open"
            if topic_status in _ACTIVE_TOPIC_STATUSES:
                record["topic_status"] = topic_status
                active_topics.append(record)
            # Resolved/archived topics fall off both lists (FE shows
            # them only under an explicit "archived" filter).
        else:
            recent.append(record)

    # Enforce dedup invariant defensively. Should be a no-op given the
    # partition above; the assert documents intent for INVARIANT_TESTS
    # §"Topic deduplication".
    recent_ids = {r["id"] for r in recent}
    active_topics = [t for t in active_topics if t["id"] not in recent_ids]

    return {"recent": recent, "active_topics": active_topics}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Fetch a single conversation with initial messages + right_rail slot.

    Per API_CONTRACT.md: "GET /api/conversations/:conversationId should
    include initial `right_rail`." For Phase B.1 we return
    `right_rail: null` so the contract shape registers; Phase B.2
    populates it from the RightRail surface stub.
    """
    service = _service(request)
    result = await service.list_messages(
        stream_id=conversation_id, viewer_id=user.id, limit=limit
    )
    if not result.get("ok"):
        err = result.get("error", "list_failed")
        if err == "stream_not_found":
            raise HTTPException(status_code=404, detail=err)
        if err == "not_a_member":
            raise HTTPException(status_code=403, detail=err)
        raise HTTPException(status_code=400, detail=err)

    return {
        "id": conversation_id,
        "messages": result["messages"],
        # TODO(Phase B.2): populate from RightRailService.for_surface(
        #   surface='conversation', object_id=conversation_id, viewer=user.id
        # ). For B.1 we return null so the contract slot is registered
        # without coupling B.1 to the B.2 right-rail wire-up.
        "right_rail": None,
    }


@router.post("/conversations/{conversation_id}/messages")
async def post_conversation_message(
    conversation_id: str,
    body: ConversationMessageRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Post a message in a conversation. Wraps StreamService.post_message."""
    service = _service(request)
    result = await service.post_message(
        stream_id=conversation_id, author_id=user.id, body=body.body
    )
    if not result.get("ok"):
        err = result.get("error", "post_failed")
        status_map = {
            "stream_not_found": 404,
            "not_a_member": 403,
        }
        raise HTTPException(status_code=status_map.get(err, 400), detail=err)
    return result


# ---- topics endpoints (B.1 stubs) ----------------------------------------


@router.post("/topics")
async def post_create_topic(
    body: CreateTopicRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Create a Topic. Phase B.1 stub.

    TODO(Phase B.2): real TopicRow primitive + StreamService
    .create_topic(scope_id, seed_message_ids, title). For B.1 we
    return the contract shape with a fresh topic_id so the FE flow
    integrates against the wire contract.
    """
    # Membership gate — the service layer will repeat this, but the
    # thin router runs the cheap check first.
    proj_service = request.app.state.project_service
    if not await proj_service.is_member(
        project_id=body.scope_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not_a_scope_member")

    # TODO(Phase B.2): persist a TopicRow via StreamService.create_topic.
    # For B.1 we return a stable placeholder id so the FE can wire its
    # navigation. The id is not persisted — calling GET on it 404s.
    now = datetime.now(timezone.utc).isoformat()
    return {
        "topic": {
            "id": f"topic_stub_{user.id}_{int(datetime.now(timezone.utc).timestamp())}",
            "type": "topic",
            "title": body.title,
            "scope_id": body.scope_id,
            "topic_status": "open",
            "source_conversation_id": body.source_conversation_id,
            "seed_message_ids": list(body.seed_message_ids),
            "created_at": now,
            "_stub": "Phase B.2 persists TopicRow",
        }
    }


@router.patch("/topics/{topic_id}/status")
async def patch_topic_status(
    topic_id: str,
    body: UpdateTopicStatusRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Change a Topic's TopicStatus. Phase B.1 stub.

    Allowed transitions are enforced by the service layer in B.2;
    for B.1 the router only validates the target value is in the
    TopicStatus enum.
    """
    if body.status not in _VALID_TOPIC_STATUSES:
        raise HTTPException(status_code=400, detail="invalid_topic_status")
    # TODO(Phase B.2): TopicService.set_status(topic_id, body.status,
    #   actor_user_id=user.id) — with authority + transition validation.
    return {
        "topic_id": topic_id,
        "status": body.status,
        "_stub": "Phase B.2 wires TopicService.set_status",
    }


@router.post("/topics/{topic_id}/propose-closure")
async def post_propose_topic_closure(
    topic_id: str,
    body: ProposeTopicClosureRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Propose closing a Topic. Returns a proposal envelope only.

    Doctrine: AI proposes, authority accepts. This endpoint never
    mutates state — it produces a `topic_closure` proposal that the
    Memory Candidate / authority pattern processes through
    `/api/proposals/{id}/accept`.

    INVARIANT_TESTS.md §"AI Assistance no-mutation" — the same
    `mutates_state: false` contract applies here because closure is a
    semantic mutation gated by authority.
    """
    # TODO(Phase B.2): generate a real Proposal row of type
    # 'topic_closure', persisted so the generic /api/proposals
    # accept/dismiss/mark-stale endpoints can resolve it.
    now = datetime.now(timezone.utc).isoformat()
    return {
        "proposal": {
            "id": f"prop_topic_closure_{topic_id}_{int(datetime.now(timezone.utc).timestamp())}",
            "type": "topic_closure",
            "target_object_id": topic_id,
            "proposed_by": user.id,
            "rationale": body.rationale,
            "created_at": now,
            "_stub": "Phase B.2 persists Proposal row + lineage",
        },
        "mutates_state": False,
    }
