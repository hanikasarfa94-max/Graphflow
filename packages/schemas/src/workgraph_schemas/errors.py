from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiErrorCode(str, Enum):
    internal = "internal_error"
    validation = "validation_error"
    not_found = "not_found"
    conflict = "conflict"
    unauthorized = "unauthorized"
    rate_limited = "rate_limited"
    upstream = "upstream_error"
    schema_fail = "schema_fail"
    manual_review = "manual_review"


class ApiError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ApiErrorCode
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
