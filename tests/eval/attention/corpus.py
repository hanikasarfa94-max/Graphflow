"""Synthetic corpus generator for the attention engine eval.

Builds a hand-curated bilingual (zh + en) snapshot of one product cell
— the "WorkGraph" team — that exercises the four-tier scope membrane
(personal / group / department / enterprise) and the supersede path.

Determinism: the 40-node first-pass corpus is hand-curated, not RNG'd,
so id ↔ ground-truth links in `seed_queries.yaml` are stable across
runs. The `seed` argument still threads through (for future RNG-padded
corpora when scaling to 200/1k/5k per PLAN-Next.md §N.1.5) and the
returned list is ordered deterministically.

Why hand-curated instead of generated:
  * Ground-truth labeling at this scale is tractable for a human
    reviewer — every must_appear / must_not_appear edge in
    seed_queries.yaml is consciously chosen.
  * Bilingual content has to read like a real product team's notes,
    not lorem ipsum, for the LLM-only baseline (Config A) to behave
    realistically.
  * The membrane suppress path needs concrete personal-to-someone-else
    nodes; randomly-tagged "personal" rows don't probe that.

Scope-tier distribution (40 nodes total):
  * 10 personal — split across 4 users; only the owner can read
  * 20 group    — the cell's shared canon (KB / decisions / streams /
                  tasks / risks all live here at the cell level)
  *  6 department — eng-wide policy / standards
  *  4 enterprise — company-wide policy

Superseded set: 3 items flagged `suppressed=True` represent old facts
overruled by a newer node. The pair (old, new) is referenced from
seed_queries.yaml so the eval can detect "was the stale node leaked?".
"""
from __future__ import annotations

import random
from collections.abc import Iterable

from .types import CorpusItem, NodeKind


# Mix used by the generator when padding past the hand-curated 40 nodes
# — kept here so the hyperedge to runner.py is stable, even though the
# first-pass eval doesn't exercise it.
DEFAULT_KIND_MIX: dict[NodeKind, float] = {
    "kb_item": 0.45,
    "stream_turn": 0.25,
    "task": 0.12,
    "decision": 0.08,
    "risk": 0.06,
    "person": 0.04,
}

# Kept for back-compat with the harness skeleton; no longer drives the
# hand-curated set, where suppressed flags are placed deliberately.
DEFAULT_SUPPRESS_FRACTION = 0.075  # 3 / 40


# -----------------------------------------------------------------------------
# Hand-curated bilingual corpus.
#
# Every entry is a 7-tuple: (id, kind, scope, lang, title, body, metadata).
# `suppressed` is layered on at the end via _SUPERSEDED_IDS so the
# supersede chain is greppable in one place.
#
# Author conventions:
#   * id stems carry semantic meaning (kb_pg_pool / dec_no_multicurrency /
#     etc.) rather than n00042 — this is the canon the seed queries
#     reference, and stable strings survive corpus reordering.
#   * Each fact ships in zh OR en, not both (parallel pairs would
#     double-count for retrieval; the eval samples real-world unilingual
#     notes).
#   * group items dominate (20/40); they are the cell's working memory.
# -----------------------------------------------------------------------------

