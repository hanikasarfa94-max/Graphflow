"""Seed the Chinese twin of Moonshot for zh-CN customer demos.

Creates a SECOND project alongside the English Stellar Drift: different
usernames (suffix `_zh`), Chinese display names, Chinese intake, Chinese
chat history. Runs the same parse → graph → plan pipeline so task/risk/
decision surfaces come out Chinese-native.

Usage:
    uv run python scripts/demo/seed_moonshot_zh.py

Assumes the dev API at http://127.0.0.1:8000. Password for all:
`moonshot2026`.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

import httpx

BASE = os.environ.get("WORKGRAPH_API_URL", "http://127.0.0.1:8000")
WEB_BASE = os.environ.get("WORKGRAPH_WEB_URL", "http://localhost:3000")
PASSWORD = "moonshot2026"

CAST = [
    ("maya_zh", "陈梅雅", "CEO / 游戏总监"),
    ("raj_zh", "帕特尔·拉杰", "设计负责人"),
    ("aiko_zh", "中村爱子", "工程负责人"),
    ("diego_zh", "托雷斯·迭戈", "美术总监"),
    ("sofia_zh", "罗西·索菲亚", "QA / 社区负责人"),
    ("james_zh", "奥科罗·詹姆斯", "初级工程师"),
]

PROFILES: dict[str, dict[str, list[str]]] = {
    "maya_zh": {
        "role_hints": ["创始人", "CEO", "游戏总监"],
        "declared_abilities": ["愿景", "战略", "范围决策", "融资"],
    },
    "raj_zh": {
        "role_hints": ["设计负责人", "游戏设计"],
        "declared_abilities": ["系统设计", "战斗手感", "平衡性", "Boss设计"],
    },
    "aiko_zh": {
        "role_hints": ["工程负责人", "技术负责人"],
        "declared_abilities": ["系统", "内存分析", "存档状态", "性能", "Unity"],
    },
    "diego_zh": {
        "role_hints": ["美术总监", "美术负责人"],
        "declared_abilities": ["美术方向", "角色设计", "调色", "管线"],
    },
    "sofia_zh": {
        "role_hints": ["QA社区负责人", "QA负责人"],
        "declared_abilities": ["试玩测试", "Steam社区", "怒退分析", "外部数据"],
    },
    "james_zh": {
        "role_hints": ["初级工程师"],
        "declared_abilities": ["匹配系统", "网络"],
    },
}

PROJECT_TITLE = "星际漂流 — 第1季发布"

PROJECT_INTAKE = (
    "我们将在 4 周内发布《星际漂流》第 1 季。核心范围："
    "基于 Steam 的 4 人联机合作匹配(支持跨平台联机)、4 个独特"
    "Boss(含永久死亡机制)、完整手柄支持(Xbox + PlayStation + "
    "Switch)、每日随机种子、排行榜。美术完成 80%。主要风险是 Boss "
    "难度调校和 Switch 性能。发布前需要 20 人以上的外部 QA 试玩。"
)

SEED_CHAT = [
    (
        "maya_zh",
        "团队,alpha 版本已经锁定。最后冲刺重点是上架打磨和外部 QA。"
        "如果性能允许,中盘商人是延伸目标;否则砍掉。",
    ),
    (
        "diego_zh",
        "美术进度良好。Boss 3 调色推迟 2 天,备选方案是复用 Boss 2 的"
        "光照调色。影响可忽略,不会阻塞。",
    ),
    (
        "james_zh",
        "我把匹配系统草稿推到 feature/mm-v2 了。继续之前需要 review,"
        "尤其是 NAT 穿透回落路径。爱子能看一眼吗?",
    ),
    (
        "sofia_zh",
        "第一次外部试玩完成。5 位测试者中有 3 位觉得 Boss 战不公平。"
        "第一个 Boss 的怒退率 40%。会话时长平均 23 分钟,目标是 35 分钟。"
        "详细报告随后发出。",
    ),
    (
        "aiko_zh",
        "看了索菲亚的报告。主因看起来是 Boss 战的永久死亡——对新手玩家"
        "来说会话结束得太早了。动代码之前需要先做一次设计决策。",
    ),
]


@dataclass
class Session:
    username: str
    client: httpx.Client
    user_id: str


def log(msg: str) -> None:
    print(f"  {msg}")


def register_or_login(username: str, display_name: str) -> Session:
    client = httpx.Client(base_url=BASE, timeout=30.0)
    r = client.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD, "display_name": display_name},
    )
    if r.status_code in (200, 201):
        user = r.json()
        log(f"已注册 {username} ({display_name})")
        return Session(username=username, client=client, user_id=user["id"])
    if r.status_code in (400, 409):
        r = client.post(
            "/api/auth/login",
            json={"username": username, "password": PASSWORD},
        )
        r.raise_for_status()
        user = r.json()
        log(f"已登录现有账号 {username}")
        return Session(username=username, client=client, user_id=user["id"])
    r.raise_for_status()
    raise RuntimeError(f"unexpected register response {r.status_code}: {r.text}")


def find_or_create_project(maya: Session) -> str:
    r = maya.client.get("/api/projects")
    r.raise_for_status()
    existing = r.json()
    if isinstance(existing, dict):
        existing = existing.get("projects", [])
    for p in existing:
        if PROJECT_TITLE in (p.get("title") or ""):
            log(f"复用已有项目 '{p['title']}' ({p['id']})")
            return p["id"]
    log("提交梅雅的立项说明 — 触发 parse → graph → plan (可能 10–30s)...")
    r = maya.client.post(
        "/api/intake/message",
        json={"text": PROJECT_INTAKE, "title": PROJECT_TITLE},
    )
    r.raise_for_status()
    project_id = r.json()["project"]["id"]
    log(f"已创建项目 {project_id}")
    return project_id


def invite_all(maya: Session, project_id: str, cast: list[Session]) -> None:
    for s in cast:
        if s.username == "maya_zh":
            continue
        r = maya.client.post(
            f"/api/projects/{project_id}/invite",
            json={"username": s.username},
        )
        if r.status_code == 200:
            log(f"已邀请 {s.username}")
        elif r.status_code in (400, 409):
            log(f"{s.username} 已经是成员")
        else:
            r.raise_for_status()


def post_message(sess: Session, project_id: str, body: str) -> str:
    r = sess.client.post(
        f"/api/projects/{project_id}/messages",
        json={"body": body},
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        return "<?>"
    nested = data.get("message")
    if isinstance(nested, dict):
        return nested.get("id", "<?>")
    return data.get("id", "<?>")


def seed_chat_history(sessions: dict[str, Session], project_id: str) -> None:
    log(f"种子 {len(SEED_CHAT)} 条历史消息...")
    for author, body in SEED_CHAT:
        sess = sessions[author]
        msg_id = post_message(sess, project_id, body)
        log(f"  {author}: {body[:40]}{'...' if len(body) > 40 else ''}  ({msg_id[:8]})")
        time.sleep(1.2)


def main() -> int:
    print("种子 Moonshot Studios 中文演示 — 星际漂流第1季")
    print(f"  API:  {BASE}")
    print(f"  Web:  {WEB_BASE}")
    print()
    try:
        httpx.get(f"{BASE}/health", timeout=5.0).raise_for_status()
    except Exception as exc:
        print(f"[FAIL] API 未就绪:{BASE}/health - 请先启动。错误:{exc}")
        return 1

    print("注册演员阵容...")
    sessions: dict[str, Session] = {}
    for username, display_name, _ in CAST:
        sessions[username] = register_or_login(username, display_name)
    maya = sessions["maya_zh"]

    print()
    print("写入用户画像...")
    for username, _, _ in CAST:
        profile = PROFILES.get(username)
        if not profile:
            continue
        r = sessions[username].client.patch(
            "/api/users/me",
            json={
                "declared_abilities": profile["declared_abilities"],
                "role_hints": profile["role_hints"],
            },
        )
        if r.status_code == 200:
            log(f"{username} 画像已写入:{','.join(profile['role_hints'])}")
        else:
            log(f"{username} PATCH /api/users/me 返回 {r.status_code}")

    print()
    print("创建项目...")
    project_id = find_or_create_project(maya)

    print()
    print("邀请团队...")
    invite_all(maya, project_id, list(sessions.values()))

    print()
    print("种子聊天历史...")
    seed_chat_history(sessions, project_id)

    print()
    print("=" * 64)
    print("[OK] 中文 Moonshot 演示已种子")
    print("=" * 64)
    print()
    print(f"  项目主页:{WEB_BASE}/projects/{project_id}")
    print()
    print("  双浏览器演示:")
    print("    浏览器 A  ←→  maya_zh / moonshot2026")
    print("    浏览器 B  ←→  raj_zh  / moonshot2026")
    print()
    print("  所有账号密码:moonshot2026")
    print()
    print("  记得在个人资料里把显示语言切成「中文」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
