二、项目结果展示
项目展示可参考我们的项目评分维度：
维度 1：完整性与价值（50%）
- 解决什么问题 / 痛点？
- AI 在其中起到什么关键作用？
- 流程是否完整闭环？能否落地使用？
- Demo 是否稳定、可正常演示？
- 带来什么实际价值 / 效率提升？
维度 2：创新性（25%）
- AI 相关创新点（技术选型 / 实现思路 / 应用方式等）
- 方案差异化亮点
- 是否可复用、可推广
维度 3：技术实现性（25%）
- AI 技术使用深度
- 技术架构 / 方案合理性
- 工程规范、稳定性、可扩展性
（一）总项目结果展示：
作品名:GraphFlow 
状态: 已上线可演示 · https://graphflow.flyflow.love
现场演示入口:https://graphflow.flyflow.love ·
账号1 raj_zh / moonshot2026
账号2 aiko_zh / moonshot2026
账号3 maya_zh / moonshot2026
Github链接 https://github.com/hanikasarfa94-max/Graphflow
1.Demo展示（可录屏）
现场入口：https://graphflow.flyflow.love
演示项目（中文）：Moonshot Studios — 6 人独立游戏团队、距发售 4 周，围绕 Boss 难度 / Switch 性能 / 永久死亡机制三个核心决策，演示一次"零会议、零文档"的跨学科决策结晶。
演示账号：raj_zh / aiko_zh / maya_zh，密码 moonshot2026。
录屏脚本：见 docs/demo_script.md（八个场景，约 7 分钟），覆盖：登录首页 → 团队会议室决策芯片 → 个人流路由询问 → 决策⚡结晶 → 知识库引用 → 复盘文档自动渲染（含可点击血缘引用）→ 图谱可视化。
关键画面：（a）⚡ 决策芯片可点击跳转到决策详情页；（b）路由 inbound 卡片显示真实发起人 + "通过项目助手询问你"；（c）复盘 Markdown 中 **D-<id>** 引用全部可点击回源；（d）右侧 React Flow 全图谱视图，展示 15–20 个真实节点 + 时间倒带条。

2.核心部分代码展示
仓库：https://github.com/hanikasarfa94-max/Graphflow
当前架构主线：World Graph（共享背景、知识、决策、风险与约束） / Org Graph（成员、责任、能力证据与路由可信度） / Work Graph（任务、路由、交接、评审与状态转化）。三张图通过 Membrane 治理共享状态写入，通过 Transition Contract 描述行动如何跨越状态边界，通过 Epistemic Event Contract 描述信息如何从私人信号、草稿或提案变成 accepted-for-scope 的组织事实。v1 不把 common knowledge 简化成一个字段，而是用 scoped canonicality 表达"在某个项目 / 房间范围内可被后续行动引用"。Router Agent 负责把信号转化为带上下文、证据和预期判断的定向认知动作；项目助手是用户接入共享图谱状态的本地界面。
以下挑选两条主线、共五段最能体现 AI 工程深度的真实代码。

———— 一、路由系统：让 AI 替你跑会、把"询问"做成可审计的图边 ————

【代码 1.1】 路由派发 + 接地（grounding）闸门
位置：apps/api/src/workgraph_api/services/routing.py · RoutingService.dispatch
意义：客户端（前端 / 项目助手；代码内部类名仍为 EdgeAgent）说"想路由给 Aiko"不算数；服务端会重新跑一遍 routing_suggest 评分器去验证目标是否在候选列表里，把验证结果（routing_basis）注入边的背景中。这是产品级的"AI 接地"——任何一次跨人路由都必须能解释"为什么是这个人"。
```python
# R2 — 接地闸门：服务端重跑 routing_suggest 验证目标
suggestions = await self._skills_service.suggest_routing(
    project_id=project_id, query=framing,
    source_user_id=source_user_id, limit=5,
)
matched = next(
    (s for s in suggestions if s.get("user_id") == target_user_id),
    None,
)
if matched is not None:
    routing_basis = {
        "grounded": True,
        "matched_suggestion": matched,
        "alternatives": [s for s in suggestions if s.get("user_id") != target_user_id],
    }
elif suggestions:
    # 候选存在但目标不在其中 → 严格拒绝并把候选 alternatives 回传，
    # 让调用方重新选或升级到 clarification。
    return {"ok": False, "error": "target_not_grounded", "alternatives": suggestions}
else:
    routing_basis = {"grounded": False, "reason": "no_signal_in_project_state"}

# 把接地结果作为 typed entry 注入 background_json，审计代码不依赖 schema 迁移就能找到
background = list(background) + [{
    "source": "routing_basis",
    "snippet": "Server-side routing_suggest verification."
                if routing_basis["grounded"] else f"Ungrounded ({routing_basis['reason']}).",
    "routing_basis": routing_basis,
}]

# 持久化为 RoutedSignalRow——一条带血缘的图边
async with session_scope(self._sessionmaker) as session:
    signal = await RoutedSignalRepository(session).create(
        source_user_id=source_user_id, target_user_id=target_user_id,
        source_stream_id=source_stream_id, target_stream_id=target_stream_id,
        project_id=project_id, framing=framing,
        background=background, options=options, trace_id=trace_id,
    )
```

