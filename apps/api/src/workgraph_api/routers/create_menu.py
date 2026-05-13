"""Phase B.1 — v0.6.2 Create Menu (API_CONTRACT §"Create Menu").

Doctrine documentation in API form. The Create menu only ever offers
blank-start creation for four object kinds:

    conversation, document, upload, project_scope

Tasks, topics, flow_requests, and memory are CONTEXT-BORN — they exist
because something happened (a message arrived, a flow closed, a
decision crystallized). Offering a blank "+ New task" affordance
would invite the user to fabricate work without context, which is the
exact failure mode v0.6.2 was designed to prevent.

INVARIANT_TESTS.md §"Create menu invariant" asserts exact ordering of
items and exact membership of the excluded list. Both are hardcoded
below; no service call required.

Endpoint:

  * GET /api/create-menu

Labels: English defaults for B.1. The FE re-renders via i18n keys
`shellV062.createMenu.*` (see FRONTEND_IMPLEMENTATION.md §"Create
menu"). Server-side i18n hook can replace `_labels_for_user()` once
that pattern lands.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser

router = APIRouter(tags=["create-menu"])


# ---- locked shape (INVARIANT_TESTS.md §"Create menu invariant") ----------

# The contract test asserts items.map(i => i.type) === this exact list,
# in this exact order. Reordering, adding, or removing entries here
# breaks the contract.
_CREATE_MENU_TYPES: list[str] = [
    "conversation",
    "document",
    "upload",
    "project_scope",
]

# The exclusion list documents the doctrine: these object kinds may
# only be created from context, never blank-start. The contract test
# asserts equality (not subset) on this list.
_EXCLUDED_DIRECT_CREATIONS: list[str] = [
    "task",
    "topic",
    "flow_request",
    "memory",
]

# English labels — keys map to FE shellV062.createMenu.* i18n strings.
_DEFAULT_LABELS: dict[str, str] = {
    "conversation": "New conversation",
    "document": "New document",
    "upload": "Upload",
    "project_scope": "New project scope",
}


# ---- response shape ------------------------------------------------------


CreateMenuType = Literal["conversation", "document", "upload", "project_scope"]


class CreateMenuItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: CreateMenuType
    label: str


class CreateMenuResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CreateMenuItem]
    # Document doctrine in the wire shape. FE renders this as a
    # tooltip / help affordance ("Tasks, topics, flow requests, and
    # memory are created from context"). Contract test asserts exact
    # equality with `_EXCLUDED_DIRECT_CREATIONS`.
    excluded_direct_creations: list[str]


# ---- endpoint ------------------------------------------------------------


@router.get("/api/create-menu", response_model=CreateMenuResponse)
async def get_create_menu(
    user: AuthenticatedUser = Depends(require_user),
) -> CreateMenuResponse:
    """Return the locked Create Menu allow / exclude list.

    Hardcoded — no service call. The shape is the contract; see
    INVARIANT_TESTS.md §"Create menu invariant" for the exact
    assertions. Auth is required so the endpoint isn't usable as a
    doctrine probe by unauthenticated clients, not because the
    response depends on the caller.
    """
    items = [
        CreateMenuItem(type=t, label=_DEFAULT_LABELS[t])  # type: ignore[arg-type]
        for t in _CREATE_MENU_TYPES
    ]
    return CreateMenuResponse(
        items=items,
        excluded_direct_creations=list(_EXCLUDED_DIRECT_CREATIONS),
    )
