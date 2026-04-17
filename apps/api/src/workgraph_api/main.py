from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from workgraph_observability import (
    bind_trace_id,
    configure_logging,
    new_trace_id,
)
from workgraph_schemas import ApiError, ApiErrorCode

from workgraph_api.settings import load_settings

settings = load_settings()
configure_logging(settings.log_level)
_log = logging.getLogger("workgraph.api")

app = FastAPI(title="WorkGraph API", version="0.1.0")


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or new_trace_id()
    bind_trace_id(trace_id)
    try:
        response = await call_next(request)
    finally:
        # Expose the trace id so clients can correlate.
        pass
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