【代码 1.2】 预答（pre-answer）：在打扰真人之前，先让目标的子代理给一份草稿
位置：packages/agents/src/workgraph_agents/pre_answer.py · PreAnswerDraft
意义：路由提议卡上的"预读"按钮调用此能力——目标成员的子代理基于其角色技能 + 个人技能 + 项目上下文先拟一份回复。如果发起方满意，可以直接关掉，零打扰；如果不满意才真正发到目标的个人流。`human_answer_demand` 是一个产品级的诚实位：当问题需要真人才能判断（任务分配、日程、人力预算），代理就承认"这件事我答不了"，不会假装信心十足。
```python
Confidence = Literal["high", "medium", "low"]

class PreAnswerDraft(BaseModel):
    """目标边的预答草稿——结构化输出，恢复梯度统一为 JSON模式 → 三重试 → manual_review。"""
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=2000)
    confidence: Confidence = "low"
    matched_skills: list[str] = Field(default_factory=list, max_length=12)
    uncovered_topics: list[str] = Field(default_factory=list, max_length=6)
    recommend_route: bool = True
    rationale: str = Field(default="", max_length=400)
    # 引文即证据：预答支持把实质性事实句挂到图节点 / KB 节点引文上；
    # 无法接地的内容会在上层 UI / 审核逻辑中弱化或进入人工复核。
    claims: list[CitedClaim] = Field(default_factory=list, max_length=8)
    # 诚实位：当问题本质上需要真人判断（任务分配 / 日程 / 容量），代理拒绝"自信地空答"
    human_answer_demand: bool = False

# manual_review 兜底——LLM 三次重试都失败时返回的安全草稿
_MANUAL_REVIEW_DRAFT = PreAnswerDraft(
    body="Could not generate a pre-answer automatically. The sender should "
         "route the question directly — the target will see it in their stream.",
    confidence="low", recommend_route=True,
    rationale="manual_review fallback",
)
```

【代码 1.3】 选项生成（generate_options）：把"问个开放问题"压缩成"挑 2-4 个候选"
位置：packages/agents/src/workgraph_agents/edge.py · RoutedOption / RoutedOptionsBatch / generate_options
意义：路由不是"自由文本来回"，而是"结构化选择"。代理会基于双方上下文产出 2-4 个选项，每项含 标签 / 背景 / 理由 / 交换代价 / 权重 (0-1)。目标成员一键 Pick 即决策；自定义回复保留为兜底通道。这把"决策摩擦"压缩到秒级。
```python
class RoutedOption(BaseModel):
    """目标看到的一张选项卡。形状参照 docs/north-star.md 'Option design'。"""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default="")  # 留空允许；validator 自动补 UUID4
    label: str = Field(min_length=1, max_length=60)
    kind: OptionKind  # accept | counter | escalate | custom
    background: str = Field(default="", max_length=240)
    reason: str = Field(default="", max_length=120)
    tradeoff: str = Field(default="", max_length=120)
    weight: float = Field(ge=0.0, le=1.0)

class RoutedOptionsBatch(BaseModel):
    """LLM 填充的容器——min/max 强制 2-4 项，单一选项不被采纳。"""
    model_config = ConfigDict(extra="forbid")
    options: list[RoutedOption] = Field(min_length=2, max_length=4)

    @field_validator("options")
    @classmethod
    def _ensure_ids(cls, v):
        # 强制 id 唯一稳定——后端持久化对 id 有 stable-ref 契约，
        # LLM 留空或返回重复时由 validator 自动补 UUID4
        seen = set(); fixed = []
        for opt in v:
            oid = (opt.id or "").strip()
            if not oid or oid in seen:
                oid = str(uuid.uuid4())
            seen.add(oid)
            if oid != opt.id:
                opt = opt.model_copy(update={"id": oid})
            fixed.append(opt)
        return fixed

class EdgeAgent:
    async def generate_options(self, *, routing_context):
        # JSON 模式 + 三次重试 + 失败 manual_review 回退到一组安全占位选项
        batch, result, attempts = await self._llm.complete_structured(
            messages, pydantic_cls=RoutedOptionsBatch, max_attempts=3,
        )
        # 用目标成员的 response profile 做最后一轮权重微调——
        # 与目标技能匹配度高的选项 weight 上浮
        options = _apply_profile_weighting(
            batch.options, routing_context.get("target_response_profile") or {},
        )
        outcome = "ok" if attempts == 1 else "retry"
        return RoutedOptionsOutcome(options=options, result=result, outcome=outcome, attempts=attempts)
```

