"""Regression: prompts must not self-point.

Bug surfaced in v3+v4 dogfood: Sofia's pre-answer body said "you should
ask Sofia" because the LLM didn't know the reader WAS Sofia. Same class
of bug hits reply-frame (source side) and scrimmage turns (speaker side).

Fix pattern: each reader-visible prompt carries explicit reader-identity
plus a self-exclusion rule. This test asserts that rule is present in
every prompt that produces reader-visible text. If a future refactor
strips it, the regression should blow up here rather than re-surfacing
in prod dogfood.
"""
from __future__ import annotations

from pathlib import Path

import re

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROMPT_DIR = (
    _REPO_ROOT
    / "packages"
    / "agents"
    / "src"
    / "workgraph_agents"
    / "prompts"
    / "edge"
)
_AGENTS_SRC = _REPO_ROOT / "packages" / "agents" / "src" / "workgraph_agents"


def _read(name: str) -> str:
    return (_PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def _read_constant(module_path: Path, name: str) -> str:
    """Read a top-level `NAME = "..."` constant from a python source file.

    Used instead of importing so this test always measures THIS
    worktree's source even when the editable install points to another
    checkout (multi-worktree dev flow).
    """
    text = module_path.read_text(encoding="utf-8")
    m = re.search(rf'^{re.escape(name)}\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m is not None, f"{name} not found in {module_path}"
    return m.group(1)


def test_pre_answer_prompt_carries_reader_identity_rule():
    """pre_answer draft reader is the target — prompt must flag it."""
    prompt = _read("pre_answer_v1")
    low = prompt.lower()
    assert "reader" in low, "pre_answer prompt missing reader-identity block"
    assert "target.display_name" in prompt, (
        "pre_answer prompt must name target.display_name as the reader"
    )
    # The "do not route to the reader" rule — phrased as "ask, route to,
    # loop in, or consult" in the v2 prompt. At minimum one of these
    # verbs must pair with a self-exclusion instruction.
    assert (
        "consult" in low and "themselves" in low
    ), "pre_answer prompt missing self-exclusion rule"


def test_reply_frame_prompt_carries_reader_identity_rule():
    """reply_frame reader is the source — prompt must flag it."""
    prompt = _read("reply_frame_v1")
    low = prompt.lower()
    assert "reader" in low, "reply_frame prompt missing reader-identity block"
    assert "source" in low
    assert (
        "consult" in low and "themselves" in low
    ), "reply_frame prompt missing self-exclusion rule"


def test_edge_v1_prompt_carries_reader_identity_rule():
    """edge.respond reader is the user — prompt must flag it + block
    self-routing as a hard rule (route_targets can't include the reader).
    """
    prompt = _read("v1")
    low = prompt.lower()
    assert "reader" in low, "edge v1 prompt missing reader-identity block"
    assert "context.user.id" in prompt, (
        "edge v1 prompt must pin the reader via context.user.id"
    )
    assert (
        "themselves" in low
    ), "edge v1 prompt missing self-exclusion rule"


def test_prompt_versions_bumped_for_self_reference_fix():
    """The three prompts that carry reader-visible LLM text must have
    their version strings bumped from the pre-fix 2026-04-18/04-20
    cohort. This keeps cache + observability coherent: a run on the new
    prompt is tagged with the new version, so eval harnesses can
    distinguish pre/post-fix behavior.
    """
    pre_answer_ver = _read_constant(
        _AGENTS_SRC / "pre_answer.py", "PRE_ANSWER_PROMPT_VERSION"
    )
    reply_frame_ver = _read_constant(
        _AGENTS_SRC / "edge.py", "REPLY_FRAME_PROMPT_VERSION"
    )
    edge_ver = _read_constant(_AGENTS_SRC / "edge.py", "PROMPT_VERSION")

    assert pre_answer_ver != "2026-04-20.stage2.v1"
    assert reply_frame_ver != "2026-04-18.phaseM.v1"
    assert edge_ver != "2026-04-18.phaseQ.v1"
