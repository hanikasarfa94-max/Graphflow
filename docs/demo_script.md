# GraphFlow 复赛 Demo 脚本

录制目标：7 分钟，竞赛复赛 Demo 提交。
基线团队：Moonshot Studios（《Stellar Drift》Season 1 发版团队，7 人跨职能）— 这是产品里已 seeded 的 demo 项目，所有数据真实。
品牌：GraphFlow（Topbar / 侧栏 logo / 页面标题已正式化）。
技术栈：DeepSeek 在产品运行时承担项目助手 / Router / IM-assist / Membrane 等 Agent 角色；前端 Next.js 15；后端 FastAPI + SQLite + Alembic；部署在阿里云 + Cloudflare Tunnel（graphflow.flyflow.love）。

---

## 0. 录制前清单（开机 30 分钟内做完）

### 0.1 数据 / 状态预热

打开终端，确认以下 4 件事，**任何一件未准备好就别开录**。

```bash
# (a) 给 cookie 续命，登录态新鲜 — 用 maya_zh（zh demo 项目 owner）
PROD=https://graphflow.flyflow.love
curl -c /tmp/cast_cookie.txt -b /tmp/cast_cookie.txt -L -d 'username=maya_zh&password=...' "$PROD/api/auth/login"
PID=e749cfad-304f-436e-843e-04df8e1f3355

# (b) 暖一下 postmortem render 缓存（首次生成调 LLM ~30s，不能让评委看进度条）
curl -b /tmp/cast_cookie.txt "$PROD/api/projects/$PID/renders/postmortem" -m 120 -o /dev/null

# (c) 暖一下 handoff 文档缓存（第二个 render 切片）
JAMES_ID=$(curl -sb /tmp/cast_cookie.txt "$PROD/api/projects/$PID/state" | python -c "import sys,json;print([m for m in json.load(sys.stdin)['members'] if m.get('username')=='james_zh'][0]['user_id'])")
curl -b /tmp/cast_cookie.txt "$PROD/api/projects/$PID/renders/handoff/$JAMES_ID" -m 120 -o /dev/null

# (d) 给个人任务列表加 1-2 条，避免 /detail/tasks 完全空白
# （走 chat 让项目助手自己提议，更自然；详见 Scene 4 备用脚本）

# (e) 今日版本关键探针：确认新不变量真的在线
curl -b /tmp/cast_cookie.txt "$PROD/api/projects/$PID/flows?limit=5" | python -c "import sys,json;d=json.load(sys.stdin);p=(d.get('packets') or [])[0];print('transition_contract' in p, 'epistemic_event' in p)"
curl -b /tmp/cast_cookie.txt "$PROD/api/projects/$PID/capabilities" | python -c "import sys,json;d=json.load(sys.stdin);print('capabilities_ok', bool(d.get('members') or d.get('items') or d))"
```

### 0.2 浏览器准备

- Chrome 全屏 1440×900（评委界面常见）
- 关掉所有扩展（防止突然弹通知）
- 字体放大到 100%（不要 90%，截图会模糊）
- 打开 4 个 tab，按下面的顺序固定：
  1. `/`（首页）
  2. `/projects/{PID}`（个人流主面）
  3. `/projects/{PID}/team`（团队会议室）
  4. `/projects/{PID}/detail/graph`（图谱视图）
- 清空 inbox 右上角 badge（点开过一次就行）
- 检查侧栏：项目展开后能看到 ☁ 我的会话 / ♟ 团队会议室 / 群组 / ▣ 状态 / ⌬ 组构 / ▥ 知识库 / ✣ 技能图谱 / ▤ 渲染文档 / ⌕ 审计视图

### 0.3 录制工具

- OBS Studio，1080p / 60fps
- 麦克风 noise gate 打开
- 鼠标高亮（小圆点跟随）
- 打字时屏幕键 overlay（可选）
- 备一个第二台电脑，开 stopwatch，每个 Scene 倒计时

### 0.4 保险准备