_HAND_CURATED: list[tuple[str, NodeKind, str, str, str, str, dict[str, object]]] = [
    # --- group / cell scope (20 items) -----------------------------------
    # KB items (8 in group; bilingual mix)
    (
        "kb_pg_pool",
        "kb_item",
        "group",
        "en",
        "Postgres pool sizing",
        "API pods run pgbouncer in transaction mode with pool_size=20 per pod. "
        "Direct asyncpg pool is 5 per worker. Total upper bound under burst "
        "is ~150 connections; Postgres max_connections=200.",
        {"author": "u_bob", "tags": ["infra", "postgres"]},
    ),
    (
        "kb_webhook_idempotency",
        "kb_item",
        "group",
        "zh",
        "Stripe webhook 幂等性",
        "Stripe webhook 在 event.id 上是幂等的——所有 webhook 处理函数必须先在 "
        "stripe_events 表里 upsert event.id；重复事件直接 200 返回，不再走业务逻辑。",
        {"author": "u_alice", "tags": ["billing", "idempotency"]},
    ),
    (
        "kb_rate_limiter_perip",
        "kb_item",
        "group",
        "en",
        "Rate limiter — per-IP",
        "The public API rate limiter is per source IP, not per user. "
        "Authenticated bursts from a single corporate egress will hit the "
        "shared bucket. Per-user limits live in the app layer (see kb_app_quota).",
        {"author": "u_bob", "tags": ["api", "rate-limit"]},
    ),
    (
        "kb_membrane_review",
        "kb_item",
        "group",
        "zh",
        "Membrane 评审单一入口",
        "所有写入 cell 的内容（KB 群条目、决策结晶、边晋升、路由确认）都必须经过 "
        "MembraneService.review()。新增候选类型时扩展 CandidateKind，不要建第二条入口。",
        {"author": "u_alice", "tags": ["architecture", "membrane"]},
    ),
    (
        "kb_thin_router",
        "kb_item",
        "group",
        "en",
        "Thin-router pattern",
        "Routers do four things: pydantic validate → membership gate via "
        "ProjectMemberRepository.is_member → service call → translate service "
        "errors to HTTP status codes. No business logic; if you reach for a "
        "repository directly, the logic belongs in a service.",
        {"author": "u_alice", "tags": ["architecture", "router"]},
    ),
    (
        "kb_sla_lifecycle",
        "kb_item",
        "group",
        "zh",
        "承诺 SLA 生命周期",
        "承诺创建后 SLA 计时器从 commitment.created_at 起算；状态机为 "
        "open → at_risk(80%) → breached(100%)；breach 后向上级 cell 升级，并在 "
        "membrane 提交 RiskRow 候选。",
        {"author": "u_carol", "tags": ["sla", "commitment"]},
    ),
    (
        "kb_decision_lineage_old",
        "kb_item",
        "group",
        "en",
        "Multi-currency rollout (DEPRECATED)",
        "v1 ships with USD, EUR, JPY, and CNY. Pricing surface uses Stripe "
        "multi-currency; the rate refresh job is a daily cron pulling ECB.",
        {"author": "u_alice", "tags": ["billing", "currency", "deprecated"]},
    ),
    (
        "kb_decision_lineage_new",
        "kb_item",
        "group",
        "en",
        "Multi-currency rollout (current)",
        "v1 ships USD only. Multi-currency is deferred to v1.2 pending a "
        "tax-engine integration. See dec_no_multicurrency for the rationale "
        "and dec_v1_scope_freeze for the freeze that captured this change.",
        {"author": "u_alice", "tags": ["billing", "currency"]},
    ),
    # Decisions (4 in group)
    (
        "dec_no_multicurrency",
        "decision",
        "group",
        "zh",
        "v1 不做多币种",
        "决策：v1 launch 仅支持 USD。延后到 v1.2，等税务引擎接入。理由：当前 "
        "Stripe 多币种映射在退款路径上有 8 个未解 edge case；与其带病上线，不如延后。",
        {
            "author": "u_alice",
            "decided_at": "2026-04-15",
            "supersedes": ["dec_multicurrency_v1_old"],
            "tags": ["billing", "scope"],
        },
    ),
    (
        "dec_v1_scope_freeze",
        "decision",
        "group",
        "en",
        "v1 scope freeze on 2026-04-20",
        "Decision: lock v1 scope on 2026-04-20. Anything not in CHANGELOG by "
        "that date moves to v1.1. Owners: u_alice (PM-side), u_bob (eng-side).",
        {
            "author": "u_carol",
            "decided_at": "2026-04-20",
            "tags": ["scope", "release"],
        },
    ),
    (
        "dec_pg_pool_bump",
        "decision",
        "group",
        "en",
        "Bump pgbouncer pool to 20",
        "Decision: raise pgbouncer pool_size from 12 to 20 per pod after "
        "the load test caught exhaustion at 14 concurrent webhooks. Ratified "
        "by u_bob; revisit if Postgres CPU > 70% sustained.",
        {
            "author": "u_bob",
            "decided_at": "2026-04-22",
            "tags": ["infra", "postgres"],
        },
    ),
    (
        "dec_signin_provider",
        "decision",
        "group",
        "zh",
        "登录采用飞书 OAuth + 邮箱回退",
        "决策：v1 登录走飞书 OAuth；邮箱+魔法链接作为 fallback。理由：飞书内有 "
        "现成 SSO，企业部署最快路径；外部用户少，邮箱回退已够。",
        {
            "author": "u_alice",
            "decided_at": "2026-04-12",
            "tags": ["auth"],
        },
    ),
    # Stream turns (4 in group; chat utterances)
    (
        "stream_alex_ratelimit_q",
        "stream_turn",
        "group",
        "zh",
        "u_carol 在 #api 频道",
        "@u_bob 限流是按 IP 还是按用户？我看到企业用户从同一出口 IP 出来都被打回 429 了。",
        {"author": "u_carol", "channel": "#api", "ts": "2026-04-23T10:14:00Z"},
    ),
    (
        "stream_bob_ratelimit_a",
        "stream_turn",
        "group",
        "en",
        "u_bob replies in #api",
        "@u_carol it's per-IP at the edge. The per-user quota is enforced at "
        "the app layer with a Redis token bucket — should be fine if the "
        "corporate egress IP isn't shared across tenants. Want me to surface "
        "tenant-id in the limit key?",
        {"author": "u_bob", "channel": "#api", "ts": "2026-04-23T10:18:00Z"},
    ),
    (
        "stream_alice_freeze_call",
        "stream_turn",
        "group",
        "en",
        "u_alice in #release",
        "Heads-up: I'm calling v1 scope freeze for Monday 04-20. If your "
        "feature isn't in CHANGELOG.md by EOD Friday it slips to v1.1. "
        "Reply here if that breaks anything for you.",
        {"author": "u_alice", "channel": "#release", "ts": "2026-04-17T22:01:00Z"},
    ),
    (
        "stream_dave_design_q",
        "stream_turn",
        "group",
        "zh",
        "u_dave 在 #design",
        "决策卡片现在显示 rationale 但不显示 superseded 链——大家觉得要不要把被覆盖的旧决策也露出来？我倾向于露，便于追溯。",
        {"author": "u_dave", "channel": "#design", "ts": "2026-04-25T14:30:00Z"},
    ),
    # Tasks (1 in group)
    (
        "task_sla_wire",
        "task",
        "group",
        "zh",
        "把 SLA 计时器接到承诺生命周期",
        "实现 commitment.created_at → at_risk(80%) → breached 状态机；breach 时 "
        "推 RiskRow 候选到 membrane。验收：单测覆盖三个分支 + 端到端。",
        {
            "assignee": "u_bob",
            "status": "in_progress",
            "due": "2026-05-02",
            "tags": ["sla", "commitment"],
        },
    ),
    # Risks (1 in group)
    (
        "risk_pg_pool_burst",
        "risk",
        "group",
        "zh",
        "突发负载下 Postgres 连接池耗尽",
        "在 200 并发 webhook 下负载测试出连接池打满，async 调用排队 > 5s。已 "
        "通过 dec_pg_pool_bump 临时缓解；根因是 webhook 同步 + 长事务，需要异步化。",
        {
            "owner": "u_bob",
            "severity": "high",
            "status": "mitigated",
            "tags": ["infra", "postgres"],
        },
    ),
    # --- personal scope (10 items, 4 owners) ----------------------------
    (
        "kb_alice_meeting_prep",
        "kb_item",
        "personal",
        "en",
        "[u_alice] Prep notes for 04-30 leadership review",
        "Talking points: scope-freeze rationale, multi-currency deferral, "
        "Postgres pool incident postmortem. Don't volunteer the v1.2 timeline; "
        "Carol wants to land that with the customer-success team first.",
        {"owner": "u_alice", "tags": ["personal", "leadership"]},
    ),
    (
        "kb_alice_perf_review",
        "kb_item",
        "personal",
        "zh",
        "[u_alice] 个人绩效自评草稿",
        "本季度自评：交付方面打 4/5，膜评审协议落地是亮点；管理方面打 3/5——"
        "和 Carol 在路线图上有摩擦，需要更主动的对齐。下季度目标：把决策可观测性做到 1.0。",
        {"owner": "u_alice", "tags": ["personal", "perf"]},
    ),
    (
        "stream_alice_personal_log",
        "stream_turn",
        "personal",
        "en",
        "[u_alice] private daily log",
        "Today felt scattered. Carol pushed back on the auth decision — I "
        "think she's right that we underweighted the email fallback case. "
        "Note to self: re-open dec_signin_provider next week with her data.",
        {"owner": "u_alice", "ts": "2026-04-26T19:40:00Z", "tags": ["personal", "log"]},
    ),
    (
        "task_alice_personal_followup",
        "task",
        "personal",
        "en",
        "[u_alice] Follow up with Carol on auth fallback",
        "Personal todo: bring auth-fallback data to next 1:1 with Carol. "
        "Tied to dec_signin_provider; not a team task yet — escalate to "
        "the cell only if her data shifts the call.",
        {
            "owner": "u_alice",
            "assignee": "u_alice",
            "status": "open",
            "tags": ["personal"],
        },
    ),
    (
        "kb_bob_oncall_runbook_draft",
        "kb_item",
        "personal",
        "zh",
        "[u_bob] 待发布的 oncall runbook 草稿",
        "我自己整理的 oncall 操作手册；还没评审，不要直接外发。覆盖 "
        "pg_pool 报警、webhook 重放、SLA breach 三个最常见场景。下周拿去 cell 过一轮。",
        {"owner": "u_bob", "tags": ["personal", "oncall", "draft"]},
    ),
    (
        "stream_bob_personal_vent",
        "stream_turn",
        "personal",
        "en",
        "[u_bob] private channel rant",
        "Honest take I'd never say in #api: the rate-limiter design is "
        "going to bite us on tenant-shared egress IPs. I flagged it in the "
        "design review and got overruled. Keeping a paper trail here.",
        {"owner": "u_bob", "ts": "2026-04-23T11:02:00Z", "tags": ["personal"]},
    ),
    (
        "task_bob_personal_learning",
        "task",
        "personal",
        "en",
        "[u_bob] Read the LangGraph internals deep-dive",
        "Personal learning task — read the LangGraph node/edge runtime "
        "writeup. Loosely related to our graph-as-state direction but not "
        "team work yet.",
        {
            "owner": "u_bob",
            "assignee": "u_bob",
            "status": "open",
            "tags": ["personal", "learning"],
        },
    ),
    (
        "kb_carol_roadmap_thoughts",
        "kb_item",
        "personal",
        "zh",
        "[u_carol] 个人路线图思考",
        "我对 v1.2 路线的私人想法：多币种之后应该先做企业级 SSO，然后再做 "
        "细粒度权限。还没和 Alice 同步，等下周 1:1 再聊。",
        {"owner": "u_carol", "tags": ["personal", "roadmap"]},
    ),
    (
        "stream_carol_personal_reflect",
        "stream_turn",
        "personal",
        "en",
        "[u_carol] private reflection",
        "Reflecting on the freeze decision — Alice moved fast and I think "
        "it was the right call, even though I pushed back in real time. "
        "Need to flag the postmortem-of-the-process at next retro.",
        {"owner": "u_carol", "ts": "2026-04-21T20:15:00Z", "tags": ["personal"]},
    ),
    (
        "kb_dave_design_sketches",
        "kb_item",
        "personal",
        "en",
        "[u_dave] Half-baked decision-card redesign",
        "Sketches for a redesigned decision card that surfaces supersede "
        "lineage in the timeline. Not ready to share — color palette and "
        "spacing are off vs. DESIGN.md. Show #design when it's a v0.5.",
        {"owner": "u_dave", "tags": ["personal", "design", "draft"]},
    ),
    # --- department scope (6 items) -------------------------------------
    (
        "kb_dept_python_style",
        "kb_item",
        "department",
        "en",
        "Eng dept — Python style standard",
        "All eng repos use ruff + black-compat formatting; line length 100; "
        "type hints on every public function; pytest is the test runner. "
        "PRs without type hints fail CI.",
        {"author": "u_eve", "department": "d_eng", "tags": ["standards", "python"]},
    ),
    (
        "kb_dept_oncall_rotation",
        "kb_item",
        "department",
        "zh",
        "工程部 oncall 轮值制度",
        "工程部每周一名 primary oncall + 一名 secondary。primary 接所有 P1/P2 "
        "告警；超过 30 分钟未响应自动升级 secondary。每月最后一周组内回顾 oncall 负载。",
        {"author": "u_eve", "department": "d_eng", "tags": ["standards", "oncall"]},
    ),
    (
        "dec_dept_llm_provider",
        "decision",
        "department",
        "en",
        "Eng dept — DeepSeek for dev/test LLM",
        "Department decision: dev + eval workloads use DeepSeek (OpenAI-compatible) "
        "as the default provider. Production routing stays provider-agnostic; "
        "any caching benchmark must re-run when providers change.",
        {
            "author": "u_eve",
            "department": "d_eng",
            "decided_at": "2026-04-18",
            "tags": ["llm", "provider"],
        },
    ),
    (
        "kb_dept_secret_mgmt",
        "kb_item",
        "department",
        "zh",
        "工程部秘钥管理规范",
        "所有秘钥经 Vault 注入，禁止写入 .env 或 secrets.json 提交到仓库；"
        "CI 通过 OIDC 拿短期凭证。每季度轮换一次。pre-commit hook 拦截疑似 "
        "AWS/Stripe key 字面量。",
        {"author": "u_frank", "department": "d_eng", "tags": ["security", "standards"]},
    ),
    (
        "task_dept_audit_q2",
        "task",
        "department",
        "en",
        "Q2 cross-cell architecture review",
        "Eng-dept-wide: each cell submits its top 3 architectural risks by "
        "2026-05-15. d_eng arch board reviews and triages; outputs feed the "
        "department roadmap.",
        {
            "assignee": "u_eve",
            "department": "d_eng",
            "status": "open",
            "due": "2026-05-15",
            "tags": ["governance"],
        },
    ),
    (
        "risk_dept_burnout",
        "risk",
        "department",
        "zh",
        "工程部 oncall 负载偏斜",
        "近三月 oncall 数据显示 30% 的 P1 集中在 2 个 cell；负载没有按 cell 大小 "
        "归一化，导致那两个 cell 的工程师 burnout 风险偏高。需要重新校准轮值权重。",
        {
            "owner": "u_eve",
            "department": "d_eng",
            "severity": "medium",
            "status": "open",
            "tags": ["people", "oncall"],
        },
    ),
    # --- enterprise scope (4 items) -------------------------------------
    (
        "kb_corp_data_classification",
        "kb_item",
        "enterprise",
        "en",
        "Company-wide data classification policy",
        "Four tiers: public / internal / confidential / restricted. PII is "
        "always at least confidential; financial records are restricted. "
        "All eng systems must label data at ingestion and propagate the label "
        "through to storage and logs.",
        {"author": "u_frank", "tags": ["security", "policy", "company-wide"]},
    ),
    (
        "dec_corp_remote_policy",
        "decision",
        "enterprise",
        "zh",
        "公司层面：远程办公 3+2 政策",
        "公司决策：自 2026-Q2 起执行 3+2（每周三天到岗、两天远程）。该政策由 "
        "CEO 与 People 团队联合发布；任何 cell/部门不得自行降低到岗天数。",
        {
            "author": "u_frank",
            "decided_at": "2026-03-30",
            "tags": ["people", "policy"],
        },
    ),
    (
        "kb_corp_ai_use",
        "kb_item",
        "enterprise",
        "en",
        "Company-wide AI tool use policy",
        "Approved AI providers: OpenAI, Anthropic, DeepSeek (for dev only). "
        "Customer data must never be sent to a non-approved provider. PII in "
        "prompts requires legal review; redaction is the default.",
        {"author": "u_frank", "tags": ["ai", "policy", "company-wide"]},
    ),
    (
        "risk_corp_supply_chain",
        "risk",
        "enterprise",
        "en",
        "Third-party LLM-provider supply-chain risk",
        "We rely on three external LLM providers; any of them being breached "
        "or rate-limiting us hard would degrade product quality. Mitigation: "
        "provider-agnostic routing layer + monthly drill that exercises the "
        "fallback chain.",
        {
            "owner": "u_frank",
            "severity": "medium",
            "status": "open",
            "tags": ["supply-chain", "ai"],
        },
    ),
]


