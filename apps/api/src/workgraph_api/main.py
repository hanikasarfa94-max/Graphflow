from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from workgraph_agents import (
    ConflictExplanationAgent,
    DeliveryAgent,
    DriftAgent,
    EdgeAgent,
    EdgeResponse,
    EdgeResponseOutcome,
    IMAssistAgent,
    MembraneAgent,
    RenderAgent,
)
from workgraph_agents.llm import LLMResult
from workgraph_agents.testing import (
    StubClarificationAgent,
    StubConflictExplanationAgent,
    StubDeliveryAgent,
    StubIMAssistAgent,
    StubPlanningAgent,
    StubRequirementAgent,
)
from workgraph_domain import EventBus
from workgraph_observability import (
    bind_trace_id,
    configure_logging,
    new_trace_id,
)
from workgraph_persistence import (
    backfill_streams_from_projects,
    build_engine,
    build_sessionmaker,
    create_all,
)
from workgraph_schemas import ApiError, ApiErrorCode

from workgraph_api.routers import auth as auth_router
from workgraph_api.routers import clarification as clarification_router
from workgraph_api.routers import collab as collab_router
from workgraph_api.routers import commitments as commitments_router
from workgraph_api.routers import conflicts as conflicts_router
from workgraph_api.routers import delivery as delivery_router
from workgraph_api.routers import demo as demo_router
from workgraph_api.routers import drift as drift_router
from workgraph_api.routers import events_stream as events_router
from workgraph_api.routers import graph as graph_router
from workgraph_api.routers import intake as intake_router
from workgraph_api.routers import kb as kb_router
from workgraph_api.routers import membrane as membrane_router
from workgraph_api.routers import observability as observability_router
from workgraph_api.routers import personal as personal_router
from workgraph_api.routers import plan as plan_router
from workgraph_api.routers import projects as projects_router
from workgraph_api.routers import render as render_router
from workgraph_api.routers import routing as routing_router
from workgraph_api.routers import streams as streams_router
from workgraph_api.routers import users as users_router
from workgraph_api.routers import ws as ws_router
from workgraph_api.services import (
    AssignmentService,
    AuthService,
    ClarificationService,
    CollabHub,
    CommentService,
    CommitmentService,
    ConflictService,
    DecisionService,
    DeliveryService,
    DriftService,
    IMService,
    IntakeService,
    MembraneService,
    MessageService,
    NotificationService,
    PersonalStreamService,
    PlanningService,
    ProjectService,
    RenderService,
    RoutingService,
    SkillsService,
    SlaService,
    StreamService,
)
from workgraph_api.settings import load_settings

settings = load_settings()
configure_logging(settings.log_level)
_log = logging.getLogger("workgraph.api")


class _SilentStubEdgeAgent:
    """Boot-time fallback EdgeAgent used in `use_stubs` mode.

    Returns `kind='silence'` for every user turn so the demo surface
    still works without a DeepSeek key. Tests inject their own stub via
    `app.state.personal_service` — this one is only for the main app
    running with `WORKGRAPH_USE_STUBS=true`.
    """

    async def respond(self, *, user_message, context):  # pragma: no cover - boot wiring
        return EdgeResponseOutcome(
            response=EdgeResponse(kind="silence", body=None, route_targets=[]),
            result=LLMResult(
                content="",
                model="stub",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
            ),
            outcome="ok",
            attempts=1,
        )

    async def generate_options(self, *, routing_context):  # pragma: no cover
        raise NotImplementedError(
            "stub edge agent: generate_options unused in stub boot mode"
        )

    async def frame_reply(self, *, signal, source_user_context):  # pragma: no cover
        raise NotImplementedError(
            "stub edge agent: frame_reply unused in stub boot mode"
        )


class _SilentStubMembraneAgent:
    """Boot-time fallback MembraneAgent used in `use_stubs` mode.

    Defaults to `flag-for-review` so stub-mode boots NEVER auto-route
    external content. Per vision §5.12 the safe-default for the membrane
    is to defer to a human. Tests inject their own stub by overriding
    `app.state.membrane_service`.
    """

    prompt_version = "stub.membrane.v1"

    async def classify(  # pragma: no cover - boot wiring
        self,
        *,
        raw_content,
        source_kind,
        source_identifier,
        project_context,
    ):
        from workgraph_agents.membrane import (
            MembraneClassification,
            MembraneOutcome,
        )

        return MembraneOutcome(
            classification=MembraneClassification(
                is_relevant=False,
                tags=[],
                summary="stub membrane — awaiting human review",
                proposed_target_user_ids=[],
                proposed_action="flag-for-review",
                confidence=0.0,
                safety_notes="",
            ),
            result=LLMResult(
                content="",
                model="stub",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
            ),
            outcome="ok",
            attempts=1,
        )