- **如果录制中产品挂了**：切到本地 `npm run dev` 备份环境，提前确认本地是同一 commit
- **如果 Membrane 审核 IMSuggestion 没出现**：直接打开 `/api/projects/{PID}/membrane/notes` 让评委看 JSON 也是有效的（"我们的 Membrane 不是 UI 装饰，是 BE 真实的状态机"）
- **如果 LLM 回答太慢**：备 Plan B 录像 — 提前录好"理想路径"的 30s 切片，必要时切过去
- **如果界面还出现"🧠 Edge / Edge 的新路由询问"**：不要开录。这说明 routed-inbound attribution 修复没有部署完整，必须等到显示"某某 通过项目助手询问你"。

---

## 1. 总时间预算

| Scene | 时长 | 类型 | 内容 |
|---|---|---|---|
| 0 | 0:00–0:20 | AI-gen 视频 | 开场情境 |
| 1 | 0:20–0:50 | 真实产品 | 登录 + 个人流 + 路由收件箱 |
| 2 | 0:50–1:50 | 真实产品 | 团队会议室 + Crystallize 决策 |
| 3 | 1:50–3:00 | 真实产品 | Save-to-Wiki + Membrane 审核 |
| 4 | 3:00–3:50 | 真实产品 | KB 详情 + 引用 |
| 5 | 3:50–4:30 | AI-gen 图 + 旁白 | 三张图 + 认知事件解释 |
| 6 | 4:30–5:30 | 真实产品 | 图谱视图 + 跨引用 |
| 7 | 5:30–6:30 | 真实产品 | Postmortem render + 引用 |
| 8 | 6:30–7:00 | AI-gen + 真实 | 闭幕愿景 + URL |

总时长：**7:00**（弹性 ±20s）。

---

## 2. Scene 0（0:00–0:20）开场情境 — AI-gen

### 2.1 视觉

一个分散在不同时区的游戏工作室，主画面分成 6 个小窗口，每个窗口是一位成员在自己的桌面上工作（程序员看代码、美术看 Figma、QA 看 bug 列表、PM 看 Slack 消息流）。镜头慢慢拉远，6 个窗口连成一张半透明的图，节点之间出现连线。背景音乐：电子环境音渐起。

### 2.2 旁白（zh 主，约 20s）

> 一个 7 人的游戏工作室，正在 6 周内做一款 Switch 平台的独立游戏。
>
> 决策散落在聊天里。知识停留在某个人的 Notion。任务靠口头交接。
>
> 直到 GraphFlow——

### 2.3 屏幕字幕（双语显示）

- zh：当协作变成图，每一次对话都不再消失。
- en：When collaboration becomes a graph, no decision gets lost.

### 2.4 AI-gen Prompt（用于 Sora / Veo / Pika）

```
A cinematic split-screen view of 6 remote game studio team members working in their own home offices, each in a different time zone (one with morning sunlight, one with evening lamps, one with a city skyline at dusk). Each person works on a different device: programmer at a multi-monitor setup, artist at a Cintiq tablet, QA tester with a Switch dev kit, project manager scrolling Slack on a laptop. The 6 windows are arranged in a 3x2 grid, separated by thin gold lines.

Camera movement: starts close on the PM (Asian woman in her 30s, focused expression) reading endless chat threads, then pulls back smoothly over 8 seconds to reveal all 6 panels, then continues pulling back further as a translucent network graph overlays the entire scene. Nodes appear over each person's window and connect with glowing amber lines. The graph stabilizes in the final frame.

Lighting: warm cream and amber accents (matching brand palette #b5802b). Soft cinematic, never harsh. Slight film grain.

Style: clean, modern documentary feel. Think Apple keynote meets a thoughtful indie studio doc. NOT slick corporate. NOT chaotic.

AVOID: visible chat bubbles with English text, generic startup imagery, AI-generated faces with uncanny eyes, dramatic music cliché, animated emojis, cyberpunk neon.

Aspect ratio: 16:9. Duration: 20 seconds. Loopable in last 2 seconds for safety.
```

---

## 3. Scene 1（0:20–0:50）登录 + 个人流 + 路由收件箱 — 真实产品

### 3.1 屏幕动作

1. 浏览器在登录页，已填好 `maya_zh` / 密码。点 **登录**。
2. 跳转到首页 `/`。镜头停 3 秒看主体。
3. 鼠标移到页面 hero 区，特别是 "{count} 项待确认" 数字上。
4. 点 hero 上的"处理路由收件箱（{count}）"按钮。
5. 跳到 `/inbox`。镜头停 4 秒看 routed signals 列表。

