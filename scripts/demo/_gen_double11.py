"""Generate the seed content for the new zh demo project: 双11 大促备战.

Drives DeepSeek (per feedback_use_deepseek_for_mocks.md) to produce
in-character cast + intake + chat for a non-gaming Chinese-flavor demo
project. Output is written to `_double11_content.json` for review +
hand-off into seed_double11_zh.py.

Cast: 6 members on a Chinese e-commerce platform team prepping for
the Double-11 (Singles' Day) campaign. Five weeks out from Nov 11.

Run:
    .venv/Scripts/python.exe scripts/demo/_gen_double11.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deepseek_gen import gen  # noqa: E402

OUT_PATH = Path(__file__).resolve().parent / "_double11_content.json"

CAST = [
    ("liwei_d11", "李伟", "campaign_lead", "总指挥 / 大促操盘手"),
    ("zhangyu_d11", "张昱", "traffic_lead", "流量负责人 / 投放主管"),
    ("chenmin_d11", "陈敏", "product_lead", "货品负责人 / 商品中台"),
    ("wangkai_d11", "王凯", "tech_lead", "技术负责人 / 大促保障"),
    ("liuxia_d11", "刘霞", "ops_lead", "客服与物流协调"),
    ("hujun_d11", "胡军", "risk_lead", "风控与财务"),
]

PROJECT_TITLE = "双11 大促备战 — 五周冲刺"

VOICE_GUIDE = """\
背景:中国头部电商平台（淘系 / 京东 / 拼多多 的语境）。
团队在为 11/11 双11 大促做最后五周的备战。
说话风格:
- 微信群 / 飞书群 的口吻,简短,技术 + 业务混合
- 用一些本土行话:GMV、UV、PV、CTR、ROI、SKU、爆款、达人、心智、坑位、
  保价、虚假发货、爬坡、补贴、买点、沉浸式、二跳率、人货场、私域、公域、
  千川、引力魔方、生意参谋