———— 二、膜系统：群体共识进入图谱的唯一边界 ————

【代码 2.1】 KB 重复检测（_review_kb_item_group）：标题近似 → 数值冲突 → 大小歧义 → 三档回执
位置：apps/api/src/workgraph_api/services/membrane.py · MembraneService._review_kb_item_group
意义：知识库的最大失败模式不是"没人写"，而是"每个人写一份大同小异的"。这段确定性检测分三档：
（a）标题归一化重复但内容大小相近 → request_review，让所有者决定合并 / 取代 / 平行；
（b）大小相差 >2x 或 <0.5x → request_clarification，主动反问"你是 supersede / elaborate / separate？"；
（c）同主题但数值断言不同（"40% 退坑率" vs "30% 退坑率"）→ request_review 标红。M1 阶段在此之上叠加语义 LLM reviewer，对模糊语义矛盾追加意见；deterministic 永远兜底。
```python
async def _review_kb_item_group(self, candidate: MembraneCandidate) -> MembraneReview:
    normalized_new = _normalize_title(candidate.title)
    if not normalized_new:
        return MembraneReview(action="auto_merge", reason="empty_title_lets_caller_validate")

    async with session_scope(self._sessionmaker) as session:
        existing = await KbItemRepository(session).list_group_for_project(
            project_id=candidate.project_id, limit=500,
        )

    for row in existing:
        if row.status == "archived":
            continue  # 归档行已被所有者明确退役，新条目覆盖标题不算冲突
        if _normalize_title(row.title) != normalized_new:
            continue

        # 大小歧义：内容相差 ≥2x 或 ≤0.5x → 反问而非阻塞
        existing_len = len(row.content_md or "")
        new_len = len(candidate.content or "")
        size_ambiguous = (
            existing_len > 0 and new_len > 0
            and (new_len >= existing_len * 2 or new_len <= existing_len * 0.5)
        )
        already_answered = bool(candidate.metadata.get("clarification_answer"))

        if size_ambiguous and not already_answered:
            return MembraneReview(
                action="request_clarification",
                reason="duplicate_title_size_diverges",
                clarify_question=(
                    f"An existing group KB entry titled '{row.title}' already exists. "
                    "Are you (a) SUPERSEDING it with this new version, "
                    "(b) ELABORATING — your entry should become a section under it, "
                    "or (c) PROPOSING a separate entry under a sharper title?"
                ),
                conflict_with=(row.id,),
            )
        return MembraneReview(
            action="request_review", reason="duplicate_title",
            diff_summary=f"An existing group KB entry has the same title: '{row.title}'...",
            conflict_with=(row.id,),
        )

    # 同主题数值断言冲突——典型例子："Boss-1 退坑率 40%" vs 已有 "Boss-1 退坑率 30%"
    numeric_conflict = _first_numeric_fact_conflict(
        title=candidate.title, content=candidate.content, existing=existing,
    )
    if numeric_conflict is not None:
        row, new_numbers, existing_numbers = numeric_conflict
        return MembraneReview(
            action="request_review", reason="numeric_claim_conflict",
            diff_summary=(
                f"Candidate appears to cover the same topic as '{row.title}' "
                f"but carries different numeric claims: candidate={sorted(new_numbers)}, "
                f"existing={sorted(existing_numbers)}."
            ),
            conflict_with=(row.id,),
        )
```