### 3.2 旁白（zh，约 30s）

> 这是项目 PM Maya 早上 9 点登录 GraphFlow 的第一眼。
>
> GraphFlow 不只展示列表——它告诉她：哪些信号需要她处理。
>
> 不是 7 万条消息的红点提醒，是 3 件按"系统认为你最适合"路由给她的具体待办：第一件是 Sofia 提交的玩家试玩报告，第二件是 James 在群组讨论的 NAT 回退方案，第三件是合规组对 Switch 性能预算的反馈。
>
> 每一条都已经被项目助手预处理：包含上下文、关联节点、建议动作。

### 3.3 关键截图点

- 首页 hero 的 "{count} 项待确认" 数字（突出"系统脉搏"）
- 路由收件箱中"路由给你的"区，显示"智能路由"标签
- 如果出现 routed-inbound 行，来源必须是"陈梅雅 / 中村爱子 通过项目助手询问你"，不能再出现"🧠 Edge"。

### 3.4 备用文案（如果 routed inbox 是 0）

> Maya 今天的 inbox 是空的——这才是 GraphFlow 期望的状态。它不是想让你不停接受推送，而是当真的需要你介入时，才打扰你。

---

## 4. Scene 2（0:50–1:50）团队会议室 + 决策已结晶 — 真实产品

> **修正**：原稿写的是"用户手动 Crystallize"，但实际产品的 UX 是"IMAssist Agent 在后台分类消息 → 给出 suggestion 卡 → 用户 Accept/Counter"。manual Crystallize 入口只在 routed-inbound 卡片上有，团队会议室消息走的是建议-审核路径。所以本 Scene 改为"展示已经结晶的决策"，narration 主打 smallest-relevant-vote。

### 4.1 屏幕动作

1. 点侧栏的 ♟ 团队会议室（或直接 nav 到 `/projects/{PID}/team`）。
2. 镜头停 3 秒看顶部 chrome（Topbar / ProjectModuleRail / 团队会议室标题 + 范围 pills + 绩效 →）。
3. 滚动消息流，停在 Sofia 的消息上（"First external playtest done. 3 of 5 testers said..."）。
4. 滚到 Aiko 的消息（"Looked at Sofia's report. Main cause looks like permadeath..."）。
5. 镜头停在 Aiko 消息底部的 **⚡ 已生成决策** 芯片上 3 秒。
6. **点这枚芯片**——跳转到 `/projects/{PID}/nodes/{decision_id}`（决策详情页）。
7. 镜头停 5 秒看决策详情：H1 决策标题 / basics（含 scope_stream_id = 团队会议室）/ rationale / lineage（来源消息）/ Dissent。
8. 关键截图：scope 标签写"团队会议室 · 7 人 quorum"。
9. 返回团队会议室。镜头扫过其他几条消息——也有同样的 ⚡ 芯片。

### 4.2 旁白（zh，约 60s）

> 团队会议室是项目里最重要的协作面。但和 Slack 频道不同的是——这里每条对话都不会消失，IMAssist Agent 在后台读每条消息，识别出哪些是闲聊、哪些是值得记录的决策。
>
> 看中村爱子这条消息：她对 Sofia 的玩家报告做出了诊断——Boss 战的永久死亡机制对新手玩家过于严苛。这不是闲聊，这是一个值得记录的设计判断。
>
> IMAssist 已经识别出这条消息的决策含义，团队的某位 Owner 在审核 inbox 里 Accept 了它，DecisionRow 已经写入。看消息底下的 ⚡ 已生成决策 芯片——这是图谱节点的入口。
>
> 点击芯片，跳到决策详情页。这里能看到 GraphFlow 的关键设计：**决策范围由消息所在的流决定**。Aiko 在团队会议室发的消息 → 决策只问会议室的 7 个人，不会广播给整个项目。我们叫它 smallest-relevant-vote——只问最相关的人。
>
> 决策详情页保留了完整的 lineage（来龙去脉）：来源消息、提议者、确认者、投票 quorum、是否有异议（Dissent）。

### 4.3 关键截图点