class _SilentStubRenderAgent:
    """Boot-time fallback RenderAgent used in `use_stubs` mode.

    Returns minimal manual-review-shape docs without hitting a real LLM.
    Tests inject their own stub via `app.state.render_service` when they
    need to drive the agent directly.
    """

    postmortem_prompt_version = "stub.render.v1"
    handoff_prompt_version = "stub.render.v1"

    async def render_postmortem(self, project_context):  # pragma: no cover
        from workgraph_agents.render import (
            PostmortemDoc,
            PostmortemOutcome,
            RenderedSection,
        )

        project = project_context.get("project") or {}
        title = project.get("title") or "Project"
        return PostmortemOutcome(
            doc=PostmortemDoc(
                title=f"{title} postmortem (stub)",
                one_line_summary="Stub render — enable a real LLM for narrative text.",
                sections=[
                    RenderedSection(
                        heading="What happened",
                        body_markdown="(stub) Render agent offline.",
                    ),
                    RenderedSection(
                        heading="Key decisions (lineage)",
                        body_markdown="(stub) — see /status for the live list.",
                    ),
                    RenderedSection(
                        heading="What we got right", body_markdown="(stub)"
                    ),
                    RenderedSection(
                        heading="What drifted", body_markdown="(stub)"
                    ),
                    RenderedSection(heading="Lessons", body_markdown="(stub)"),
                ],
            ),
            result=LLMResult(
                content="",
                model="stub",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
            ),
            outcome="ok",
            attempts=1,
        )

    async def render_handoff(self, departing_user_context):  # pragma: no cover
        from workgraph_agents.render import (
            HandoffDoc,
            HandoffOutcome,
            RenderedSection,
        )

        user = departing_user_context.get("user") or {}
        project = departing_user_context.get("project") or {}
        name = user.get("display_name") or user.get("username") or "Teammate"
        return HandoffOutcome(
            doc=HandoffDoc(
                title=f"{name}'s handoff — {project.get('title') or 'Project'} (stub)",
                sections=[
                    RenderedSection(
                        heading="Role summary",
                        body_markdown=f"(stub) {name}'s role summary.",
                    ),
                    RenderedSection(
                        heading="Active tasks I own", body_markdown="(stub)"
                    ),
                    RenderedSection(
                        heading="Recurring decisions I make", body_markdown="(stub)"
                    ),
                    RenderedSection(
                        heading="Key relationships", body_markdown="(stub)"
                    ),
                    RenderedSection(
                        heading="Open items / pending routings",
                        body_markdown="(stub)",
                    ),
                    RenderedSection(
                        heading="Style notes (how I reply to common asks)",
                        body_markdown="(stub)",
                    ),
                ],
            ),
            result=LLMResult(
                content="",
                model="stub",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
            ),
            outcome="ok",
            attempts=1,
        )