# Old facts that have been overruled by a newer node. The eval treats
# these as "must not appear" — Config A is expected to leak them ("for
# completeness"); Config C should drop them via the membrane filter.
_SUPERSEDED_IDS: frozenset[str] = frozenset(
    {
        "kb_decision_lineage_old",   # superseded by kb_decision_lineage_new
        "dec_multicurrency_v1_old",  # superseded by dec_no_multicurrency
        "kb_pg_pool_old",            # superseded by kb_pg_pool + dec_pg_pool_bump
    }
)

# Old fact rows the supersede chain points to. Held separately from
# _HAND_CURATED so the suppress flag is clearly attached at construction
# and the supersede chain reads top-to-bottom.
_SUPERSEDED_NODES: list[
    tuple[str, NodeKind, str, str, str, str, dict[str, object]]
] = [
    (
        "kb_pg_pool_old",
        "kb_item",
        "group",
        "en",
        "Postgres pool sizing (OLD — DO NOT USE)",
        "Per-pod pool size is 12. Postgres max_connections=150. Updated by "
        "dec_pg_pool_bump on 2026-04-22 — see kb_pg_pool for the current "
        "configuration.",
        {
            "author": "u_bob",
            "tags": ["infra", "postgres", "superseded"],
            "superseded_by": "kb_pg_pool",
        },
    ),
    (
        "dec_multicurrency_v1_old",
        "decision",
        "group",
        "en",
        "v1 ships multi-currency (SUPERSEDED 2026-04-15)",
        "Original decision: v1 ships USD/EUR/JPY/CNY. Superseded by "
        "dec_no_multicurrency after the tax-engine integration was ruled "
        "out for v1 timeline.",
        {
            "author": "u_alice",
            "decided_at": "2026-03-22",
            "superseded_by": "dec_no_multicurrency",
            "tags": ["billing", "currency", "superseded"],
        },
    ),
]