【代码 2.2】 技能/画像系统：5 级 Trust Ladder——技能不是标签，是对证据的投影
位置：apps/api/src/workgraph_api/services/org_capabilities.py · OrgCapabilityService
意义：成员的"能力"不是一栏自填字段，而是从多类证据投影出的 5 级阶梯。读优先（read-only），永不污染 UserRow.profile；任何一次读取都对当前图状态实时计算。Skill key 来自一个封闭集合（declared_abilities ∪ role_hints ∪ skill_tags），系统永远不从行文本里"发明"新技能——这条不变量确保 AI 给出的能力评估可被人直接审计。
```python
CapabilityLevel = Literal[
    "declared",   # 用户 profile 自述
    "role",       # 项目级角色 skill_tags 推断
    "observed",   # 图谱观察到他在这个主题附近工作（决策 / 任务）
    "validated",  # 至少一条已被接受的证据：source 接受了路由回复，
                  #   或绑定该技能的任务到达 status='done'
    "trusted",    # 重复 validated 证据（≥ TRUSTED_THRESHOLD 条不同行）
]

# 阈值——上一级永远要求"真证据"，不放过 active-member 噪声
OBSERVED_THRESHOLD = 1   # 至少一条 observed 信号
VALIDATED_THRESHOLD = 1  # 至少一条 validated 信号
TRUSTED_THRESHOLD = 3    # 三条不同 validated 行才升级到 trusted
                          # （两条可能巧合，三条很难）

# 置信度——单调、有界、刻意不是"概率"，让路由秩可以用软信号而不丢含义
_LEVEL_CONFIDENCE: dict[CapabilityLevel, float] = {
    "declared": 0.30, "role": 0.45, "observed": 0.60,
    "validated": 0.78, "trusted": 0.92,
}

# 升序——给路由秩做"是否至少 validated"的门控
_LEVEL_ORDER: dict[CapabilityLevel, int] = {
    "declared": 0, "role": 1, "observed": 2, "validated": 3, "trusted": 4,
}

def level_at_least(level: str, threshold: str) -> bool:
    """路由秩用此判断'这个人这条技能是否至少 validated'。
    未知 level 字符串永远返回 False，绝不爆掉调用方。"""
    a = _LEVEL_ORDER.get(level, -1)
    b = _LEVEL_ORDER.get(threshold, 99)
    return a >= b

class OrgCapabilityService:
    """对当前图状态的实时投影——读完即丢，没有缓存、没有反范式列。"""
    async def list_for_project(self, project_id: str) -> list[dict[str, Any]]:
        # 一次性预取证据行：路由信号、任务+派单、决策。
        # 然后在 Python 侧对 skill_keys 做文本匹配——v1 规模下，
        # skill 键短、行数有限，本地匹配胜过 N 次 SQL 查询。
        ...
```

更多核心模块（按"协调即图谱"主线推荐评审导览）：
- apps/api/src/workgraph_api/services/decisions.py + services/im.py — 决策结晶（投票收敛 / 冲突解决 / 隐性共识 / IM 接受）四路径汇聚到同一张 DecisionRow
- apps/api/src/workgraph_api/services/flow_projection.py — Flow Packets 投影层，把 5 类源行投影为含 transition_contract + epistemic_event 的"轮次包"
- packages/agents/src/workgraph_agents/membrane_reviewer.py — 膜的 LLM 语义审查代理（在 deterministic 检查之上叠加，永不替换）
- packages/persistence/src/workgraph_persistence/orm.py — 33 张 ORM 表的核心——StreamRow / RoutedSignalRow / DecisionRow / KbItemRow / DissentRow / SilentConsensusRow / OnboardingStateRow 等
- apps/web/src/components/stream/PersonalStream.tsx + RoutedInboundCard.tsx — 主战场前端：预演卡、工具调用可见、路由 inbound 真人归属
- apps/web/src/app/projects/[id]/detail/graph/GraphCanvas.tsx — React Flow 图谱可视化 + 时间倒带条