class _SilentStubDriftAgent:
    """Boot-time fallback DriftAgent used in `use_stubs` mode.

    Returns `has_drift=false` for every check so the demo surface runs
    without a DeepSeek key. Tests inject their own stub by overriding
    `app.state.drift_service`.
    """

    prompt_version = "stub.drift.v1"

    async def check(self, context):  # pragma: no cover - boot wiring
        from workgraph_agents.drift import DriftCheckOutcome, DriftCheckResult

        return DriftCheckOutcome(
            result_payload=DriftCheckResult(
                has_drift=False, drift_items=[], reasoning="stub drift agent"
            ),
            result=LLMResult(
                content="",
                model="stub",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
            ),
            outcome="ok",
            attempts=1,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.database_url.startswith("sqlite"):
        _ensure_sqlite_parent(settings.database_url)

    engine = build_engine(settings.database_url)
    await create_all(engine)
    sessionmaker = build_sessionmaker(engine)
    event_bus = EventBus(sessionmaker)

    # Phase B: sync stream primitive with existing ProjectRow / members.
    # Idempotent — safe to run every boot. Dev SQLite recreates, so this is
    # usually a no-op; on a seeded DB it populates streams for existing
    # projects and links messages by project_id.
    backfill_stats = await backfill_streams_from_projects(sessionmaker)
    _log.info("stream backfill complete", extra=backfill_stats)

    collab_hub = CollabHub(redis_url=settings.redis_url)
    await collab_hub.start()

    auth_service = AuthService(sessionmaker, event_bus)
    project_service = ProjectService(sessionmaker, event_bus)
    notification_service = NotificationService(sessionmaker, event_bus, collab_hub)
    assignment_service = AssignmentService(
        sessionmaker, event_bus, collab_hub, notification_service
    )
    comment_service = CommentService(
        sessionmaker, event_bus, collab_hub, notification_service
    )
    message_service = MessageService(
        sessionmaker, event_bus, collab_hub, notification_service
    )
    if settings.use_stubs:
        _log.info("WORKGRAPH_USE_STUBS=true — every LLM agent is a stub")
        requirement_agent = StubRequirementAgent()
        clarification_agent = StubClarificationAgent()
        planning_agent = StubPlanningAgent()
        im_agent = StubIMAssistAgent()
        conflict_agent = StubConflictExplanationAgent()
        delivery_agent = StubDeliveryAgent()
        drift_agent = _SilentStubDriftAgent()
        membrane_agent = _SilentStubMembraneAgent()
        render_agent = _SilentStubRenderAgent()
    else:
        requirement_agent = None  # service-level default (RequirementAgent)
        clarification_agent = None
        planning_agent = None
        im_agent = IMAssistAgent()
        conflict_agent = ConflictExplanationAgent()
        delivery_agent = DeliveryAgent()
        drift_agent = DriftAgent()
        membrane_agent = MembraneAgent()
        render_agent = RenderAgent()

    im_service = IMService(
        sessionmaker,
        event_bus,
        collab_hub,
        notification_service,
        message_service,
        im_agent,
    )
    conflict_service = ConflictService(
        sessionmaker,
        event_bus,
        collab_hub,
        conflict_agent,
    )
    decision_service = DecisionService(
        sessionmaker,
        event_bus,
        collab_hub,
        conflict_service,
        assignment_service,
    )
    delivery_service = DeliveryService(
        sessionmaker,
        event_bus,
        collab_hub,
        delivery_agent,
    )
    render_service = RenderService(sessionmaker, render_agent)
    stream_service = StreamService(sessionmaker, event_bus, collab_hub)
    drift_service = DriftService(
        sessionmaker,
        event_bus,
        drift_agent,
        stream_service,
    )
    routing_service = RoutingService(sessionmaker, event_bus, stream_service)
    commitment_service = CommitmentService(sessionmaker, event_bus)
    sla_service = SlaService(sessionmaker, event_bus, stream_service)
    membrane_service = MembraneService(
        sessionmaker,
        event_bus,
        collab_hub,
        stream_service,
        membrane_agent,
    )

    if settings.use_stubs:
        edge_agent = _SilentStubEdgeAgent()
    else:
        edge_agent = EdgeAgent()

    skills_service = SkillsService(sessionmaker)
    personal_service = PersonalStreamService(
        sessionmaker,
        stream_service,
        routing_service,
        edge_agent,
        event_bus,
        skills_service=skills_service,
    )

    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.event_bus = event_bus
    app.state.intake_service = IntakeService(
        sessionmaker,
        event_bus,
        agent=requirement_agent,
        project_service=project_service,
    )
    app.state.clarification_service = ClarificationService(
        sessionmaker,
        event_bus,
        clarification_agent=clarification_agent,
        requirement_agent=requirement_agent,
    )
    app.state.planning_service = PlanningService(
        sessionmaker, event_bus, agent=planning_agent
    )
    app.state.auth_service = auth_service
    app.state.project_service = project_service
    app.state.collab_hub = collab_hub
    app.state.notification_service = notification_service
    app.state.assignment_service = assignment_service
    app.state.comment_service = comment_service
    app.state.message_service = message_service
    app.state.im_service = im_service
    app.state.conflict_service = conflict_service
    app.state.decision_service = decision_service
    app.state.delivery_service = delivery_service
    app.state.render_service = render_service
    app.state.render_agent = render_agent
    app.state.drift_service = drift_service
    app.state.drift_agent = drift_agent
    app.state.stream_service = stream_service
    app.state.routing_service = routing_service
    app.state.edge_agent = edge_agent
    app.state.personal_service = personal_service
    app.state.skills_service = skills_service
    app.state.membrane_service = membrane_service
    app.state.membrane_agent = membrane_agent
    app.state.commitment_service = commitment_service
    app.state.sla_service = sla_service

    # Drift auto-trigger (Sprint 1c). Subscribe drift_service to the
    # event types that most reliably indicate "the project's surface
    # has moved since the last drift check." Rate-limit inside
    # DriftService (60s per project) handles burst protection, so we
    # can subscribe liberally without blowing LLM cost. Fire-and-forget
    # via EventBus.subscribe; bad handlers are swallowed with a log.
    async def _drift_on_event(payload: dict[str, object]) -> None:
        project_id = payload.get("project_id")
        if not isinstance(project_id, str):
            return
        await drift_service.check_project(project_id=project_id)

    event_bus.subscribe("decision.applied", _drift_on_event)
    event_bus.subscribe("delivery.generated", _drift_on_event)

    # SLA auto-trigger (Sprint 2b). Same pattern as drift — sweep a
    # project's open commitments whenever its graph surface moves,
    # plus when a new commitment is created (catches "created with
    # a past target_date"). Per-commitment throttle lives on
    # CommitmentRow.sla_last_escalated_at (see services/sla.py) so
    # bursts of events don't spam owners. commitment.created fires
    # even when there's no target_date — SlaService skips those
    # cheaply.
    async def _sla_on_event(payload: dict[str, object]) -> None:
        project_id = payload.get("project_id")
        if not isinstance(project_id, str):
            return
        await sla_service.check_project(project_id=project_id)

    event_bus.subscribe("decision.applied", _sla_on_event)
    event_bus.subscribe("delivery.generated", _sla_on_event)
    event_bus.subscribe("commitment.created", _sla_on_event)
    event_bus.subscribe("commitment.status_changed", _sla_on_event)

    _log.info("api boot ok", extra={"database_url": _sanitize(settings.database_url)})
    try:
        yield
    finally:
        try:
            await im_service.drain()
        except Exception:
            _log.exception("im drain failed during shutdown")
        try:
            await conflict_service.drain()
        except Exception:
            _log.exception("conflict drain failed during shutdown")
        try:
            await collab_hub.stop()
        except Exception:
            _log.exception("collab hub stop failed during shutdown")
        await engine.dispose()
        _log.info("api shutdown ok")


def _ensure_sqlite_parent(url: str) -> None:
    # sqlite+aiosqlite:///./data/workgraph.sqlite  → ./data/workgraph.sqlite
    _, _, path = url.partition(":///")
    if not path:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _sanitize(url: str) -> str:
    if "@" in url:
        scheme, rest = url.split("://", 1)
        _, host = rest.split("@", 1)
        return f"{scheme}://***@{host}"
    return url


app = FastAPI(title="WorkGraph API", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router.router)
app.include_router(intake_router.router)
app.include_router(kb_router.router)
app.include_router(membrane_router.router)
app.include_router(clarification_router.router)
app.include_router(graph_router.router)
app.include_router(plan_router.router)
app.include_router(projects_router.router)
app.include_router(collab_router.router)
app.include_router(conflicts_router.router)
app.include_router(delivery_router.router)
app.include_router(demo_router.router)
app.include_router(drift_router.router)
app.include_router(commitments_router.router)
app.include_router(events_router.router)
app.include_router(observability_router.router)
app.include_router(personal_router.router)
app.include_router(render_router.router)
app.include_router(routing_router.router)
app.include_router(streams_router.router)
app.include_router(users_router.router)
app.include_router(ws_router.router)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or new_trace_id()
    bind_trace_id(trace_id)
    response = await call_next(request)
    response.headers["x-trace-id"] = trace_id
    return response


def _error_response(
    code: ApiErrorCode,
    message: str,
    status_code: int,
    details: dict | None = None,
) -> JSONResponse:
    from workgraph_observability import get_trace_id

    body = ApiError(
        code=code,
        message=message,
        details=details or {},
        trace_id=get_trace_id(),
    ).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=body)


