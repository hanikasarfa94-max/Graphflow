from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from workgraph_agents import EdgeResponse, EdgeResponseOutcome
from workgraph_agents.drift import DriftCheckOutcome, DriftCheckResult
from workgraph_agents.llm import LLMResult
from workgraph_agents.pre_answer import PreAnswerDraft, PreAnswerOutcome
from workgraph_agents.membrane import (
    MembraneClassification,
    MembraneOutcome,
)
from workgraph_agents.testing import (
    StubClarificationAgent,
    StubConflictExplanationAgent,
    StubDeliveryAgent,
    StubIMAssistAgent,
    StubPlanningAgent,
    StubRequirementAgent,
)


class _NoDriftAgent:
    """Default DriftAgent stub for the api_env fixture.

    Returns has_drift=False for every project so tests that exercise
    unrelated endpoints don't accidentally generate drift alerts in
    shared state. Tests that exercise drift override
    `app.state.drift_service` or `app.state.drift_agent` directly.
    """

    prompt_version = "stub.drift.v1"

    async def check(self, context):
        return DriftCheckOutcome(
            result_payload=DriftCheckResult(
                has_drift=False, drift_items=[], reasoning="test stub"
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


class _ScriptableMembraneAgent:
    """Default MembraneAgent stub for the api_env fixture.

    Behaves like a keyword-driven classifier: any content containing
    "IGNORE" (case-insensitive) is flagged for review with a safety note;
    otherwise the stub mirrors whatever the test sets in
    `next_classification`. Tests that need a bespoke result assign
    `app.state.membrane_agent.next_classification` to an explicit
    MembraneClassification and the next `classify()` call returns it.
    """

    prompt_version = "stub.membrane.v1"

    def __init__(self) -> None:
        self.calls: list[dict] = []
        # If set, returned verbatim on the next call and reset after.
        self.next_classification: MembraneClassification | None = None

    async def classify(
        self,
        *,
        raw_content,
        source_kind,
        source_identifier,
        project_context,
    ):
        self.calls.append(
            {
                "raw_content": raw_content,
                "source_kind": source_kind,
                "source_identifier": source_identifier,
                "project_context": project_context,
            }
        )
        if self.next_classification is not None:
            classification = self.next_classification
            self.next_classification = None
        else:
            body = (raw_content or "").upper()
            # Heuristic injection detector so the prompt-injection test
            # doesn't need to stuff a bespoke classification into state.
            looks_injectable = any(
                marker in body
                for marker in (
                    "IGNORE ABOVE INSTRUCTIONS",
                    "IGNORE ALL PREVIOUS INSTRUCTIONS",
                    "DELETE ALL DATA",
                    "FORGET PREVIOUS",
                )
            )
            if looks_injectable:
                classification = MembraneClassification(
                    is_relevant=False,
                    tags=["other"],
                    summary="Suspected prompt-injection payload.",
                    proposed_target_user_ids=[],
                    proposed_action="flag-for-review",
                    confidence=0.2,
                    safety_notes=(
                        "stub: content contains injection markers — "
                        "flagged for human review"
                    ),
                )
            else:
                # Default: low-confidence, no targets → pending-review
                # so the auto-approve gate doesn't silently route.
                classification = MembraneClassification(
                    is_relevant=True,
                    tags=["other"],
                    summary=(raw_content or "")[:160],
                    proposed_target_user_ids=[],
                    proposed_action="ambient-log",
                    confidence=0.5,
                    safety_notes="",
                )

        return MembraneOutcome(
            classification=classification,
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


class _StubRenderAgent:
    """Default RenderAgent stub for the `api_env` fixture.

    Deterministic — produces a PostmortemDoc / HandoffDoc with the right
    shape so tests that don't exercise render content directly just see a
    cache-able payload. Tests that DO exercise render behaviour override
    `app.state.render_service` (to swap the cache) or
    `app.state.render_agent` (to swap the agent) directly.
    """

    postmortem_prompt_version = "stub.render.v1"
    handoff_prompt_version = "stub.render.v1"

    def __init__(self) -> None:
        self.postmortem_calls: list[dict] = []
        self.handoff_calls: list[dict] = []

    async def render_postmortem(self, project_context):
        from workgraph_agents.render import (
            PostmortemDoc,
            PostmortemOutcome,
            RenderedSection,
        )

        self.postmortem_calls.append(project_context)
        decisions = project_context.get("decisions") or []
        citations = "\n".join(
            f"- **D-{d.get('id')}** — {d.get('rationale') or '(no rationale)'}"
            for d in decisions
        ) or "(no recorded decisions)"
        return PostmortemOutcome(
            doc=PostmortemDoc(
                title=f"{(project_context.get('project') or {}).get('title') or 'Project'} postmortem",
                one_line_summary="Stub postmortem for tests.",
                sections=[
                    RenderedSection(
                        heading="What happened",
                        body_markdown="Stub narrative.",
                    ),
                    RenderedSection(
                        heading="Key decisions (lineage)",
                        body_markdown=citations,
                    ),
                    RenderedSection(
                        heading="What we got right", body_markdown="- stub"
                    ),
                    RenderedSection(
                        heading="What drifted", body_markdown="- stub"
                    ),
                    RenderedSection(heading="Lessons", body_markdown="- stub"),
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

    async def render_handoff(self, departing_user_context):
        from workgraph_agents.render import (
            HandoffDoc,
            HandoffOutcome,
            RenderedSection,
        )

        self.handoff_calls.append(departing_user_context)
        user = departing_user_context.get("user") or {}
        project = departing_user_context.get("project") or {}
        name = user.get("display_name") or user.get("username") or "Teammate"
        return HandoffOutcome(
            doc=HandoffDoc(
                title=f"{name}'s handoff — {project.get('title') or 'Project'}",
                sections=[
                    RenderedSection(
                        heading="Role summary",
                        body_markdown=f"{name} is a stubbed teammate.",
                    ),
                    RenderedSection(
                        heading="Active tasks I own", body_markdown="- stub"
                    ),
                    RenderedSection(
                        heading="Recurring decisions I make",
                        body_markdown="- stub",
                    ),
                    RenderedSection(
                        heading="Key relationships", body_markdown="- stub"
                    ),
                    RenderedSection(
                        heading="Open items / pending routings",
                        body_markdown="- stub",
                    ),
                    RenderedSection(
                        heading="Style notes (how I reply to common asks)",
                        body_markdown="- stub",
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


class _ScriptableMeetingMetabolizer:
    """Default MeetingMetabolizer stub for the api_env fixture.

    Keyword-driven: default return is an empty MetabolizedSignals
    (success outcome). Tests that need a specific extraction set
    `next_signals` or `next_outcome`; tests that want a failure path
    set `next_outcome='failed'`. Calls are recorded for assertions.
    """

    prompt_version = "stub.meeting.v1"

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.next_signals = None
        self.next_outcome: str = "ok"
        self.next_error: str | None = None

    async def metabolize(self, *, transcript_text, participant_context):
        from workgraph_api.services.meeting_ingest import (
            MetabolizedSignals,
            MetabolizeOutcome,
        )

        self.calls.append(
            {
                "transcript_text": transcript_text,
                "participant_context": participant_context,
            }
        )
        signals = self.next_signals or MetabolizedSignals()
        outcome = self.next_outcome
        error = self.next_error
        # Consume-once semantics so every test that sets `next_*`
        # stays local to its own scenario.
        self.next_signals = None
        self.next_outcome = "ok"
        self.next_error = None
        return MetabolizeOutcome(signals=signals, outcome=outcome, error=error)


class _SilenceEdgeAgent:
    """Default EdgeAgent stub for the `api_env` fixture — every turn is
    treated as 'silence' so tests that don't exercise the edge path stay
    deterministic. Tests that DO exercise it (test_personal.py) override
    `app.state.personal_service` with their own wiring.
    """

    async def respond(self, *, user_message, context):
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

    async def generate_options(self, *, routing_context):  # pragma: no cover - not used
        raise NotImplementedError

    async def frame_reply(self, *, signal, source_user_context):  # pragma: no cover
        raise NotImplementedError


class _ScriptablePreAnswerAgent:
    """Default PreAnswerAgent stub for the api_env fixture.

    Produces a deterministic draft whose `matched_skills` mirrors the
    target's role_skills so the sanitizer on the real agent would be a
    no-op. Tests that need a bespoke draft assign
    `app.state.pre_answer_agent.next_draft` to a custom PreAnswerDraft.

    For multi-turn flows (scrimmage Phase 2.B) tests can queue several
    drafts via `draft_queue.append(...)`. Queued drafts are consumed in
    FIFO order; `next_draft` still wins over the queue if both are set.
    """

    prompt_version = "stub.pre_answer.v1"

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.next_draft: PreAnswerDraft | None = None
        self.draft_queue: list[PreAnswerDraft] = []

    async def draft(
        self,
        *,
        question,
        target_context,
        sender_context=None,
        project_context=None,
    ):
        self.calls.append(
            {
                "question": question,
                "target_context": target_context,
                "sender_context": sender_context or {},
                "project_context": project_context or {},
            }
        )
        if self.next_draft is not None:
            draft = self.next_draft
            self.next_draft = None
        elif self.draft_queue:
            draft = self.draft_queue.pop(0)
        else:
            role_skills = list(target_context.get("role_skills") or [])
            # Say "medium confidence, probably route" — realistic default
            # behaviour when the stub has no project-specific knowledge.
            draft = PreAnswerDraft(
                body=(
                    f"Based on {target_context.get('display_name', 'them')}'s "
                    f"skills ({', '.join(role_skills[:2]) or 'n/a'}), this "
                    "would likely be framed as a scope question — route to "
                    "confirm."
                ),
                confidence="medium",
                matched_skills=role_skills[:2],
                uncovered_topics=[],
                recommend_route=True,
                rationale="stub pre-answer",
            )
        return PreAnswerOutcome(
            draft=draft,
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
from workgraph_domain import EventBus
from workgraph_persistence import (
    backfill_streams_from_projects,
    build_engine,
    build_sessionmaker,
    create_all,
    drop_all,
)

from workgraph_api.main import app
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
    DissentService,
    DriftService,
    HandoffService,
    IMService,
    IntakeService,
    LeaderEscalationService,
    LicenseContextService,
    MeetingIngestService,
    MembraneIngestService,
    MembraneService,
    MessageService,
    NotificationService,
    OnboardingService,
    PersonalStreamService,
    PlanningService,
    ProjectService,
    RenderService,
    RoutingService,
    PreAnswerService,
    ScrimmageService,
    SilentConsensusService,
    SignalTallyService,
    SimulationService,
    SkillAtlasService,
    SkillsService,
    SlaService,
    StreamService,
)


@pytest_asyncio.fixture
async def api_env():
    """Fresh in-memory DB + fully wired app.state for integration tests.

    Every Phase 7'/7'' service is instantiated against stubs so tests neither
    hit DeepSeek nor a real Redis. Tuple shape stays 6-long so pre-existing
    tests that unpack `(client, maker, bus, req_agent, clar_agent, plan_agent)`
    keep working; new collab services reach tests via `app.state`.
    """
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    maker = build_sessionmaker(engine)
    bus = EventBus(maker)
    # Phase B: backfill is idempotent; run it here so tests that boot
    # without any prior projects behave the same as the prod boot path.
    await backfill_streams_from_projects(maker)

    req_agent = StubRequirementAgent()
    clar_agent = StubClarificationAgent()
    plan_agent = StubPlanningAgent()
    im_agent = StubIMAssistAgent()
    conflict_agent = StubConflictExplanationAgent()
    delivery_agent = StubDeliveryAgent()

    collab_hub = CollabHub(redis_url=None)
    await collab_hub.start()

    auth_service = AuthService(maker, bus)
    project_service = ProjectService(maker, bus)
    notification_service = NotificationService(maker, bus, collab_hub)
    assignment_service = AssignmentService(
        maker, bus, collab_hub, notification_service
    )
    comment_service = CommentService(
        maker, bus, collab_hub, notification_service
    )
    signal_tally_service = SignalTallyService(maker)
    message_service = MessageService(
        maker, bus, collab_hub, notification_service, signal_tally_service
    )
    im_service = IMService(
        maker,
        bus,
        collab_hub,
        notification_service,
        message_service,
        im_agent,
    )
    conflict_service = ConflictService(maker, bus, collab_hub, conflict_agent)
    decision_service = DecisionService(
        maker, bus, collab_hub, conflict_service, assignment_service,
        signal_tally_service,
    )
    delivery_service = DeliveryService(
        maker, bus, collab_hub, delivery_agent
    )
    stream_service = StreamService(maker, bus, collab_hub)
    license_context_service = LicenseContextService(maker)
    routing_service = RoutingService(
        maker,
        bus,
        stream_service,
        signal_tally_service,
        license_context_service,
    )
    drift_agent = _NoDriftAgent()
    drift_service = DriftService(maker, bus, drift_agent, stream_service)
    commitment_service = CommitmentService(maker, bus)
    sla_service = SlaService(maker, bus, stream_service)
    simulation_service = SimulationService(maker)
    skill_atlas_service = SkillAtlasService(maker)
    pre_answer_agent = _ScriptablePreAnswerAgent()
    pre_answer_service = PreAnswerService(
        maker,
        skill_atlas_service,
        pre_answer_agent,
        license_context_service,
    )
    leader_escalation_service = LeaderEscalationService(
        maker, routing_service, pre_answer_service
    )
    scrimmage_service = ScrimmageService(
        maker,
        bus,
        pre_answer_service,
        pre_answer_agent,
        license_context_service,
        skill_atlas_service,
    )
    handoff_service = HandoffService(maker)
    dissent_service = DissentService(maker, bus)
    silent_consensus_service = SilentConsensusService(maker, bus)
    onboarding_service = OnboardingService(
        maker, license_context_service
    )
    meeting_metabolizer = _ScriptableMeetingMetabolizer()
    meeting_ingest_service = MeetingIngestService(
        maker, bus, meeting_metabolizer
    )
    # Mirror the production subscription — drift uses fire-and-forget
    # tasks, dissent validation piggybacks on the same event so tests
    # that submit decisions see dissent-accuracy flips without
    # invoking the service directly.
    bus.subscribe(
        "decision.applied", dissent_service.validate_on_decision_applied
    )
    # Mirror production subscriptions for silent-consensus so tests
    # that exercise the event-bus path (e.g. dissent-suppresses-
    # proposal) see the same re-scan behavior as prod. The scanner
    # itself is idempotent (pending-dedupe guard), so the extra wakeup
    # from dissent.recorded after a dissent write is safe.
    bus.subscribe("decision.applied", silent_consensus_service.on_event)
    bus.subscribe("dissent.recorded", silent_consensus_service.on_event)
    bus.subscribe(
        "task.status_changed", silent_consensus_service.on_event
    )
    from workgraph_api.services.perf_aggregation import PerfAggregationService

    perf_service = PerfAggregationService(maker)
    edge_agent = _SilenceEdgeAgent()
    skills_service = SkillsService(maker)
    personal_service = PersonalStreamService(
        maker,
        stream_service,
        routing_service,
        edge_agent,
        bus,
        skills_service=skills_service,
    )
    membrane_agent = _ScriptableMembraneAgent()
    membrane_service = MembraneService(
        maker, bus, collab_hub, stream_service, membrane_agent
    )
    membrane_ingest_service = MembraneIngestService(
        maker, membrane_service, license_context_service
    )
    render_agent = _StubRenderAgent()
    render_service = RenderService(maker, render_agent)

    intake_service = IntakeService(
        maker, bus, agent=req_agent, project_service=project_service
    )
    clar_service = ClarificationService(
        maker,
        bus,
        clarification_agent=clar_agent,
        requirement_agent=req_agent,
    )
    planning_service = PlanningService(maker, bus, agent=plan_agent)

    app.state.engine = engine
    app.state.sessionmaker = maker
    app.state.event_bus = bus
    app.state.intake_service = intake_service
    app.state.clarification_service = clar_service
    app.state.planning_service = planning_service
    app.state.requirement_agent = req_agent
    app.state.clarification_agent = clar_agent
    app.state.planning_agent = plan_agent
    app.state.im_agent = im_agent
    app.state.conflict_agent = conflict_agent
    app.state.auth_service = auth_service
    app.state.project_service = project_service
    app.state.collab_hub = collab_hub
    app.state.notification_service = notification_service
    app.state.assignment_service = assignment_service
    app.state.comment_service = comment_service
    app.state.message_service = message_service
    app.state.signal_tally_service = signal_tally_service
    app.state.im_service = im_service
    app.state.conflict_service = conflict_service
    app.state.decision_service = decision_service
    app.state.delivery_service = delivery_service
    app.state.delivery_agent = delivery_agent
    app.state.drift_service = drift_service
    app.state.drift_agent = drift_agent
    app.state.stream_service = stream_service
    app.state.routing_service = routing_service
    app.state.edge_agent = edge_agent
    app.state.personal_service = personal_service
    app.state.skills_service = skills_service
    app.state.membrane_agent = membrane_agent
    app.state.membrane_service = membrane_service
    app.state.membrane_ingest_service = membrane_ingest_service
    app.state.render_agent = render_agent
    app.state.render_service = render_service
    app.state.commitment_service = commitment_service
    app.state.sla_service = sla_service
    app.state.simulation_service = simulation_service
    app.state.skill_atlas_service = skill_atlas_service
    app.state.pre_answer_agent = pre_answer_agent
    app.state.pre_answer_service = pre_answer_service
    app.state.license_context_service = license_context_service
    app.state.leader_escalation_service = leader_escalation_service
    app.state.scrimmage_service = scrimmage_service
    app.state.handoff_service = handoff_service
    app.state.dissent_service = dissent_service
    app.state.silent_consensus_service = silent_consensus_service
    app.state.onboarding_service = onboarding_service
    app.state.meeting_ingest_service = meeting_ingest_service
    app.state.meeting_metabolizer = meeting_metabolizer
    app.state.perf_service = perf_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, maker, bus, req_agent, clar_agent, plan_agent
    try:
        await im_service.drain()
    except Exception:
        pass
    try:
        await conflict_service.drain()
    except Exception:
        pass
    try:
        await meeting_ingest_service.drain()
    except Exception:
        pass
    await collab_hub.stop()
    await drop_all(engine)
    await engine.dispose()
