"""Seed a SECOND zh-CN demo project — 双11 大促备战 (e-commerce campaign).

Why a second zh project: the existing seed_moonshot_zh.py covers a
gaming launch. Customer demos kept feeling gaming-specific. Double-11
campaign prep is the canonical Chinese ops/coordination scenario —
multi-team, hard deadline, real KPIs, native vocabulary (千川, 坑位,
爬坡, 引力魔方, 生意参谋, 二跳率, 公域/私域).

Cast, intake paragraph, profiles, and seed-chat messages were
generated via the DeepSeek API per
`feedback_use_deepseek_for_mocks.md`. Cached at
`_double11_content.json`. Re-run `_gen_double11.py` to regenerate.

Usage:
    uv run python scripts/demo/seed_double11_zh.py

Or inside the api container on prod:
    docker compose -f deploy/docker-compose.yml exec -T api \\
        python /app/scripts/demo/seed_double11_zh.py

Idempotent: if a project with the same title already exists, it
re-uses it instead of creating a duplicate.

Assumes the dev API at http://127.0.0.1:8000. Password for all:
`moonshot2026`.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

BASE = os.environ.get("WORKGRAPH_API_URL", "http://127.0.0.1:8000")
WEB_BASE = os.environ.get("WORKGRAPH_WEB_URL", "http://localhost:3000")
PASSWORD = "moonshot2026"

CONTENT_PATH = Path(__file__).resolve().parent / "_double11_content.json"
# Fallback location when the script is shipped into the api container —
# the codepaths under /app/scripts/demo/ may or may not include the
# generated JSON depending on how the image was built.
_CONTAINER_PATH = Path("/app/scripts/demo/_double11_content.json")


def load_content() -> dict:
    for p in (CONTENT_PATH, _CONTAINER_PATH):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"_double11_content.json missing — looked in {CONTENT_PATH} and {_CONTAINER_PATH}. "
        "Run scripts/demo/_gen_double11.py first to regenerate."
    )


CONTENT = load_content()
PROJECT_TITLE: str = CONTENT["project_title"]
PROJECT_INTAKE: str = CONTENT["project_intake"]
CAST_RAW = CONTENT["cast"]  # list of {username, display_name, role_label, role_zh}
PROFILES: dict[str, dict[str, list[str]]] = CONTENT["profiles"]
SEED_CHAT: list[tuple[str, str]] = [
    (m["username"], m["body"]) for m in CONTENT["seed_chat"]
]

# Backwards-compatible CAST shape: (username, display_name, role_label_zh)
CAST: list[tuple[str, str, str]] = [
    (c["username"], c["display_name"], c["role_zh"]) for c in CAST_RAW
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


def find_or_create_project(lead: Session) -> str:
    r = lead.client.get("/api/projects")
    r.raise_for_status()
    existing = r.json()
    if isinstance(existing, dict):
        existing = existing.get("projects", [])
    for p in existing:
        if PROJECT_TITLE in (p.get("title") or ""):
            log(f"复用已有项目 '{p['title']}' ({p['id']})")
            return p["id"]
    log("提交立项说明 — 触发 parse → graph → plan (可能 10–30s)...")
    r = lead.client.post(
        "/api/intake/message",
        json={"text": PROJECT_INTAKE, "title": PROJECT_TITLE},
    )
    r.raise_for_status()
    project_id = r.json()["project"]["id"]
    log(f"已创建项目 {project_id}")
    return project_id


def invite_all(lead: Session, project_id: str, cast: list[Session]) -> None:
    for s in cast:
        if s.username == cast[0].username:
            continue
        r = lead.client.post(
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


def write_profiles(sessions: dict[str, Session]) -> None:
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
            log(f"{username} 画像已写入：{'，'.join(profile['role_hints'])}")
        else:
            log(f"{username} PATCH /api/users/me 返回 {r.status_code}")


def main() -> int:
    print(f"种子 双11 大促备战 中文演示 — {PROJECT_TITLE}")
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
    lead = sessions[CAST[0][0]]

    print()
    print("写入用户画像...")
    write_profiles(sessions)

    print()
    print("创建项目...")
    project_id = find_or_create_project(lead)

    print()
    print("邀请团队...")
    invite_all(lead, project_id, list(sessions.values()))

    print()
    print("种子聊天历史...")
    seed_chat_history(sessions, project_id)

    print()
    print("=" * 64)
    print("[OK] 双11 中文演示已种子")
    print("=" * 64)
    print()
    print(f"  项目主页:{WEB_BASE}/projects/{project_id}")
    print()
    print("  双浏览器演示：")
    print(f"    浏览器 A  ←→  {CAST[0][0]} / moonshot2026")
    print(f"    浏览器 B  ←→  {CAST[1][0]} / moonshot2026")
    print()
    print("  所有账号密码：moonshot2026")
    print()
    print("  记得在个人资料里把显示语言切成「中文」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
