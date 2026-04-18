from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Project(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: str
    title: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime


class Requirement(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: str
    project_id: str
    version: int = 1
    raw_text: str = Field(min_length=1)
    parsed_json: dict | None = None
    parse_outcome: str | None = None
    parsed_at: datetime | None = None
    created_at: datetime


class ClarificationQuestion(BaseModel):
    """One outstanding clarification attached to a requirement version.

    `answer` is null until the user replies. The Clarification stage ends
    when every question attached to the latest requirement has an answer
    (see workgraph_persistence.stage.project_stage — decision 1E).
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: str
    requirement_id: str
    position: int
    question: str = Field(min_length=1)
    answer: str | None = None
    answered_at: datetime | None = None
    created_at: datetime


class IntakeResult(BaseModel):
    """Return value for both API and Feishu intake paths.

    Identical shape enforces the "API path and Feishu path produce the same
    domain result" acceptance criterion.
    """

    model_config = ConfigDict(extra="forbid")

    project: Project
    requirement: Requirement
    source: str
    source_event_id: str
    deduplicated: bool = False