- Aiko 消息底下的 ⚡ 已生成决策 芯片（hover 时鼠标变成手指 + 出现 tooltip "查看决策详情:范围、quorum、来龙去脉"）
- 决策详情页 H1 + basics 区的 scope_stream_id（写"团队会议室 · 7 人 quorum"或类似）
- lineage 板块显示从消息到决策的链路

### 4.4 技术细节（不要在录制里说，但脚本里留作背景）

- BE: 用户在原始消息上点芯片 → Link 到 `/projects/{PID}/nodes/{decision_id}`（cycle 4 修复，原本是 label-only span）
- IMAssist Agent 后台异步分类消息，produces `IMSuggestion(kind="decision", confidence>=0.6)`
- 用户 Accept 时，`im.py` 的 `handle_accept` → `DecisionRepository.create()` → stamp `scope_stream_id = source_msg.stream_id`
- `decision_votes.py` 用 scope_stream_id 决定 quorum：项目 vs 会议室 vs sub-room

---

## 5. Scene 3（1:50–3:00）Save-to-Wiki + Membrane 审核 — 真实产品

### 5.1 录制前 30 秒预热（重要！）

这一 Scene 需要 **一个待审 KB 草稿**才能演示。**不要靠 `@edge` 这种聊天命令** —— 没有专门的 mention 解析器，项目助手是否真的调用 `propose_wiki_entry` 取决于它自己的判断。可靠做法是走 FE 的 Save-to-Wiki 真实路径：

```text
录制前手动操作：
1. 登录 maya_zh，进入团队会议室 /projects/$PID/team
2. Hover 在罗西·索菲亚的"外部试玩"那条消息上
3. 点出现的「保存到 Wiki」按钮（💾 图标）
4. 浮层 → 确认
5. 切到 /projects/$PID/kb，确认 KB 树里出现「待审 / 去审批 →」chip
```

如果想程序化校验队列，可用：

```bash
PROD=https://graphflow.flyflow.love
PID=e749cfad-304f-436e-843e-04df8e1f3355
curl -b /tmp/cast_cookie.txt "$PROD/api/projects/$PID/membrane/notes" | python -m json.tool
```

确认 `pending_reviews` 至少 1 条再开始录。

### 5.2 屏幕动作

1. 切回团队会议室，鼠标移到 Sofia 的消息上。
2. 点消息上的 "Save to wiki" 按钮（💾 图标）。
3. 出现确认浮层："项目助手将把这条消息提议为团队 Wiki 条目"。点确认。
4. 浮层关闭，消息流右上角出现 toast："📥 已提议给团队审核"。
5. 镜头切到 `/projects/{PID}/kb`。
6. 在 KB 树里找到刚创建的草稿，标签是 **🔶 待审 · 去审批 →**。
7. 点这个 chip。跳转到 `/projects/{PID}/detail/im`。
8. 镜头停 3 秒看 Membrane 审核面板：title + summary + diff + 接受 / 忽略 / 反提 / 上报 4 个动作（zh-locale 按钮文案）。
9. 点 **接受**。
10. 状态卡片出现 "✓ 建议已接受"。
11. 切回 KB tree，刷新（或自动刷新），刚才那条没了草稿芯片，显示为正式条目。

### 5.3 旁白（zh，约 70s）

> 现在陈梅雅想把罗西·索菲亚的报告升级为团队知识。
>
> 她点 "保存到 Wiki"——但 GraphFlow 不会直接写入。项目助手把它包装成"候选"，送进 Membrane 审核队列。
>
> Membrane 是 GraphFlow 的核心架构不变式：**所有进入团队共享上下文的内容，必须经过同一个边界**。无论是 LLM 提议、用户保存、还是外部信号摄入——一个入口，一种审核。
>
> Membrane 的 4 状态：auto_merge（无冲突自动合并）、request_review（需要 Owner 审核）、request_clarification（提议人需要澄清）、reject（拒绝）。这条提议触发了 request_review，因为它是 LLM 提议的草稿，按设计 LLM 没有写入团队记忆的权限。
>
> Owner 在审核面板看到完整 diff，点 Accept——决议落地，KB 条目从草稿翻转为正式发布。
>
> 这一步是 GraphFlow 在 AI 时代解决的核心问题：**AI 帮你思考，但不替你做决定**。