def build_corpus(
    *,
    size: int,
    seed: int = 42,
    kind_mix: dict[NodeKind, float] | None = None,
    suppress_fraction: float = DEFAULT_SUPPRESS_FRACTION,
) -> list[CorpusItem]:
    """Generate a corpus of `size` nodes.

    First-pass eval (size <= 40) returns a hand-curated bilingual cell:
    10 personal / 20 group / 6 department / 4 enterprise, with three
    superseded items flagged `suppressed=True`. The corpus order is
    deterministic — sorted by (scope, kind, id) — so two runs at the
    same size produce identical lists.

    For size > 40 (scaling pass per PLAN-Next.md §N.1.5), the
    hand-curated 40-node set is returned in full and the remainder is
    padded with deterministic synthetic items via `random.Random(seed)`.

    Args:
        size: number of nodes to return. Hand-curated nodes are always
            included up to 40; padding kicks in beyond that.
        seed: RNG seed for the padding synthesis. Hand-curated content
            is independent of the seed.
        kind_mix: override the node-kind distribution used for padding.
        suppress_fraction: fraction of padding nodes to mark suppressed.
            Hand-curated suppression is fixed at 3/40 regardless.

    Returns:
        A deterministic, ordered list of `CorpusItem`s.
    """
    items = _build_hand_curated()
    if size <= len(items):
        return items[:size]

    # Padding path — only exercised by the scaling pass. Deterministic
    # via `seed`; never produces duplicate ids vs. the hand-curated set.
    pad = _build_padding(
        n=size - len(items),
        seed=seed,
        kind_mix=kind_mix or DEFAULT_KIND_MIX,
        suppress_fraction=suppress_fraction,
    )
    return items + pad


