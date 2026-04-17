from __future__ import annotations

from fastapi import Request

from workgraph_api.services import IntakeService


def get_intake_service(request: Request) -> IntakeService:
    return request.app.state.intake_service
