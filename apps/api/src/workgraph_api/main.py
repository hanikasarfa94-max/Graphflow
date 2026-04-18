from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from workgraph_agents import ConflictExplanationAgent, DeliveryAgent, IMAssistAgent
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
    build_engine,
    build_sessionmaker,
    create_all,
)
from workgraph_schemas import ApiError, ApiErrorCode

from workgraph_api.routers import auth as auth_router
from workgraph_api.routers import clarification as clarification_router
from workgraph_api.routers import collab as collab_router
from workgraph_api.routers import conflicts as conflicts_router
from workgraph_api.routers import delivery as delivery_router
from workgraph_api.routers import demo as demo_router
from workgraph_api.routers import events_stream as events_router
from workgraph_api.routers import graph as graph_router
from workgraph_api.routers import intake as intake_router
from workgraph_api.routers import observability as observability_router
from workgraph_api.routers import plan as plan_router
from workgraph_api.routers import projects as projects_router
from workgraph_api.routers import ws as ws_router
from workgraph_api.services import (
    AssignmentService,
    AuthService,
    ClarificationService,
    CollabHub,
    CommentService,
    ConflictService,
    DecisionService,
    DeliveryService,
    IMService,
    IntakeService,
    MessageService,
    NotificationService,
    PlanningService,
    ProjectService,
)
from workgraph_api.settings import load_settings

settings = load_settings()
configure_logging(settings.log_level)
_log = logging.getLogger("workgraph.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.database_url.startswith("sqlite"):
        _ensure_sqlite_parent(settings.database_url)

    engine = build_engine(settings.database_url)
    await create_all(engine)
    sessionmaker = build_sessionmaker(engine)
    event_bus = EventBus(sessionmaker)

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
    else:
        requirement_agent = None  # service-level default (RequirementAgent)
        clarification_agent = None
        planning_agent = None
        im_agent = IMAssistAgent()
        conflict_agent = ConflictExplanationAgent()
        delivery_agent = DeliveryAgent()

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
app.include_router(clarification_router.router)
app.include_router(graph_router.router)
app.include_router(plan_router.router)
app.include_router(projects_router.router)
app.include_router(collab_router.router)
app.include_router(conflicts_router.router)
app.include_router(delivery_router.router)
app.include_router(demo_router.router)
app.include_router(events_router.router)
app.include_router(observability_router.router)
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
    from workgraph_api.routers.ws import ACTIVE_WS

    return {
        "status": "ok",
        "env": settings.env,
        "sse_streams": ACTIVE_STREAMS["count"],
        "ws_streams": ACTIVE_WS["count"],
    }


@app.get("/_debug/boom")
async def _debug_boom() -> None:
    """Deliberately raise an unhandled error — used by Phase 1 validation."""
    raise RuntimeError("intentional boom for ApiError verification")