def split_visible_and_suppressed(
    corpus: Iterable[CorpusItem],
) -> tuple[list[CorpusItem], list[CorpusItem]]:
    """Split helper for the leak-rate metric harness."""
    visible: list[CorpusItem] = []
    suppressed: list[CorpusItem] = []
    for item in corpus:
        (suppressed if item.suppressed else visible).append(item)
    return visible, suppressed


# -----------------------------------------------------------------------------
# Internals
# -----------------------------------------------------------------------------


def _build_hand_curated() -> list[CorpusItem]:
    """Materialize the hand-curated 40-node corpus.

    Stable order: sort by (scope_tier, kind, id) so two runs hand back
    identical lists. Suppress flags are layered on from `_SUPERSEDED_IDS`.
    """
    rows = list(_HAND_CURATED) + list(_SUPERSEDED_NODES)
    items: list[CorpusItem] = []
    for (id_, kind, scope, lang, title, body, metadata) in rows:
        meta = dict(metadata)
        meta.setdefault("lang", lang)
        items.append(
            CorpusItem(
                id=id_,
                kind=kind,
                scope=scope,  # type: ignore[arg-type]
                title=title,
                content=body,
                metadata=meta,
                suppressed=id_ in _SUPERSEDED_IDS,
            )
        )
    # Deterministic order — scope then kind then id.
    scope_order = {"personal": 0, "group": 1, "department": 2, "enterprise": 3}
    items.sort(key=lambda i: (scope_order.get(i.scope, 99), i.kind, i.id))
    return items


