# GraphFlow 复赛 Demo 录制交接

**写于**：2026-05-04 晚
**写给**：自己（明天/随时打开）+ 任何接手的人
**目的**：你坐下来准备 cast 时，看完这一页就够了，不用回头翻聊天历史。

---

## TL;DR

GraphFlow 复赛 demo 已经准备好录了。两份文档 + 6 处 prod 修复 + 数据预热脚本就绪。
- 报告：`docs/feishu_competation.md`（4 个周期写完，自然衔接到 demo）
- 脚本：`docs/demo_script.md`（8 个场景，7 分钟，含 AI-gen 提示词）
- 代码：所有 demo 路径在 prod 已验证；最新 commit `7f17901`，5 个容器全 healthy
- 你要做的：暖 LLM render 缓存 + 启动录屏；脚本里有 curl 一行命令

---

## 1. Prod 状态（开录前 5 分钟核对）

```bash
# 一行健康检查
ssh -i ~/.ssh/id_vps root@118.31.226.72 "docker ps --format '{{.Names}}\t{{.Status}}' | grep -E 'web|api'"
```

期望输出：`workgraph-web-1 Up ... (healthy)` + `workgraph-api-1 Up ... (healthy)`

| 关键路径 | 状态 |
|---|---|
| `https://graphflow.flyflow.love/login` | ✓ GraphFlow 品牌 |
| `/projects/627e5ae2-296e-4b54-85ae-a643d0537f34/team` | ✓ 7 unique 聊天消息 + 决策芯片可点 |
| `/projects/.../kb` | ✓ 22 approved + **1 pending draft**（"外部试玩 Wave A 总结"） |
| `/projects/.../detail/im` | ✓ 1 pending_review 等你 Accept（Scene 3 用） |
| `/projects/.../detail/graph` | ✓ React Flow + TimelineStrip 渲染 |
| `/projects/.../renders/postmortem` | ⚠️ 首次调 LLM ~30s，**录前必须暖** |

---

## 2. 录前 30 分钟必做（warm-up + state freshen）

```bash
# (a) 续 cookie，登录态新鲜（用 maya/owner）
PROD=https://graphflow.flyflow.love
curl -c /tmp/cast_cookie.txt -b /tmp/cast_cookie.txt -L \
  -d 'username=maya&password=<密码>' "$PROD/api/auth/login"

PID=627e5ae2-296e-4b54-85ae-a643d0537f34

# (b) 暖 postmortem render（首次 ~30s，之后秒开）
curl -b /tmp/cast_cookie.txt "$PROD/api/projects/$PID/renders/postmortem" -m 120 -o /dev/null

# (c) 暖 handoff render（james 切片）
JAMES_ID=$(curl -sb /tmp/cast_cookie.txt "$PROD/api/projects/$PID/state" | \
  python -c "import sys,json;print([m for m in json.load(sys.stdin)['members'] if m.get('username')=='james'][0]['user_id'])")
curl -b /tmp/cast_cookie.txt "$PROD/api/projects/$PID/renders/handoff/$JAMES_ID" -m 120 -o /dev/null

# (d) 检查 Membrane 队列里还有 1 条 pending review（Scene 3 必需）
curl -sb /tmp/cast_cookie.txt "$PROD/api/projects/$PID/membrane/notes" | \
  python -c "import sys,json;d=json.load(sys.stdin);print('pending_reviews:',len(d.get('pending_reviews',[])))"
# 期望：pending_reviews: 1
# 如果是 0：去到 (e) 重建一条
```

```bash
# (e) 备用——若 pending_review 被意外清掉，重建一条 demo 草稿
cat > /tmp/draft.json <<'EOF'
{"title":"外部试玩 Wave A 总结","content_md":"# 外部试玩 Wave A 总结\n\n来源：Sofia 5/2 凌晨提交的玩家试玩报告。\n\n## 核心数据\n\n- 5 位测试者中 3 位反馈 Boss 战手感不公平\n- 第一关 Boss 怒退率 40%\n- 平均会话时长 23min（目标 35min）\n\n## 主因诊断（Aiko）\n\nBoss 战的永久死亡机制对新手玩家过于严苛。\n\n## 待决议\n\n是否引入中盘纪念品复活机制？需要团队投票。","scope":"group","source":"llm","status":"draft"}
EOF
curl -b /tmp/cast_cookie.txt -H "Content-Type: application/json" \
  -X POST "$PROD/api/projects/$PID/kb-items" -d @/tmp/draft.json
```

---

## 3. 关键 ID（避免现场翻表）