### 5.4 关键截图点

- KB 草稿的 🔶 待审 · 去审批 → chip
- Membrane 审核面板的 4 个动作按钮（zh: 接受 / 忽略 / 反提 / 上报；en: Accept / Dismiss / Counter / Escalate）
- "✓ 建议已接受" 翻转效果

### 5.5 技术细节（背景，不要说）

- `KbItemService.create()` → membrane.review() → returns auto_merge or request_review
- 任何 status='draft' 的 group-scope 候选 → 自动创建 IMSuggestion 进入 inbox
- Accept handler → `KbItemRepository.update(status='published')`
- 这是 cycle 4 修复的 bug 路径——确保不变式真的覆盖所有入口

---

## 6. Scene 4（3:00–3:50）KB 详情 + 引用 — 真实产品

### 6.1 屏幕动作

1. 在 KB tree 里点刚接受的那条新条目（"外部试玩 Wave A 总结"）。
2. 跳到 `/projects/{PID}/kb/{item_id}`。
3. 镜头停 4 秒看页面：完整 title + 完整 content_md（**不是空态！**）+ 右侧 meta panel（来源 llm / 录入者 陈梅雅 / 状态 published / 分类标签）+ "记忆修复"卡片（owner 可见 Archive 按钮）。
4. 滚动看内容，停在"## 待决议：是否引入中盘纪念品复活机制？"那段。
5. 切到 `/projects/{PID}/detail/decisions`，找之前中村爱子消息结晶出的那条决策（关于 Boss 难度取舍）。
6. 镜头停在决策卡片，特别是 lineage 板块——显示决策的来龙去脉：来源消息 → 提议 → 投票 → 结晶。
7. 点 lineage 中的来源消息引用，跳回团队会议室对应消息（demo 这条引用闭环）。

### 6.2 旁白（zh，约 50s）

> 进入条目详情。注意：每条 KB 条目都包含 source（来源 chat / wiki / git / RSS）、ingested_by（哪位成员 / Agent 录入）、classification（自动打标签）。
>
> 这不是简单的笔记应用——这是带元数据的图谱节点。Owner 还可以在右侧"记忆修复"卡片上一键归档过时的条目，归档后立即从 Agent 上下文里淡出，但完整审计记录仍然保留——这是 GraphFlow 的"记忆是可修复的"承诺。
>
> 任何后续的 Agent 推理、决策结晶、风险检测，都可以引用这个节点。
>
> 看这条决策——它的来龙去脉清晰可见：起源于罗西·索菲亚的玩家报告，进入 Membrane 审核，通过后成为 KB 条目，再被中村爱子的设计讨论引用，最终结晶为团队决策。
>
> 这就是 "Graph IS the state"——不是给状态加列，状态本身就是图。

### 6.3 关键截图点

- KB 详情页完整内容渲染（不能是空态！cycle 4 修了这个 bug）
- 决策 lineage 页面：chat → KB → decision 的可视化路径
- 引用可点击（蓝色下划线）

---

## 7. Scene 5（3:50–4:30）三张图 + 认知事件解释 — AI-gen 图 + 旁白

### 7.1 视觉（AI-gen 静态图 + 简单动效）

一张"三图同构"概念图，画面中央是一个被 Membrane 包裹的项目 Cell，里面有三张互相套叠的图：

1. **World Graph（世界图）**：知识、决策、风险、约束、why-chain，颜色偏蓝。
2. **Org Graph（组织图）**：成员、角色、声明能力、观察能力、验证能力、可信能力，颜色偏绿。
3. **Work Graph（工作图）**：任务、路由、Flow Packet、交接、评审、状态转换，颜色偏琥珀。
4. **Membrane（膜）**：包裹三张图的半透明边界，外部信号进入时变成 announcement candidate，通过 auto_merge / request_review / request_clarification / reject。
5. **Router + 项目助手**：Router 是在图之间移动信号的"主动神经"；项目助手是用户接入共享图状态的局部界面。

整张图风格：cool-clinical 蓝白 blueprint paper，少量琥珀强调。画面不要像企业架构 PPT，要像一张可操作的组织认知仪表图。