- 不说「我们一定要」「让我们一起」之类翻译腔
- 偶尔不耐烦,带情绪,但不无礼
- 中英混用偶尔出现是正常的(KPI、SLA、push、deadline 这些)
- 数字 + 具体时间是常态:GMV 目标 8亿,UV 4500万,深度页 CTR 12%
- 不写品牌名(怕侵权),用「平台」「商家」「头部品牌」「白牌」
"""


def gen_intake() -> str:
    return gen(
        system=(
            "你是一个中国头部电商平台的大促总指挥,正在向团队提交一份立项说明。\n"
            f"{VOICE_GUIDE}\n"
            "请用 220-280 字写出立项说明,包含:\n"
            "- 业务目标(GMV、UV、深度页等具体数字)\n"
            "- 范围(预热期 / 爆发期 / 返场;承接什么货品池)\n"
            "- 资源约束(人力、坑位、预算)\n"
            "- 主要风险(选品、保价、性能、客服话术)\n"
            "- 交付要求(几号封板、几号上线、何时复盘)\n"
            "用第一人称,口吻像总指挥在飞书群发的项目立项 brief。"
        ),
        user=f"项目标题:{PROJECT_TITLE}。请写立项说明。",
        max_tokens=600,
        temperature=0.6,
    )


def gen_profile(username: str, role_label: str, role_zh: str) -> dict[str, list[str]]:
    """Generate role_hints + declared_abilities for one cast member."""
    text = gen(
        system=(
            f"你正在为电商大促团队的成员 {username}（{role_zh}）生成画像。\n"
            f"{VOICE_GUIDE}\n"
            "返回严格 JSON,不要 markdown 包裹,不要解释:\n"
            '{"role_hints": ["...", "...", "..."], "declared_abilities": ["...", "...", "...", "..."]}\n'
            "role_hints 是 3 个对该角色的高频别称(中文,2-6 字),例如对总指挥:[\"总指挥\", \"操盘手\", \"项目负责人\"]\n"
            "declared_abilities 是 4-5 个该人在双11 项目里能干的具体技能(中文,3-8 字),例如对流量:\n"
            "[\"千川投放\", \"达人种草\", \"引力魔方调优\", \"竞价提报\"]\n"
            "技能要具体到工具或场景,不要写虚的(\"沟通能力\"\"团队合作\"是禁止的)。"
        ),
        user=f"为 {username}（{role_zh}）生成 profile。",
        max_tokens=240,
        temperature=0.5,
    )
    # Parse JSON; tolerate fences if model adds them.
    text = text.strip()
    if text.startswith("```"):
        # strip optional ```json fence
        text = text.split("\n", 1)[1].rsplit("\n```", 1)[0]
    data = json.loads(text)
    return {
        "role_hints": data["role_hints"],
        "declared_abilities": data["declared_abilities"],
    }


def gen_chat_message(username: str, role_zh: str, beat: str) -> str:
    return gen(
        system=(
            f"你扮演 {username}（{role_zh}）,在大促飞书群里发一条消息。\n"
            f"{VOICE_GUIDE}\n"
            "约束:\n"
            "- 单条 40-110 字,微信群口吻\n"
            "- 不要署名,不要加问候语\n"
            "- 必须涉及一个具体的、可验证的事实(数字、时间、SKU、链接、人名)\n"
            "- 自然出现 1-3 个本土行话\n"
            "- 不要用「我们将」「让我们」翻译腔\n"
            "- 直接输出消息正文,不要引号"
        ),
        user=f"语境(剧情节拍):{beat}\n请写出 {username} 的消息。",
        max_tokens=240,
        temperature=0.85,
    )


# Beats — 15 messages telling a 5-week campaign-prep arc.
BEATS = [
    ("liwei_d11", "总指挥", "群里第一条:宣布五周冲刺开始,定 KPI(GMV 目标、UV、心智)、把节奏拍下来"),
    ("chenmin_d11", "货品负责人", "回应总指挥,报告本期主推的 3 个品类 + 头部 SKU 清单的进度"),
    ("zhangyu_d11", "流量负责人", "盘点千川 + 达人 + 站外的预算分配,提出预热期的核心动作"),
    ("wangkai_d11", "技术负责人", "压测预告:本周做一次百万 QPS 压测,需要业务给数据脚本"),
    ("liuxia_d11", "客服与物流", "客诉趋势提醒:上周保价话术有歧义,被投诉;需要重新培训"),
    ("hujun_d11", "风控与财务", "风控警示:今年监管对虚假发货 / 先涨后降的处罚力度更狠,提醒货品端注意"),
    ("zhangyu_d11", "流量负责人", "插一条紧急情况:预算审批被卡,千川计划要等到周五才能开;影响预热爬坡"),
    ("liwei_d11", "总指挥", "回应预算被卡,提出走绿色通道 + 提交财务的简版 ROI 测算"),
    ("chenmin_d11", "货品负责人", "提名一款黑马 SKU(具体品类 + 价格段),建议追加到主会场"),
    ("wangkai_d11", "技术负责人", "压测结果:深度页 P99 1.8s,目标 800ms;需要 2 周内优化到位"),
    ("liuxia_d11", "客服与物流", "对接菜鸟 / 京东物流的发货 SLA 已经签好,初稿在共享文档里"),
    ("hujun_d11", "风控与财务", "决策请求:某个商家的资质有疑点,要不要从主会场撤掉?"),
    ("liwei_d11", "总指挥", "针对资质疑点商家的处理:撤掉,但要把履约预案告知客服"),
    ("zhangyu_d11", "流量负责人", "进展更新:千川 + 达人计划上线了,UV 爬坡比预期快 12%"),
    ("liwei_d11", "总指挥", "T-1 复盘前的最后一条:把每个分团的封板时间钉在置顶,出问题立刻在群里 @ 我"),
]


def main() -> None:
    out: dict = {}

    print("[1/3] generating intake...", file=sys.stderr)
    out["project_title"] = PROJECT_TITLE
    out["project_intake"] = gen_intake()
    print(out["project_intake"][:80] + "...", file=sys.stderr)

    print(f"[2/3] generating {len(CAST)} profiles...", file=sys.stderr)
    out["cast"] = []
    out["profiles"] = {}
    for username, display, role_label, role_zh in CAST:
        out["cast"].append(
            {
                "username": username,
                "display_name": display,
                "role_label": role_label,
                "role_zh": role_zh,
            }
        )
        try:
            out["profiles"][username] = gen_profile(username, role_label, role_zh)
            print(
                f"  {username}: hints={out['profiles'][username]['role_hints']}",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"  {username}: FAILED ({e}); falling back to placeholder", file=sys.stderr)
            out["profiles"][username] = {
                "role_hints": [role_zh.split(" / ")[0]],
                "declared_abilities": [role_zh.split(" / ")[0]],
            }

    print(f"[3/3] generating {len(BEATS)} seed messages...", file=sys.stderr)
    out["seed_chat"] = []
    for username, role_zh, beat in BEATS:
        msg = gen_chat_message(username, role_zh, beat)
        out["seed_chat"].append({"username": username, "body": msg})
        print(f"  {username}: {msg[:60]}...", file=sys.stderr)

    OUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nwrote {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