3.项目亮点介绍
（1）"动态组织认知系统"的范式重构。同行做的是"AI + 文档"，我们做的是"受治理的组织状态更新"：消息、任务、知识和决策都不是普通内容，而是可能改变 World Graph / Org Graph / Work Graph 的认知事件。GraphFlow 的价值不是生成更多文本，而是在 AI 加速协作后，让团队围绕同一套可审计状态行动、承认同一个决策、执行同一个目标。
（2）核心群体级原语已经形成闭环：项目助手 / 路由 / 预答 / Flow Packet / Transition Contract / Epistemic Event Contract / 决策结晶 / 异议（dissent）/ Membrane review / KB 引文 / Org Capability Trust Ladder / Handoff render / 图谱审计。部分更前沿原语仍处于 projection-only 或实验性阶段，文档中按"已上线、部分实现、未来路线"区分，避免把研究方向误说成完全成熟的产品功能。
（3）零会议决策闭环：演示路径"Raj 输入 → 项目助手解析 → 路由给 Aiko → Aiko 选择或自定义回复 → Maya 接受 → ⚡结晶"可以在约 90 秒内完成，传统等价物通常是一场同步会议或多轮群聊。
（4）演示稳定性：683/683 后端测试通过、TypeScript 严格模式、覆盖 EN+ZH 双演示数据、Cloudflare Tunnel + Aliyun 国内 VPS 上线，已通过多轮 dogfood。
（5）膜（Membrane）作为单一边界的工程纪律：共享上下文写入的核心路径（KB、任务升级、决策结晶、手工房间、技能修改、成员邀请等）统一由 domain service + Membrane/Transition Contract 管控；低风险 owner 操作可 auto-merge 但必须留下审计线索。这个约束避免后期出现"七条进入图谱的私下路径"，是 AI 工程长期可审计的关键。

4.AI 亮点介绍
此模块侧重体现项目的 AI 工程化深度与落地价值，可参考以下思路示例展开，也欢迎自行做更多方面补充。
- 项目中使用了哪些高阶 AI 技巧？
  · 多智能体 / 多契约编排：项目助手、Router、Pre-answer、IM-assist、Membrane reviewer、Render 等关键角色分工明确；不是单一大模型回答一切。
  · 提示注入防御 + 三层恢复梯度（JSON 模式 → 三次重试 → manual_review 兜底），落地于关键结构化输出路径。
  · 引文即证据（CitedClaim）：结构化事实句可以挂到图节点 / KB 节点；关键渲染与引用路径要求可点击回源，无引用或弱引用内容在 UI 和审核逻辑中被弱化处理。
  · 预答与选项生成：在路由抵达人之前，系统先基于目标成员的能力画像和项目上下文生成预答或 2–4 个结构化选项；如果问题需要真人判断，`human_answer_demand` 会显式承认模型不能代答。
  · 长上下文 + 膜抑制结合的注意力工程：canonical KB 检索默认排除 pending / archived 行；未审批候选不会作为团队事实进入默认上下文，只能以 review_pending / proposal 的身份被明确呈现。
- 项目中人和 AI 的分工是怎么样的？
  · AI 负责上下文整理、路由建议、记忆候选生成、结晶候选识别与文档渲染；服务层和 Membrane 决定哪些候选可以真正改变共享状态。
  · 人只做不可下放的判断：哪条选项被采纳、哪个异议被记录、哪个共识被追认、哪个边界被授权。
  · 这个分工是显式契约：每条决策行都记录"由谁判断"，每条共识行都记录"被谁追认"。AI 永远不冒充判断者。
- 项目中包含了哪些核心模型选型思路？
  · DeepSeek（OpenAI 协议兼容）作为主提供商：国内可达、成本低、合规友好。
  · 提示词 + JSON schema 与提供商解耦（provider-agnostic），随时切到 Kimi / 通义 / Qwen 等。
  · 对低延迟用例（预演卡、路由 inbound）固定温度 + 短 max_tokens；对叙述类（复盘 / 导览）放宽长度，温度仍受控。