def _build_padding(
    *,
    n: int,
    seed: int,
    kind_mix: dict[NodeKind, float],
    suppress_fraction: float,
) -> list[CorpusItem]:
    """Generate `n` synthetic padding items past the hand-curated 40.

    Used only by the scaling pass. Ids are namespaced `pad_NNNNN` so they
    can never collide with hand-curated ids. Content is intentionally
    plain — the scaling eval cares about retrieval-at-scale signal, not
    prose realism.
    """
    rng = random.Random(seed)
    kinds, weights = zip(*kind_mix.items())
    scopes: tuple[str, ...] = ("personal", "group", "department", "enterprise")
    scope_weights = (0.25, 0.50, 0.15, 0.10)

    pad: list[CorpusItem] = []
    for i in range(n):
        kind = rng.choices(kinds, weights=weights, k=1)[0]
        scope = rng.choices(scopes, weights=scope_weights, k=1)[0]
        suppressed = rng.random() < suppress_fraction
        pad.append(
            CorpusItem(
                id=f"pad_{i:05d}",
                kind=kind,
                scope=scope,  # type: ignore[arg-type]
                title=f"[padding {kind} #{i}]",
                content=f"Synthetic padding body for {kind} {i} (scope={scope}).",
                metadata={"seed": seed, "index": i, "padding": True},
                suppressed=suppressed,
            )
        )
    return pad