### 7.2 旁白（zh，约 40s）

> 让我们退一步看 GraphFlow 的架构。
>
> GraphFlow 不是聊天，也不是任务表。它是一个动态组织认知系统。
>
> 第一张图叫 World Graph——团队共同承认的现实：知识、决策、风险、约束，以及为什么。
>
> 第二张图叫 Org Graph——谁在这里，谁能判断什么，谁的能力已经被工作验证。
>
> 第三张图叫 Work Graph——行动如何流动。注意，任务不是 todo item，而是一个被治理的状态转换：未知变成已判断，草稿变成团队计划，讨论变成决策。
>
> Membrane 是公告算子。AI 可以提出候选，但只有经过证据、权限、范围和审查之后，才会写入共享状态。
>
> Router 不是通知系统，而是上下文转换系统：它决定这条信号应该带着哪些证据，去问谁，要对方做什么判断，回来以后更新哪一张图。
>
> 所以 GraphFlow 的目标不是生成更多内容，而是在 AI 加速协作时，维持团队共同现实不失真。

### 7.3 AI-gen Prompt

```
A clean diagrammatic illustration of GraphFlow as a dynamic organizational cognition system. Style: technical infographic in the style of Edward Tufte meets a precise blueprint instrument. Background: pale blueprint paper (#f5f8ff), fine blue grid lines, deep navy ink, sparse amber highlights.

Main structure:

Center: one translucent project cell surrounded by a semi-transparent Membrane / 膜 boundary. The membrane has four labeled gates: auto-merge, request-review, request-clarification, reject.

Inside the cell, show three nested but visually distinct graphs:

1. World Graph / 世界图: blue nodes labeled knowledge, decisions, risks, constraints, why-chain.
2. Org Graph / 组织图: green nodes labeled members, roles, declared skill, observed skill, validated skill, trusted skill.
3. Work Graph / 工作图: amber nodes labeled routed signal, Flow Packet, task transition, review, handoff.

Show arrows between the graphs: accepted work updates World Graph, accepted replies update Org Graph capability evidence, World Graph context informs routing.

At the left edge, show "Project assistant / 项目助手" as a local interface beside one user, connected into the cell. At the top, show "Router Agent / 路由器" as a routing nerve moving a signal from one user to another with compressed context and evidence refs. Outside the membrane, show a messy message/document entering as "announcement candidate / 认知事件候选"; inside, after the membrane, it becomes "accepted-for-scope / 范围内承认".

Include a small contract strip at the bottom:
"LLM recommends → Membrane enforces → Domain services mutate → Lineage remains"

Typography: bilingual labels, English bold + smaller Chinese annotation. Minimal, technical, clean. No corporate clipart. No AI brain. No neon. No purple gradients. No decorative blobs.

Aspect ratio: 16:9, leave 20% bottom margin for caption text overlay.
```

### 7.4 备用图（如 AI 不出图）

退而求其次：录制屏幕展示 `graphify-out/graph.html`（646 communities 的实际图谱可视化）。这本来就是用 graphify 自动生成的，是真实数据。优势：是真的；劣势：信息密度过高，需要快速 zoom-in zoom-out。

---

## 8. Scene 6（4:30–5:30）图谱视图 + 跨引用 — 真实产品

### 8.1 屏幕动作

1. 切到 `/projects/{PID}/detail/graph`。
2. 镜头停 3 秒看图谱视图：节点（Decision 菱形 / KB 方形 / Task 圆 / Risk 三角）+ 边（带方向箭头）。
3. Hover 在一个 Decision 节点上，显示 tooltip：title + scope_stream_id + apply_outcome。
4. 点这个节点。右侧 panel 展开：决策详情 + 引用的 KB 节点列表 + 关联的 Task。
5. 在右侧 panel 点一个 KB 引用。图谱中相应节点高亮。
6. 切到 TimelineStrip（时间线），显示决策按时间序列：每个节点带时间戳。
7. 拖动 TimelineStrip 把时间游标拉回 4 月底。图谱节点根据 created_at 过滤。

### 8.2 旁白（zh，约 60s）

