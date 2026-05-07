<p align="center">
  <img src="apps/web/public/brand/logo-mark.png" alt="GraphFlow" width="120" />
</p>

<h1 align="center">GraphFlow</h1>

<p align="center">
  <strong>以图谱（而非文档）为协调本体</strong>
  <br />
  群体层协作平台 · 为 AI 时代而生
</p>

<p align="center">
  <a href="https://graphflow.flyflow.love"><img src="https://img.shields.io/badge/在线演示-graphflow.flyflow.love-2563eb" alt="Live demo" /></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License" /></a>
  <a href="./README.md"><img src="https://img.shields.io/badge/English-README-red" alt="English" /></a>
</p>

<p align="center"><a href="./README.md">English README →</a></p>

---

## 核心论断

过去十年，协作工具的迭代都建立在同一个前提上：**信息的单位是文档**。Notion、飞书、Slack 都围绕这一点展开。这在 AI 到来前是合理的——只有"冻结的快照"能在多人之间承载共享意义。

AI 改变了底层。协调层本身开始能思考、路由、记忆、结晶。所以信息的单位必须切换：**从文档变成"轮次（turn）"**。每一次对话、每一次询问路由、每一次决策接受，都是图上的一个节点或一条边。文档是这些轮次累积后的自动渲染产物——不是输入。

GraphFlow 是知识工作的第一台**认识论装配线**：工作流是主体，人是其中承载判断的节点，AI 层负责节点之间的上下文保全。

> "Ford 没有发明汽车。他发明的是把工人摆进装配线、让工人成为线上节点的工作流。生产力提高了 10 倍。
> 知识工作至今仍处在 pre-Ford 时代。"

---

## 在线演示

**站点：** https://graphflow.flyflow.love
**演示项目：** Moonshot Studios —— 6 人独立游戏团队、距发售 4 周，围绕 Boss 难度 / Switch 性能 / 永久死亡机制三个核心权衡展开。
**演示账号** （`raj_zh` / `aiko_zh` / `maya_zh`）—— 密码见 `scripts/demo/seed_moonshot.py`。
**演示脚本：** [`docs/demo_script.md`](docs/demo_script.md) —— 8 个场景、约 7 分钟。

90 秒核心叙事：Raj 在自己的个人流里输入一个问题 → 子代理识别为可路由 → 带结构化选项路由给 Aiko → Aiko 4 秒选定回复 → Raj 接受 → ⚡ 决策结晶为图谱节点，血缘完整。**零会议、零文档书写。**

---

## 三张图（Three Graphs）

GraphFlow 把一个团队建模为三张图的交集：

| 图 | 承载内容 | 回答的问题 |
|---|---|---|
| **World Graph（世界图）** | 共享背景、知识、决策、风险与约束 | "团队知道什么？已经决定了什么？什么在赌？" |
| **Org Graph（组织图）** | 成员、责任继承、能力证据（Trust Ladder）、路由可信度 | "谁负责？谁在这件事上可信？" |
| **Work Graph（工作图）** | 任务、路由边、交接、评审、状态转化 | "什么在跑？跑到哪里了？落在谁身上？" |

三张图的交点是每位成员的**个人项目流**——他们唯一真正交互的界面。图谱才是产品本体；聊天只是人与图谱交互的方式。

---

## 核心原语（V1 已上线）

- **每位成员一个全局子代理。** 跨项目、长期持有，承载用户上下文、调用技能、起草回复、提议路由。
- **路由取代会议。** 一个问题 + 2-4 个结构化选项 + 权重，几秒内回复。落到图上是一条带血缘的边。
- **决策结晶 ⚡。** 每一次被接受的决定成为图上的永久节点，含来源、选项、理由、影响范围。三个月后再问"我们当时为什么选这个"，图谱直接给出因果链——不依赖任何人的记忆。
- **膜（Membrane）作为单一边界。** 所有进入群体共识的写入——KB 条目、任务晋升、决策结晶、房间创建、技能/邀请变更——都过同一道闸门。新增写入种类只是扩展枚举，永远不开第二条路。
- **引文即证据。** 子代理的每一条主张都带结构化引文，指向图节点或 KB 节点。无引文的断言会被视觉削弱，永远不会被隐藏。
- **5 级 Trust Ladder。** 能力是对证据的投影：声明（declared）/ 角色（role）/ 观察（observed）/ 验证（validated）/ 信任（trusted）。技能永远不从行文本里被发明出来。
- **异议即一等公民。** 成员可以对任何决策记录结构化异议，后续真实结果会标注异议为 supported / refuted / still-open。判断质量因此变得可被长期观察。
- **隐性共识（Silent consensus）。** 当 ≥3 名成员在 7 天窗口内围绕同一交付物作出一致行为且无异议，扫描器自动抛出"提议"等待追认。
- **代理对辩（Agent-vs-agent scrimmage）。** 路由请求抵达人之前，双方子代理先辩论 2-3 轮。收敛 → 直接生成待追认决策；不收敛 → 把对立摘要交给人——人类永远不会收到一个空白问题。
- **主动感知膜（Active membrane ingestion）。** 外部信号（RSS / 网页 / 网络搜索 / cron）经膜统一入图，带提示注入防御，始终 `proposed` 状态等人类确认。
- **会议转录元消化。** 上传转录（飞书妙记 / Zoom / 粘贴文本），膜抽出决策 / 任务 / 风险 / 立场作为"提议"，绝不自动改写图谱。