| 名称 | ID |
|---|---|
| 主 demo 项目（Stellar Drift — Season 1 Launch） | `627e5ae2-296e-4b54-85ae-a643d0537f34` |
| 团队会议室 stream | `32f41cb8-285e-49e7-8a0e-ce4d3a1da11f` |
| 录制账号 | `maya`（owner，full-tier） |
| 主 demo URL | `https://graphflow.flyflow.love/projects/627e5ae2-296e-4b54-85ae-a643d0537f34` |
| 备用账号 | `sofia` / `aiko` / `james` / `diego`（如需切换视角） |

---

## 4. 8 个场景 cheat sheet（详见 `docs/demo_script.md`）

| Scene | 时长 | URL / 动作 | 关键画面 |
|---|---|---|---|
| 0 | 20s | AI-gen 视频 | 6 人远程团队 → 图谱浮现 |
| 1 | 30s | `/` → `/inbox` | "{count} 项待确认"数字 |
| 2 | 60s | `/projects/.../team` → 点 ⚡ 决策芯片 → `/nodes/{decision_id}` | scope_stream_id = 团队会议室 |
| 3 | 70s | Sofia 消息上点 📚 Save → `/detail/im` → Accept | KB 草稿翻 published |
| 4 | 50s | `/projects/.../kb/{item_id}` → `/detail/decisions` | 完整正文不空 + lineage |
| 5 | 40s | AI-gen 图 | 5 层架构 |
| 6 | 60s | `/projects/.../detail/graph` | React Flow + TimelineStrip 倒带 |
| 7 | 60s | `/renders/postmortem` → 点 `**D-<id>**` 引用 | 引用可点击 → 决策详情 |
| 8 | 30s | AI-gen 闭幕 + logo | URL `graphflow.flyflow.love` |

---

## 5. 出意外时怎么办

| 症状 | 第一手处理 |
|---|---|
| 浏览器加载慢 | 切到 `https://graphflow.flyflow.love` 直接访问，不要走 cf workers 代理路径 |
| 决策芯片不可点 | 重新 hard-refresh（清缓存 ctrl+shift+r）；最新 commit 已经把 chip 改成 Link |
| `/detail/im` 没有 pending review | 跑一遍 §2 (e)，重建一条 |
| Postmortem 长时间转圈 | 没暖好——切到 `/renders/handoff/{james_id}` 演 handoff（同样的 citation 故事） |
| `/inbox` 是空的 | 改口径："这才是 GraphFlow 期望的安静状态——不打扰你，除非真的需要"，参考 §3.4 |
| 整个站挂了 | `ssh root@118.31.226.72 "cd /opt/workgraph/deploy && docker compose restart"` |
| 网络断了 | 切本地 `bun run dev`（同 commit），改 demo 用 `localhost:3000` |

---

## 6. 录制后 checklist

- [ ] 完整观看一遍剪辑，听有无"啊/嗯"
- [ ] 检查 ⚡ 芯片点击跳转、Accept 状态翻转、`**D-<id>**` 蓝色下划线 三个关键画面是否清晰
- [ ] 时间总长 ≤ 7:30
- [ ] 字幕（zh + en，.srt）
- [ ] 上传前再过一遍 §1 健康检查
- [ ] 录完别忘了清理 demo 草稿：`/api/kb-items/{id}` DELETE，让 prod 状态回到干净 22 approved

---

## 7. 今天这个 session 干了什么（10 行版）

发现并修复了 6 处会让 demo 演不下去的 prod 问题：
1. 决策芯片只是 label，加了 Link → /nodes/{id}（commit `7f17901`）
2. 3/7 seed 决策 scope_stream_id=null，backfilled
3. 团队会议室 5 条重复消息，去重到 7 条
4. 脚本 Scene 2 假设了不存在的"manual Crystallize"按钮，改写成"展示 IMAssist 已分类 + 用户 Accept 的状态"
5. 脚本 Scene 4/7 引用了 KB-{id} citation，但 postmortem prompt 只产出 D-<id>，已删除
6. Membrane 队列预先 stage 了 1 条 demo 草稿

写完了 `docs/feishu_competation.md` 第 3、4 周期（4.29-5.4）和 `docs/demo_script.md`（8 scenes + 4 AI-gen prompt + 备用问答）。

代码层关键 commits（按时间序）：`6ef759a` KB detail BE shape, `9e233bb` Membrane gate widening, `b513f80` KB detail wrapper unwrap, `7f17901` decision chip linkable + 脚本修订。

---

## 8. 之后（决赛之外）

- e2e harness（Playwright）—— cycle 5 优先
- v-Next 灰度复活——决赛后用 feature flag
- 5 层架构对外内容化（30s 演示切片）

加油。