> 进入图谱视图——这是 GraphFlow 区别于其他协作工具的关键。
>
> 你看到的不是装饰，是项目的真实状态。World Graph 记录团队共同承认的背景和依据，Org Graph 记录谁的能力被工作验证，Work Graph 记录每个任务和路由正在把什么状态转成什么状态。
>
> 每个节点是一次写入团队上下文的认知事件：决策、知识、任务、风险。每条边是一次实际引用：决策 cite 了知识，任务依赖了决策，路由把判断送到最合适的人。
>
> Time-Cursor 让你可以倒带——拉到 4 月底，看那个时间点项目长什么样。决策还没结晶，几个 KB 还在草稿。
>
> 这不是事后画的架构图，是实时运行的状态机。
>
> 当评委问"为什么做这个决策"——答案在图里，不在某人的脑子里，不在埋藏的 Slack 历史里。

### 8.3 关键截图点

- 图谱视图：4 种节点形状 + 边的方向箭头
- Decision 节点的 tooltip 显示 scope_stream_id
- TimelineStrip 倒带效果

---

## 9. Scene 7（5:30–6:30）Postmortem 渲染 + 引用 — 真实产品

### 9.1 屏幕动作（**前提：postmortem 缓存已暖**）

1. 切到 `/projects/{PID}/renders/postmortem`。
2. 镜头停 4 秒看完整渲染的 postmortem 文档：项目目标 / Key decisions（含 lineage）/ Risks resolved / What we learned。
3. 滚动文档。**Key decisions 部分每条都有 `**D-<id>**` 蓝色下划线引用**。
4. 点一个 `**D-<id>**` 引用。跳到 `/projects/{PID}/nodes/{id}`，看对应决策详情页。
5. 返回。
6. 切到 `/projects/{PID}/renders/handoff/{james_user_id}`——给 James 准备的交接文档。
7. 镜头停 4 秒看 handoff 文档：包含 James 在项目中负责的 routine、未交接的 commitment、active tasks。

### 9.2 旁白（zh，约 60s）

> 项目结束时，Maya 一键生成项目复盘。
>
> 但这不是 LLM 凭空写的总结——每条 Key Decision 都带可点击的 `**D-<id>**` 引用，点回去就是真实的决策节点。
>
> 这是 GraphFlow 的 citation contract：**postmortem prompt 强制每条决策引用必须对应输入 decisions 列表里的真实 id，编不出来就只能写"(no recorded decisions)"**。
>
> 这是 AI 时代协作工具的诚信底线——不是"看起来对"，是"可以验证"。
>
> 同样的引用约束也用于 handoff——给 James 准备的交接文档列出他在项目中观察到的 routine、active tasks。新人接手不再依靠口头交接，每条事实都可追溯到图谱节点。

### 9.3 关键截图点

- Postmortem 文档里 **D-{id}** 引用可点击效果
- Handoff 文档里"James 负责的 routine"自动归纳

---

## 10. Scene 8（6:30–7:00）闭幕愿景 + URL — AI-gen + 真实

### 10.1 视觉

回到 Scene 0 的同一个 6 人分屏，但这次每个人脸上都是平静的专注表情。镜头慢慢从分屏拉远，6 个人之间的连线变得清晰、稳定。然后画面切到 GraphFlow 的 logo + 一行 URL：`graphflow.flyflow.love`。

### 10.2 旁白（zh，约 30s）

> 当 AI 让每个人都变快，团队最危险的不是信息不够，而是共享现实开始失真。
>
> GraphFlow 给出的答案是：让每个人通过项目助手接入同一张共享图；让 Router 把信号带着证据送到正确的人；让所有进入团队状态的候选，经过 Membrane；让任务、知识、决策都留下可追踪的状态转换。
>
> GraphFlow——**让团队在 AI 加速下，仍然知道同一个现实。**

### 10.3 屏幕字幕

```
GraphFlow
graphflow.flyflow.love

Coordination as a graph, not a document.
协作是一张图，而不是一份文档。

Shared state under AI acceleration.
AI 加速下的团队共享状态。
```

### 10.4 AI-gen Prompt（闭幕场景）