---

## 技术栈

| 层级 | 选择 |
|---|---|
| Web | Next.js 15（App Router）、React 19、TypeScript 严格模式、next-intl（中英双语） |
| API | FastAPI · Python 3.11 · SQLAlchemy + aiosqlite |
| 实时 | FastAPI WebSocket + Redis 发布订阅 |
| 存储 | SQLite（单节点）、33+ ORM 表、13+ Alembic 迁移 |
| LLM | DeepSeek（OpenAI 协议兼容）—— 提示词与提供商解耦 |
| 可视化 | React Flow（图谱画布）、PixiJS（少数动画时刻） |
| 部署 | 单 VPS · Cloudflare Tunnel · Nginx · Docker Compose |
| 可观测 | 结构化日志、端到端 `trace_id`、每次 LLM 调用记 `agent_run_log` |

13 个专职 LLM 代理分担不同职责：`EdgeAgent`（子代理）、`MembraneAgent`（外部信号分类 + 注入防御）、`MembraneReviewer`（语义审查）、`ClarificationAgent`、`PlanningAgent`、`DriftAgent`、`RenderAgent`、`PreAnswerAgent`、`ConflictExplanationAgent`、`IMAssistAgent`、`MeetingIngestService`、`DeliveryAgent`、`RequirementAgent`。每个代理都带版本化的提示词 + 结构化输出 schema + 恢复梯度（JSON 模式 → 三次重试 → `manual_review` 兜底）。

---

## 快速上手

依赖：**Python 3.11**、**uv**、**bun**（或 **npm**）、Redis（开发可选）。

```bash
# 后端
uv sync
cp .env.example .env  # 配置 DEEPSEEK_API_KEY
uv run alembic -c apps/api/alembic.ini upgrade head
uv run uvicorn workgraph_api.main:app --reload --port 8000

# 前端
cd apps/web
bun install
bun dev   # localhost:3000

# 测试
uv run pytest                    # 后端 683/683 全绿
cd apps/web && bun test          # 前端单元测试
```

种子演示数据：

```bash
uv run python scripts/demo/seed_moonshot.py        # Stellar Drift / Moonshot Studios
```

---

## 仓库结构

```
apps/
  api/               FastAPI —— 路由、服务、智能体接驳
  web/               Next.js —— app router、组件、国际化
  worker/            Celery —— 异步 agent 运行
packages/
  agents/            13 个 LLM 代理 —— 提示词、schema、恢复梯度
  domain/            EventBus、实体 schema
  persistence/       SQLAlchemy ORM、仓库类、Alembic 迁移
  schemas/           共享 Pydantic DTO
  observability/     结构化日志、trace_id 传播
  orchestrator/      工作流阶段逻辑
  feishu_adapter/    飞书集成（v2 计划）
docs/
  north-star.md           当前产品意图（最优先读）
  architecture.md         架构可视化总结
  competition.zh-CN.md    参赛叙事
  demo_script.md          7 分钟演示脚本
  flow-packets-spec.md    Flow Packets v1.1 规格
  membrane-reorg.md       膜·单一边界论
deploy/
  docker-compose.yml、nginx 配置、Alembic 部署辅助
```

**最优先阅读：** `docs/north-star.md`。这是当前产品意图。`PLAN.md`、`docs/dev.md`、`AGENT.md` 等带归档横幅的文档是 MVP 时代的历史记录，不是当前规格。

---

## 状态

V1 已上线。V2 → V4 全部功能（异议、隐性共识、代理对辩、第一天导览、分层 KB、会议转录元消化、执照感知回复、Org Graph Trust Ladder、Epistemic Event Contract、Membrane 语义审查 M1–M5.1）截至 `2026-05-07` 全部已上线。

后端 683 个测试全绿。前端 TypeScript 严格模式。生产环境：单 VPS、Cloudflare Tunnel、阿里云国内节点，已稳定运行约 6 个月。

---

## 贡献

本项目最初是参赛作品，现在作为开源实验对外。欢迎贡献——请先阅读 `docs/north-star.md` 理解产品意图。把产品拉回"Notion + AI"或"ChatOps"范式的 PR 会被礼貌地引导回来。

架构不变量（被测试与 CI 强制）：

1. **路由瘦原则** —— pydantic 校验 → 成员闸 → 服务调用 → 状态码。路由里不写业务。
2. **膜是唯一边界** —— 所有进入群体共识的写入都过 `MembraneService.review()`。新增写入种类只扩展 `CandidateKind` 枚举，永远不开第二条路。
3. **LLM 编排集中在 `packages/agents/`** —— 所有 `LLMClient` 实例化在那里。服务负责编排，代理负责调 LLM。
4. **执照闸单一来源** —— 层级过滤过 `LicenseContextService`；回复经 `lint_reply()` 校验。

---

## 许可证

MIT —— 详见 [`LICENSE`](LICENSE)。

---

## 致谢

作为字节跳动参赛作品而生。最大智识债欠 [North Star 文档](docs/north-star.md)，以及关于"知识图谱即状态"、多代理编排、群体信念模态逻辑的现有工作。

品牌标识是"G + F"无缝交织——Graph + Flow——作为一个连续整体的造型，呼应产品论断：协作应该是图谱之上的一段连续流，而不是一摞割裂文档的堆叠。
