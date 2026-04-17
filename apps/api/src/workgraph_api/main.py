from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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

from workgraph_api.routers import intake as intake_router
from workgraph_api.services import IntakeService
from workgraph_api.settings import load_settings

settings = load_settings()
configure_logging(settings.log_level)
_log = logging.getLogger("workgraph.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the sqlite data directory exists before the engine opens a file handle.
    if settings.database_url.startswith("sqlite"):
        _ensure_sqlite_parent(settings.database_url)

    engine = build_engine(settings.database_url)
    await create_all(engine)
    sessionmaker = build_sessionmaker(engine)
    event_bus = EventBus(sessionmaker)

    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.event_bus = event_bus
    app.state.intake_service = IntakeService(sessionmaker, event_bus)
    _log.info("api boot ok", extra={"database_url": _sanitize(settings.database_url)})
    try:
        yield
    finally:
        await engine.dispose()
        _log.info("api shutdown ok")


def _ensure_sqlite_parent(url: str) -> None:
    # sqlite+aiosqlite:///./data/workgraph.sqlite  → ./data/workgraph.sqlite
    _, _, path = url.partition(":///")
    if not path:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _sanitize(url: str) -> str:
    # Strip credentials for log visibility.
    if "@" in url:
        scheme, rest = url.split("://", 1)
        _, host = rest.split("@", 1)
        return f"{scheme}://***@{host}"
    return url


app = FastAPI(title="WorkGraph API", version="0.1.0", lifespan=lifespan)
app.include_router(intake_router.router)


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
async def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.env}


@app.get("/_debug/boom")
async def _debug_boom() -> None:
    """Deliberately raise an unhandled error — used by Phase 1 validation."""
    raise RuntimeError("intentional boom for ApiError verification")