- 引入 AI 后对原有工作流带来了哪些改变？
  · 协调单位从"文档"变成"轮次"——决策、问题、共识都成图上的节点和边，可以遍历、可以追溯。
  · 三个月后任何成员问"我们当时为什么这样选"，智能体直接从图给出因果链，不依赖任何人的记忆。
  · 跨成员对齐从"会议或长文档"压缩到"一次结构化路由询问"，平均 90 秒完成一次跨学科决策。
  · 外部信号（RSS / 网页 / 会议转录）经膜统一入图，带注入防御与 `proposed` 缓冲，绝不自动改写图谱。

5.其他任何信息补充
- 部署：单节点 Aliyun VPS（4 GB RAM）+ Cloudflare Tunnel 接入；容器组合 Nginx / Next.js 15 / FastAPI / Redis / SQLite。
- 测试：后端 683 个 pytest 全绿；前端 TypeScript 严格模式 + bun 单元测试覆盖核心 lib / 组件；每个智能体带 stub LLM 单元测试 + 恢复梯度覆盖。
- 可观测：`agent_run_log` 表 + trace_id 贯穿请求/工具/LLM 全链路，token 消耗、延迟、重试次数全记录。
- 国际化：next-intl 全站中英双语，KB 按用户偏好语言过滤，演示数据覆盖 EN + ZH 双项目。
- 后续路线：v2 计划支持 500+ 人组织（基于子图切片的执照分发），更深的 Feishu 适配器（在 Feishu 已有用户面前以"群体智能层"形态嵌入而非取代）。




（二）小组成员各自负责部分信息
要求：每个小组同学都需完成个人负责部分展示
你所负责核心or亮点部分的demo和代码
陈个人负责部分展示
主导产品设计全流程，主要负责产品开发——涵盖产品定义、技术架构、AI 工程、前后端实现、部署上线与演示数据建设的全流程独立交付。

1 产品理念与系统设计
- 提出并落地"轮次即基元、图谱即状态"的协调本体重构（详见 docs/north-star.md），把过去十年"以文档为信息单位"的协作工具范式转译为"以图节点 + 路由边 + 受治理状态转化为协调原语"的新范式。
- 设计并推动当前三图架构落地：World Graph 维护共享事实、知识、决策、风险与约束；Org Graph 维护成员、责任、能力证据与路由可信度；Work Graph 维护任务、路由、交接、评审与状态转化。Membrane 保护三张图的可信度，Transition Contract 与 Epistemic Event Contract 让每次状态转化具备 evidence_refs、authority、review_method、mutation_service 与 lineage_output。
- 设计并落地一组群体级原语：项目助手、路由、预答、Flow Packet、决策结晶、异议、Membrane review、KB 引文、Org Capability Trust Ladder、Handoff render、图谱审计等；其中部分前沿原语保持 projection-only 或实验性状态，文档中明确区分真实上线能力与后续路线。

2 AI 工程
- 设计并落地多智能体 / 多契约 LLM 编排：项目助手、Router、Pre-answer、IM-assist、Membrane reviewer、Render 等核心角色拥有独立提示词、结构化输出 schema 与统一恢复梯度 (JSON 模式 → 三次重试 → manual_review 兜底)。
- 落地"膜作为共享状态边界"的工程纪律：KB / 任务升级 / 决策 / 手工房间 / 技能 / 邀请等核心共享状态路径由 domain service + Membrane/Transition Contract 管控；低风险 owner 操作允许 auto_merge，但仍保留审计线索，避免出现绕过共享图谱治理的第二条写入捷径。
- 设计并实现"引文即证据"的产品级幻觉防御：结构化事实句支持绑定图节点 / KB 节点；关键引用链路可点击回源（决策 / 任务 / KB 三类节点），无引用或弱引用内容不被等同为 canonical fact。

3 后端实现 (Python / FastAPI / SQLAlchemy / aiosqlite)
- 33 张 ORM 表 + 50+ 仓库类，覆盖流（StreamRow）/ 路由（RoutedSignalRow）/ 决策结晶（DecisionRow）/ 膜信号（MembraneSignalRow）/ 执照审计（LicenseAuditRow）/ 异议（DissentRow）/ 隐性共识 / 代理对辩 / 知识库分层与单条执照 / 会议转录 / 第一天导览状态等。
- 实现 Flow Packets 投影读模型：把多种异构源行（KB / Task / Decision / IMSuggestion）统一投影为含 transition_contract + epistemic_event 的 FlowPacket，FE 不再直接读源行。
- 后端测试 683 个全绿，覆盖 signal-chain / streams / routing / personal / skills / kb / drift / membrane / render / ws 全链路。