@app.exception_handler(RequestValidationError)
async def _validation_handler(_: Request, exc: RequestValidationError):
    return _error_response(
        ApiErrorCode.validation,
        "request validation failed",
        status_code=422,
        details={"errors": exc.errors()},
    )


@app.exception_handler(StarletteHTTPException)
async def _http_handler(_: Request, exc: StarletteHTTPException):
    code = {
        401: ApiErrorCode.unauthorized,
        404: ApiErrorCode.not_found,
        409: ApiErrorCode.conflict,
        429: ApiErrorCode.rate_limited,
    }.get(exc.status_code, ApiErrorCode.internal)
    return _error_response(code, str(exc.detail), status_code=exc.status_code)


@app.exception_handler(Exception)
async def _unhandled_handler(_: Request, exc: Exception):
    _log.exception("unhandled exception")
    return _error_response(
        ApiErrorCode.internal,
        "internal server error",
        status_code=500,
        details={"type": type(exc).__name__},
    )


@app.get("/health")
async def health() -> dict:
    # Phase 7' fault-injection test reads `sse_streams` to verify the
    # SSE connection counter decrements on client disconnect.
    from workgraph_api.routers.events_stream import ACTIVE_STREAMS
    from workgraph_api.routers.ws import ACTIVE_STREAM_WS, ACTIVE_WS

    return {
        "status": "ok",
        "env": settings.env,
        "sse_streams": ACTIVE_STREAMS["count"],
        "ws_streams": ACTIVE_WS["count"],
        "ws_stream_channels": ACTIVE_STREAM_WS["count"],
    }


@app.get("/_debug/boom")
async def _debug_boom() -> None:
    """Deliberately raise an unhandled error — used by Phase 1 validation."""
    raise RuntimeError("intentional boom for ApiError verification")
