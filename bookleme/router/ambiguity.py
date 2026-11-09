"""Deterministic ambiguity evidence.

The approved plan calls for 3 independent LLM judges when margin < threshold.
This batch ships a deterministic fallback instead: it records a fixed-seed
sample of 8 slices and explicitly marks that no judge votes were cast. The
LLM-judge adapter is an interface placeholder for a later batch. Honesty over
claiming a capability that is not implemented.
"""

from __future__ import annotations

import random


def build_evidence(segments: list[dict], sample_size: int = 8, seed: int = 42) -> dict:
    ids = [s["segment_id"] for s in segments]
    rng = random.Random(seed)
    sample = ids if len(ids) <= sample_size else sorted(rng.sample(ids, sample_size))
    return {
        "schema_version": "1.0",
        "judge_mode": "deterministic-fallback",
        "llm_judge_invoked": False,
        "sample_seed": seed,
        "sample_size_requested": sample_size,
        "sampled_segment_ids": sample,
        "votes": [],
        "vote_bonus_applied": 0.0,
        "note": (
            "margin < threshold: 采用确定性兜底（自动双引擎）。计划中的 3 独立 LLM judge "
            "尚未接入，本批不宣称已做体裁投票；接入后每票按 configs/router.json 的 "
            "ambiguity_vote_bonus 回写分数并在此文件留痕。"
        ),
    }