4 前端实现 (Next.js 15 / React 19 / TypeScript / next-intl)
- 主战场页（/projects/[id]）：预演卡（1 秒实时刷新草稿分类）、工具调用可见化、路由提议卡、决策结晶 ⚡ 卡片、漂移提示卡。
- 全站中英双语（next-intl），KB 按用户偏好语言过滤，复盘 / 交接渲染同样按语言切换。
- React Flow 图谱可视化 + 时间倒带条 + 节点详情页 + 任务/风险/决策/冲突/事件多视角投影。

5 演示数据与部署
- 设计并使用 DeepSeek 自动生成 ZH + EN 双语演示数据集（Moonshot Studios 6 人独立游戏团队场景），覆盖十条任务、四条里程碑、四条风险、三条决策、二十个维基页面，保证演示可重现。
- 单节点上线：Aliyun VPS（4 GB RAM）+ Cloudflare Tunnel + Nginx + Docker Compose；docs/handoff_demo.md 记录所有暖缓存 / 健康检查 / 出意外应急路径。

6 工程纪律
- 所有路由保持"瘦"原则：pydantic 校验 → 成员闸 → 服务调用 → 服务异常 → HTTP 状态码，不在路由里写业务。
- 所有 LLM 实例化集中在 packages/agents/，服务编排 / 数据库写 / 事件发射在 services/，永不混杂。
- 设计系统（DESIGN.md）作为视觉决策的单一来源，禁止内联 hex 字面量，所有视觉决策可被代码审计。



张个人负责部分展示
深度参与产品理念讨论与产品定义共建；主要负责产品 QA 与全路径 dogfood、产品 UI 设计与视觉方向决策、demo 视频产出；未写代码。从 HR 视角对未来产品如何承载人才识别、团队协作与长期合作做了贯穿性的思考与建议。

1 产品 QA 与全路径 dogfood
- 在每一轮迭代后亲自走完 demo 主路径（登录 → 团队会议室决策芯片 → 个人流路由询问 → 4 秒选定回复 → ⚡ 决策结晶 → 知识库引用 → 复盘文档自动渲染），充当真实评审视角的代理。
- 发现并反馈的产品级问题（部分实例）：决策芯片不可点击 → 改为 Link、个人流路由 inbound 把代理身份当作发起人显示（"🧠 Edge"）→ 推动后端字段水合 + 前端来源人优先级修正、复盘 Markdown 中 **D-<id>** 引用未跳转 → 引用全部接入可点击节点详情、KB 引用 404 → 修复 citation kind → 走 /kb/[id] 路由、复盘缓冲未暖导致首次调用 30 秒空白 → 录前固化 warm-up curl 流程到 docs/handoff_demo.md。
- 双语 dogfood：分别以中文项目（Moonshot Studios）和英文项目走相同主路径，发现并反馈 zh 时间戳显示 "GMT" 三个大写字母刺眼（→ 改为 GMT+8 直接展示）、framing 在跨语言路由时需要保留 framingNote 提示等。
- 提出"先把骨架走通，再把组件放进去"的工作纪律——避免把组件硬塞进错的骨架（详见 memory/feedback_port_shell_before_widgets）。

2 产品 logo 设计
[图片]
GraphFlow 产品 logo 解读：Logo 以产品名首字母「G（Graph / 图谱）」与「F（Flow / 流）」为原型，采用无缝交织的共生设计，直观传递"图谱化协作 + 流畅工作流"的双核心逻辑。
G 的环形轮廓呼应"图谱"属性，打破传统表格与线性流程的割裂感，象征协作中决策、知识、任务相互连接，形成可遍历的动态网络，让信息不再孤立；F 的流线延伸呼应"流"的内核，传递多人与 AI 协同的无缝衔接，上下文信息自然贯通，无流程断点。
蓝白渐变配色中，科技蓝承载理性可信的 AI 工具属性，白色传递开放包容的协作氛围；渐变光影模拟信息流流动质感，暗含 AI 聚合信息、激活静态内容的过程。整体无断点的流线造型，以简约高级的视觉语言，诠释"协作即图谱"的核心理念。

