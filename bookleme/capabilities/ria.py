"""RIA++ six-field validation."""

from __future__ import annotations

SIX_FIELDS = ["R_quote", "I_rephrase", "A1_author_case", "A2_user_trigger", "A3_steps", "B_not_applicable"]


def validate_ria(ria: dict, config: dict) -> list[str]:
    # Lazy import: fidelity.quotes imports capabilities.ria, so importing the
    # fidelity package at module load time would create a circular import.
    from ..fidelity.overlap import shingle_jaccard

    errors: list[str] = []
    for key in SIX_FIELDS:
        value = ria.get(key)
        if not value or (isinstance(value, str) and not value.strip()):
            errors.append(f"ria.{key} 为空")
    quote = str(ria.get("R_quote", ""))
    if len(quote) > config["max_quote_chars"]:
        errors.append(f"ria.R_quote 超过 {config['max_quote_chars']} 字上限（{len(quote)}）")
    steps = ria.get("A3_steps")
    if not isinstance(steps, list) or len(steps) < 1:
        errors.append("ria.A3_steps 必须是至少 1 步的列表")
    if shingle_jaccard(quote, str(ria.get("I_rephrase", "")), config["shingle_size"]) > 0.10:
        errors.append("ria.I_rephrase 与原文引语 13 字 shingle 重叠 > 0.10，未做到重写")
    return errors