```
The same 6 remote game studio team members from the opening scene, now in a calmer state. Each person works in their own home office (same lighting as opening), but their expressions are focused, settled, in flow. Same 3x2 split-screen grid.

A network graph overlays the entire scene from the start, but this time the graph is fully formed and stable. Amber connections pulse softly, in sync — like a heartbeat. No new lines appear; existing ones glow.

Camera: slow pull-back from a medium shot of the PM, ending on a wide shot of all 6 panels with the graph fully overlaid. Final 3 seconds: graph dissolves into the GraphFlow logo, centered, with URL "graphflow.flyflow.love" underneath.

Lighting: identical warm cream + amber palette as opening, slightly dimmed for "evening / project closing" feel.

Style: matches opening cinematic exactly. The contrast is subtle — same scene, calmer state.

AVOID: dramatic transformation effects, cliché "before/after" framing, smiling faces (real focus is more powerful), any UI mockups.

Aspect: 16:9. Duration: 30 seconds. Last 3 seconds reserved for logo lockup.
```

---

## 11. 录制后清单

- [ ] 看一遍完整剪辑，标出任何"啊"、"嗯"、卡顿
- [ ] 检查每个 Scene 的画面是否正确（特别是 Membrane Accept 后的 KB 状态翻转）
- [ ] 确认所有引用点击都跳到正确目标
- [ ] 确认 `**D-{id}**` 在 postmortem 里渲染为蓝色可点击
- [ ] 确认全片没有用户可见的"🧠 Edge / Edge 的新路由询问 / 边缘代理"旧称
- [ ] 确认所有聊天时间都显示 GMT+8
- [ ] 检查时间总长 ≤ 7:30
- [ ] 检查音量、麦克风噪音
- [ ] 准备字幕文件（.srt），双语
- [ ] 上传前再过一遍清单

---

## 12. 备用 Q&A 准备（若复赛有 Live 答辩环节）

### Q1：和 Slack / Lark / Notion 的差异？

> Slack 在做"沟通"。Notion 在做"知识"。Lark 在做"工作台"。GraphFlow 在做"动态组织认知系统"——团队不是缺更多内容，而是在 AI 加速后需要稳定、可审查、可追踪的共享状态。World Graph 记录共同现实，Org Graph 记录能力和责任，Work Graph 记录行动状态转换；所有共享状态更新都要经过 Membrane 或明确的 transition contract。

### Q2：如果 Membrane 误判了怎么办？

> Membrane 不是普通审批 UI，而是组织认知更新的合法化机制。LLM recommends，Membrane enforces，Domain services mutate，Lineage remains。它包含 deterministic checks 和 LLM semantic review；AI 不确定时走 request_clarification，冲突或越权时走 request_review / reject。Owner 可以在审核面板 Override，动作进入 audit log。

### Q3：Demo 数据是真实的吗？

> 所有数据落到真实 SQLite 数据库。zh demo 项目 26 条 KB、3 条决策、6 个成员、5 条 chat 历史，全部走真实的 KB Service / Membrane Service / Decision Service / Routing Service。Flow Packet 里能看到 transition_contract 和 epistemic_event，不是前端 mock。其中 KB 内容是用 DeepSeek 生成的 zh-native 文本，模拟真实游戏开发场景。代码完全可重现：`scripts/demo/seed_moonshot_zh.py`。

### Q4：技术栈？

> 前端 Next.js 15 + RSC + Turbopack。后端 FastAPI + SQLAlchemy + Alembic。LLM 层用 DeepSeek（OpenAI 兼容协议），运行时角色包括项目助手、Router、Pre-answer、IM-assist、Membrane Agent。部署：阿里云 + Docker Compose + Cloudflare Tunnel。整个项目从 4.17 第一行代码到现在，约 200+ 次 commit，多个 Alembic 迁移，AI coding 占主导但 PM 在做架构判断。

---

## 13. 录完后选项

- 6 分钟剪辑版（去掉 Scene 5 架构解释，去掉 Scene 7 一半）→ 给评委 first pass
- 7 分钟完整版 → 给评委细看
- 可选 12 分钟"工程师向"版本：保留所有产品截图，加上代码层的 Membrane gate / scope_stream_id / KbItemRow 合并迁移的代码片段

---

录制时记住一件事：**慢一点。每个画面停 2-3 秒。让评委的眼睛跟得上鼠标。**