3 网页 UI 设计与视觉方向决策（"UI bargain"）
- 在每一轮迭代节点上与开发方做视觉权衡（"bargain"）：哪些信息以稠密表格表达（任务 / 风险 / 决策详情），哪些以稀疏对话表达（个人流），哪些以图谱形态表达（图视图、节点详情）。最终落到三层投影并存的设计原则：图本身 + 流（轮次叙事）+ 表（稠密审计）。
- 主张并坚持"流的留白"——在主战场（个人项目流）上，避免把工具调用展开为强视觉单元，使用折叠卡 + 单行单色，让对话线条本身成为主导节奏；这一决策直接体现在 EdgeReplyCard / ToolCallCard 的视觉密度上。
- 主张并坚持"决策结晶 ⚡ 必须有可识别的视觉地位"——和普通气泡明显不同，让用户一眼看到"这是关键时刻"。
- 配色方向：蓝白渐变作为产品主线（与 logo 一致），琥珀 / 暖纸色（var(--wg-paper) / var(--wg-amber)）作为温度（DESIGN.md 与 PWA themeColor 同步），红色仅用于真正阻塞的状态。
- 移动端优先级判断：v1 不做移动端原生体验，但保留 PWA 元数据（manifest + apple-touch-icon）以便后续低成本扩展。

[图片]（首页 / 项目主战场）
[图片]（决策结晶 + 路由 inbound）
[图片]（图谱可视化 / 节点详情）

4 产品测试与回归
详见 Graphflow 产品迭代记录。
- 在每一次大功能上线后，对核心 8 个场景（见 docs/demo_script.md）做完整跑通，并把发现的问题反馈给开发方，进入下一轮回归。
- 维护 docs/handoff_demo.md 中"出意外时怎么办"的应急表（页面加载慢 / 决策芯片不可点 / pending review 丢失 / postmortem 长时间转圈 / inbox 空 / 整站挂 / 网络断），让 demo 录制不依赖单点。
[图片]

5 产品概念辩论（参与共建的部分）
- 与开发方在多轮讨论中共同确立"轮次（turn）作为协调基元"取代"文档 / 消息"的产品定位（详见 docs/north-star.md），坚持产品要走"群体（group）层"而非"个人（individual）副驾驶（copilot）"路线（详见 memory/project_positioning_group_not_individual）。
- 推动"决策结晶 ⚡ 是产品最重要的视觉与逻辑装置"成为团队共识，确保即使在压缩演示时间内，也保留"⚡ 结晶 → 血缘 → 复盘引用"这条主线不被切掉。
- 推动"主页面 = 个人项目流（chat-centered）而不是多面板控制台（panel-centered）"的设计选择（详见 memory/project_surface_chat_centered），避免落入传统协作工具的视觉惯性。

6 HR 视角与未来合作的产品承载
张作为 HR 实践者，在多次讨论中提出："如果这个产品真正落地，它要承载的不是一次性的协作，而是组织的长期人才识别与团队协作演化"。基于这一视角，与开发方共建了以下产品承载点（落到代码与 schema）：
- response profile（响应画像）作为一等公民：每位成员的"自述能力 + 观察发射 + 角色"三维数据结构（详见 docs/north-star.md "Profile as first-class primitive"），使绩效从"年度叙事"逐步过渡到"可观察数据集"。
- 技能图谱 / `/projects/[id]/skills` 双层模型：角色技能（随岗位传承）+ 个人技能（入职自述 + 工作观察验证）。绿色徽章为双重验证、琥珀色为未验证声明。
- 交接 = 画像迁移：handoff 渲染从图谱中抽取"该成员承担的边"，使继任者继承的是关系槽，而非姓名（落地于 RenderAgent 的 handoff slug）。
- 异议（dissent）作为一等公民：让"判断质量"可被长期观察，避免大模型时代的"橡皮图章"陷阱（详见 docs/north-star.md "honest caveat" 段）。

以上四点是 HR 视角对产品最重要的输入：让 GraphFlow 不只是一个"让今天的协作更顺"的工具，而是一个"让团队长期观察彼此判断"的认识论装配线。这部分 PRD 与文案以"长期合作"框架贯穿，被开发方接受并落到 V3 / V4 的实际功能（dissent、silent consensus、第一天导览、技能图谱、handoff = profile transfer）。
三、其他信息
