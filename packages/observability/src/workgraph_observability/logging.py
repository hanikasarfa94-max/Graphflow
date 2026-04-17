from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar

_trace_id_var: ContextVar[str | None] = ContextVar("workgraph_trace_id", default=None)


def new_trace_id() -> str:
    return uuid.uuid4().hex


def bind_trace_id(trace_id: str | None) -> None:
    _trace_id_var.set(trace_id)


def get_trace_id() -> str | None:
    return _trace_id_var.get()


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        trace_id = get_trace_id()
        if trace_id:
            payload["trace_id"] = trace_id
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k
            not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "taskName",
            }
        }
        if extras:
            payload["extra"] = extras
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    # Remove prior handlers so reconfigure is idempotent.
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
