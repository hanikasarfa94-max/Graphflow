"""Generate realistic corpus padding via DeepSeek.

Input: a narrative seed (which team, which product, what they're working
on) plus a desired count + kind/scope mix.

Output: JSON list of {id, kind, scope, title, content, metadata} dicts
compatible with CorpusItem. Saved to tests/eval/dataset/attention/
realistic_padding.json so build_corpus can load it instead of the RNG
synthetic placeholders.

Two purposes from one generator:
  1. Eval — replaces RNG `pad_NNNNN` plain text with realistic noise so
     scaling-pass numbers reflect production-shape content. Caveat:
     DeepSeek-generated content evaluated by DeepSeek has circularity
     risk; the real test is whether F1/leak numbers hold against
     realistic-but-not-self-generated content. Cross-provider
     generation (Claude / GPT) would tighten the signal but no other
     provider is configured today.
  2. Demo — same corpus seeds the production DB for screenshots,
     ByteDance final-round walkthroughs, customer pilots.

Run:
  python tests/eval/scripts/generate_realistic_corpus.py --count 500
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "agents" / "src"))

from workgraph_agents.llm import LLMClient  # noqa: E402


NARRATIVE_SEED = """
Team: WorkGraph product team — 6 engineers, 2 designers, 1 PM, 1 CEO.
Building an AI-native collaboration platform competing with Slack/Lark/Feishu.
Core product: "cells" (project workspaces) with stream-shaped chat,
crystallized decisions as first-class graph nodes, KB items, tasks, risks.
Stack: Next.js 15 web, FastAPI Python backend, SQLAlchemy + Postgres,
DeepSeek LLM for agent layer, deployed on Fly.io with Cloudflare tunnel.
Recent themes: signal-chain crystallization, membrane review queue,
multi-room cells, scope-tier license filtering, attention-engine eval.
Bilingual zh + en team — content can be in either language.
"""

PEOPLE = ["u_alice", "u_bob", "u_carol", "u_dave", "u_eve", "u_frank"]

DEFAULT_KIND_MIX = {
    "kb_item": 0.40,
    "decision": 0.18,
    "stream_turn": 0.20,
    "task": 0.13,
    "risk": 0.09,
}

DEFAULT_SCOPE_MIX = {
    "personal": 0.20,
    "group": 0.55,
    "department": 0.15,
    "enterprise": 0.10,
}


@dataclass(slots=True)
class GenSpec:
    """A single item to generate."""

    id: str
    kind: str
    scope: str
    lang: str  # "zh" or "en"
    owner: str | None  # for personal scope
    age_days: int  # how old this item should pretend to be


def _build_specs(
    n: int,
    seed: int,
    kind_mix: dict[str, float],
    scope_mix: dict[str, float],
    id_prefix: str = "gen_",
) -> list[GenSpec]:
    """Deterministic plan: ids, kinds, scopes, languages, owners, ages.

    `id_prefix` lets the caller produce non-colliding id sets when
    layering multiple generations into one combined corpus (e.g.
    `gen_` for the 498-item baseline + `gen_xl_` for an additional
    2000-item scaling pass).
    """
    rng = random.Random(seed)
    kinds, kweights = zip(*kind_mix.items())
    scopes, sweights = zip(*scope_mix.items())
    specs: list[GenSpec] = []
    for i in range(n):
        kind = rng.choices(kinds, weights=kweights, k=1)[0]
        scope = rng.choices(scopes, weights=sweights, k=1)[0]
        lang = "zh" if rng.random() < 0.4 else "en"  # ~40% zh
        owner = rng.choice(PEOPLE) if scope == "personal" else None
        # Age band by kind (recent-skewed): stream_turn fresh, kb_item old.
        band = {
            "stream_turn": (0, 30),
            "task": (0, 60),
            "risk": (3, 90),
            "decision": (1, 120),
            "kb_item": (7, 240),
        }[kind]
        age_days = rng.randint(*band)
        specs.append(
            GenSpec(
                id=f"{id_prefix}{i:05d}",
                kind=kind,
                scope=scope,
                lang=lang,
                owner=owner,
                age_days=age_days,
            )
        )
    return specs


def _build_prompt(spec: GenSpec) -> list[dict[str, str]]:
    kind_guide = {
        "kb_item": (
            "a knowledge-base note: a fact, runbook, architecture pattern, "
            "or technical spec. ~80-180 words of substantive prose, with "
            "optional code-fence or numbered steps where natural."
        ),
        "decision": (
            "a crystallized decision: title in form 'Decision: <verb> <object>', "
            "body has 'Decision: ...' line + 'Rationale: ...' line + optional "
            "'Trade-off: ...'. ~50-100 words."
        ),
        "stream_turn": (
            "a chat message in a team room or DM. Single conversational turn, "
            "1-3 sentences. May @-mention another teammate. May reference an "
            "id like @kb_xxx or @dec_xxx in passing."
        ),
        "task": (
            "a task description: imperative title, 1-2 sentence body describing "
            "what to do and the acceptance signal."
        ),
        "risk": (
            "a flagged risk: short title, 1-2 sentence body describing the "
            "concern and why it matters now."
        ),
    }[spec.kind]

    scope_guide = {
        "personal": "Personal note, only the owner reads. May be candid / draft / opinion.",
        "group": "Cell-shared content visible to the whole project team.",
        "department": "Cross-cell knowledge — visible to a department / discipline.",
        "enterprise": "Org-wide content — broadcast quality.",
    }[spec.scope]

    lang_guide = {"zh": "Write in 简体中文.", "en": "Write in English."}[spec.lang]

    system = (
        "You generate realistic corpus content for an AI collaboration "
        "platform's eval/demo dataset. The content must be plausibly "
        "different from one item to the next (vary topic, tone, specifics) "
        "and consistent with the team narrative below. Avoid generic "
        "corporate prose. Sound like real engineers writing real notes.\n\n"
        f"Team narrative:\n{NARRATIVE_SEED.strip()}\n\n"
        "Return strict JSON of shape "
        '{"title": "...", "content": "...", "tags": ["..."]}. '
        "Tags are optional; 0-3 short tag strings."
    )
    user = (
        f"Generate one {spec.kind} for this corpus.\n"
        f"Shape: {kind_guide}\n"
        f"Scope: {spec.scope} — {scope_guide}\n"
        f"Language: {lang_guide}\n"
        f"Recency: ~{spec.age_days} days old "
        "(content should feel time-appropriate; e.g. older items reference "
        "themes from earlier in the project, newer items are about ongoing work).\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def _generate_one(client: LLMClient, spec: GenSpec) -> dict | None:
    messages = _build_prompt(spec)
    try:
        result = await client.complete(
            messages,
            temperature=0.7,  # higher = more variety
            response_format={"type": "json_object"},
        )
    except Exception as e:
        print(f"  spec {spec.id} failed: {type(e).__name__}: {e}", flush=True)
        return None
    try:
        payload = json.loads(result.content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    title = str(payload.get("title", "")).strip()
    content = str(payload.get("content", "")).strip()
    tags_raw = payload.get("tags") or []
    tags = [str(t) for t in tags_raw if isinstance(t, str)][:3]
    if not title or not content:
        return None
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(days=spec.age_days)).isoformat()
    metadata: dict[str, object] = {
        "lang": spec.lang,
        "ts": ts,
        "tags": tags,
        "generated": True,
    }
    if spec.owner is not None:
        metadata["owner"] = spec.owner
    return {
        "id": spec.id,
        "kind": spec.kind,
        "scope": spec.scope,
        "title": title,
        "content": content,
        "metadata": metadata,
        "suppressed": False,
    }


async def _run(
    count: int,
    seed: int,
    output_path: Path,
    concurrency: int,
    id_prefix: str = "gen_",
):
    specs = _build_specs(
        count, seed, DEFAULT_KIND_MIX, DEFAULT_SCOPE_MIX, id_prefix=id_prefix
    )
    print(
        f"plan: {len(specs)} items  "
        f"kinds={dict((k, sum(1 for s in specs if s.kind == k)) for k in DEFAULT_KIND_MIX)}  "
        f"scopes={dict((s, sum(1 for x in specs if x.scope == s)) for s in DEFAULT_SCOPE_MIX)}",
        flush=True,
    )

    client = LLMClient()
    semaphore = asyncio.Semaphore(concurrency)
    items: list[dict | None] = [None] * len(specs)

    async def worker(idx: int, spec: GenSpec):
        async with semaphore:
            t0 = time.monotonic()
            items[idx] = await _generate_one(client, spec)
            elapsed = int((time.monotonic() - t0) * 1000)
            ok = "ok" if items[idx] else "FAIL"
            if (idx + 1) % 25 == 0 or idx < 5:
                print(
                    f"  [{idx + 1}/{len(specs)}] {ok} {spec.kind}/{spec.scope}/{spec.lang} ({elapsed}ms)",
                    flush=True,
                )

    await asyncio.gather(*[worker(i, s) for i, s in enumerate(specs)])

    good = [item for item in items if item is not None]
    print(f"\ngenerated {len(good)}/{len(specs)} items ({len(specs) - len(good)} failed)", flush=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(good, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"wrote {output_path} ({output_path.stat().st_size} bytes)", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--count", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "tests" / "eval" / "dataset" / "attention" / "realistic_padding.json",
    )
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument(
        "--id-prefix",
        type=str,
        default="gen_",
        help="Item id prefix — use a non-default value when generating "
        "incremental items meant to layer with an existing file.",
    )
    args = p.parse_args()
    t0 = time.monotonic()
    asyncio.run(
        _run(
            args.count,
            args.seed,
            args.output,
            args.concurrency,
            id_prefix=args.id_prefix,
        )
    )
    print(f"total wall: {time.monotonic() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
