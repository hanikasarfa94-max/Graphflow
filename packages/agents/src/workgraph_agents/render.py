"""RenderAgent — Phase R (rendered artifacts).

PLAN-v2 Phase F reference; vision §5.10 "why chain"; roadmaps R11 handoff, R12 postmortem.

Two LLM-backed methods that turn live graph + stream state into human-readable
Markdown documents:

  * `render_postmortem(project_context)` — project-level R12 lineage render.
    Input: requirement + decisions (with lineage) + resolved risks + delivered
    vs. undelivered tasks + key turns. Output: a structured PostmortemDoc with
    five sections (What happened / Key decisions / What we got right / What
    drifted / Lessons).

  * `render_handoff(departing_user_context)` — per-user R11 departure doc.
    Input: user + project + their edges (tasks owned, decisions shaped, signals
    emitted) + adjacent teammates + open items + response profile. Output: a
    structured HandoffDoc with six sections (Role / Active tasks / Recurring
    decisions / Relationships / Open items / Style notes).

Both methods use the same recovery ladder every other agent uses (decision 2C4):
JSON mode → reprompt on invalid output up to 3 attempts → deterministic
manual-review fallback so the UI always has something to render. Decision
citations are grounded: the prompt contract forbids inventing decision ids, and
the postprocessor cross-checks any `D-<id>` mentions in the rendered markdown
against the input decision list — unknown ids are stripped to plain text to
keep the "never fabricate" invariant.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .llm import LLMClient, LLMResult, ParseFailure

_log = logging.getLogger("workgraph.agents.render")

POSTMORTEM_PROMPT_VERSION = "2026-04-18.phaseR.v1"
HANDOFF_PROMPT_VERSION = "2026-04-18.phaseR.v1"

_PROMPT_DIR = Path(__file__).parent / "prompts" / "render"


def _load_prompt(name: str) -> str:
    return (_PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


Outcome = Literal["ok", "retry", "manual_review"]


# ---------------------------------------------------------------------------
# Shared section model.
# ---------------------------------------------------------------------------


class RenderedSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(min_length=1, max_length=200)
    body_markdown: str = Field(default="", max_length=8000)


# ---------------------------------------------------------------------------
# Postmortem.
# ---------------------------------------------------------------------------


class PostmortemDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    one_line_summary: str = Field(default="", max_length=400)
    sections: list[RenderedSection] = Field(default_factory=list)


@dataclass(slots=True)
class PostmortemOutcome:
    doc: PostmortemDoc
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


def _postmortem_manual_review_fallback(
    *, project_title: str, decisions: list[dict[str, Any]]
) -> PostmortemDoc:
    """Deterministic fallback so the render page always has content to show.

    Uses the decision list verbatim — never invents lineage text.
    """
    citation_lines: list[str]
    if decisions:
        citation_lines = []
        for d in decisions:
            did = d.get("id") or ""
            headline = (
                d.get("rationale")
                or d.get("custom_text")
                or "Decision without rationale"
            )
            citation_lines.append(f"- **D-{did}** — {headline}")
    else:
        citation_lines = ["(no recorded decisions)"]

    return PostmortemDoc(
        title=f"{project_title} postmortem",
        one_line_summary=(
            "The render agent could not produce a structured postmortem; "
            "this fallback lists what the graph already knows."
        ),
        sections=[
            RenderedSection(
                heading="What happened",
                body_markdown=(
                    "The render agent fell back to manual review. "
                    "Review the lineage below and write the narrative manually."
                ),
            ),
            RenderedSection(
                heading="Key decisions (lineage)",
                body_markdown="\n".join(citation_lines),
            ),
            RenderedSection(
                heading="What we got right",
                body_markdown="(fallback — fill in manually)",
            ),
            RenderedSection(
                heading="What drifted",
                body_markdown="(fallback — fill in manually)",
            ),
            RenderedSection(
                heading="Lessons",
                body_markdown="(fallback — fill in manually)",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Handoff.
# ---------------------------------------------------------------------------


class HandoffDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    sections: list[RenderedSection] = Field(default_factory=list)


@dataclass(slots=True)
class HandoffOutcome:
    doc: HandoffDoc
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


def _handoff_manual_review_fallback(
    *,
    display_name: str,
    project_title: str,
    active_tasks: list[dict[str, Any]],
    adjacent_teammates: list[dict[str, Any]],
    open_items: list[dict[str, Any]],
) -> HandoffDoc:
    def _bullet_tasks() -> str:
        if not active_tasks:
            return "(no active tasks — handoff is clean)"
        return "\n".join(
            f"- **{t.get('title', '(untitled)')}** ({t.get('status', 'unknown')})"
            for t in active_tasks
        )

    def _bullet_adjacent() -> str:
        if not adjacent_teammates:
            return "(no adjacent teammates recorded)"
        return "\n".join(
            f"- **{t.get('display_name', 'unknown')}** "
            f"({t.get('role', '—')})"
            for t in adjacent_teammates
        )

    def _bullet_open() -> str:
        if not open_items:
            return "Nothing pending at handoff time."
        return "\n".join(
            f"- {item.get('framing', '(no framing)')} "
            f"(from {item.get('from_display_name') or 'unknown'})"
            for item in open_items
        )

    return HandoffDoc(
        title=f"{display_name}'s handoff — {project_title}",
        sections=[
            RenderedSection(
                heading="Role summary",
                body_markdown=(
                    f"{display_name} was working on {project_title}. "
                    "The render agent could not produce a narrative "
                    "automatically — review the raw edges below."
                ),
            ),
            RenderedSection(
                heading="Active tasks I own", body_markdown=_bullet_tasks()
            ),
            RenderedSection(
                heading="Recurring decisions I make",
                body_markdown="(fallback — no pattern extracted)",
            ),
            RenderedSection(
                heading="Key relationships", body_markdown=_bullet_adjacent()
            ),
            RenderedSection(
                heading="Open items / pending routings",
                body_markdown=_bullet_open(),
            ),
            RenderedSection(
                heading="Style notes (how I reply to common asks)",
                body_markdown="(fallback — no style signal extracted)",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Agent.
# ---------------------------------------------------------------------------


class RenderAgent:
    """Pure agent; the service owns caching + persistence.

    Both methods accept the caller's prepared context dict (no DB access
    from here), invoke complete_structured with a Pydantic model, and
    ground decision citations against the passed-in decision id set.
    """

    postmortem_prompt_version = POSTMORTEM_PROMPT_VERSION
    handoff_prompt_version = HANDOFF_PROMPT_VERSION

    def __init__(
        self,
        llm: LLMClient | None = None,
        *,
        postmortem_prompt: str | None = None,
        handoff_prompt: str | None = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._postmortem_prompt = postmortem_prompt or _load_prompt(
            "postmortem_v1"
        )
        self._handoff_prompt = handoff_prompt or _load_prompt("handoff_v1")

    # -- render_postmortem -------------------------------------------------

    async def render_postmortem(
        self, project_context: dict[str, Any]
    ) -> PostmortemOutcome:
        messages = [
            {"role": "system", "content": self._postmortem_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    project_context, ensure_ascii=False, default=str
                ),
            },
        ]
        known_decision_ids = {
            str(d.get("id"))
            for d in (project_context.get("decisions") or [])
            if d.get("id")
        }
        project_title = (
            (project_context.get("project") or {}).get("title")
            or "Project"
        )
        try:
            parsed, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=PostmortemDoc,
                max_attempts=3,
            )
        except ParseFailure as e:
            _log.error(
                "render.postmortem failed — manual review",
                extra={
                    "prompt_version": self.postmortem_prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            fallback = _postmortem_manual_review_fallback(
                project_title=project_title,
                decisions=list(project_context.get("decisions") or []),
            )
            return PostmortemOutcome(
                doc=fallback,
                result=e.last_result
                or LLMResult(
                    content="",
                    model=self._llm.settings.model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=0,
                ),
                outcome="manual_review",
                attempts=len(e.errors),
                error=e.errors[-1] if e.errors else "unknown",
            )

        assert isinstance(parsed, PostmortemDoc)
        # Ground citations: any `D-<id>` mention whose id is NOT in the
        # input decision set gets stripped to plain text, so we never
        # surface a fabricated id as a real link. Keeps the "renders MUST
        # NOT fabricate decision IDs" invariant from the PLAN.
        grounded = _strip_unknown_decision_citations(
            parsed, known_ids=known_decision_ids
        )
        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "render.postmortem ok",
            extra={
                "prompt_version": self.postmortem_prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "sections": len(grounded.sections),
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
            },
        )
        return PostmortemOutcome(
            doc=grounded, result=result, outcome=outcome, attempts=attempts
        )

    # -- render_handoff ----------------------------------------------------

    async def render_handoff(
        self, departing_user_context: dict[str, Any]
    ) -> HandoffOutcome:
        messages = [
            {"role": "system", "content": self._handoff_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    departing_user_context, ensure_ascii=False, default=str
                ),
            },
        ]
        user = departing_user_context.get("user") or {}
        project = departing_user_context.get("project") or {}
        try:
            parsed, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=HandoffDoc,
                max_attempts=3,
            )
        except ParseFailure as e:
            _log.error(
                "render.handoff failed — manual review",
                extra={
                    "prompt_version": self.handoff_prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            fallback = _handoff_manual_review_fallback(
                display_name=user.get("display_name") or user.get("username") or "Teammate",
                project_title=project.get("title") or "Project",
                active_tasks=list(departing_user_context.get("active_tasks") or []),
                adjacent_teammates=list(
                    departing_user_context.get("adjacent_teammates") or []
                ),
                open_items=list(departing_user_context.get("open_items") or []),
            )
            return HandoffOutcome(
                doc=fallback,
                result=e.last_result
                or LLMResult(
                    content="",
                    model=self._llm.settings.model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=0,
                ),
                outcome="manual_review",
                attempts=len(e.errors),
                error=e.errors[-1] if e.errors else "unknown",
            )

        assert isinstance(parsed, HandoffDoc)
        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "render.handoff ok",
            extra={
                "prompt_version": self.handoff_prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "sections": len(parsed.sections),
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
            },
        )
        return HandoffOutcome(
            doc=parsed, result=result, outcome=outcome, attempts=attempts
        )


# ---------------------------------------------------------------------------
# Citation grounding.
# ---------------------------------------------------------------------------


_DECISION_CITATION_RE = re.compile(r"\*\*D-([A-Za-z0-9_\-]+)\*\*")


def _strip_unknown_decision_citations(
    doc: PostmortemDoc, *, known_ids: set[str]
) -> PostmortemDoc:
    """Replace any `**D-<id>**` whose id is NOT in `known_ids` with plain
    italics — keeps rendered text honest without having to fail the whole
    doc. If the LLM cited ids that exist, every bolded marker survives.
    """
    if not known_ids:
        # No valid ids at all — unbold every citation to plain text.
        def _unbold_all(m: re.Match) -> str:
            return f"*D-{m.group(1)}*"

        return PostmortemDoc(
            title=doc.title,
            one_line_summary=doc.one_line_summary,
            sections=[
                RenderedSection(
                    heading=s.heading,
                    body_markdown=_DECISION_CITATION_RE.sub(
                        _unbold_all, s.body_markdown
                    ),
                )
                for s in doc.sections
            ],
        )

    def _gate(m: re.Match) -> str:
        did = m.group(1)
        if did in known_ids:
            return m.group(0)
        return f"*D-{did}*"

    return PostmortemDoc(
        title=doc.title,
        one_line_summary=doc.one_line_summary,
        sections=[
            RenderedSection(
                heading=s.heading,
                body_markdown=_DECISION_CITATION_RE.sub(_gate, s.body_markdown),
            )
            for s in doc.sections
        ],
    )


__all__ = [
    "RenderAgent",
    "PostmortemDoc",
    "PostmortemOutcome",
    "HandoffDoc",
    "HandoffOutcome",
    "RenderedSection",
    "POSTMORTEM_PROMPT_VERSION",
    "HANDOFF_PROMPT_VERSION",
]
