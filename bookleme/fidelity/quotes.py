"""Verbatim quote verification against the normalised full text."""

from __future__ import annotations

from ..capabilities.ria import validate_ria


def verify_quotes(capabilities: dict, full_text: str, char_map: list, config: dict) -> tuple[dict, list[dict]]:
    records: list[dict] = []
    for cap in capabilities["capabilities"]:
        quote = cap["ria"]["R_quote"]
        # 已有权威锚点时以它为准（读图卡的锚点来自 figures.json，比 find 更准）；
        # find 出来的是**第一次出现**的位置——引文在目录/正文重复时会指错地方。
        anchor = cap.get("span", {}).get("char_start")
        pos = -1
        if isinstance(anchor, int) and anchor >= 0 \
                and full_text[anchor:anchor + len(quote)] == quote:
            pos = anchor
        else:
            pos = full_text.find(quote)
        length_ok = len(quote) <= config["max_quote_chars"]
        verified = pos >= 0 and length_ok
        ria_errors = validate_ria(cap["ria"], config)
        if verified:
            cap["span"]["char_start"] = pos
            cap["span"]["char_end"] = pos + len(quote)
        origin = [-1, -1]
        if 0 <= pos < len(char_map):
            origin = char_map[pos]
        cap["status"] = "verified" if verified and not ria_errors else "rejected"
        cap["checks"]["quote_verified"] = verified
        cap["checks"]["ria_errors"] = ria_errors
        cap["checks"]["origin"] = {"source_index": origin[0], "original_char_index": origin[1]}
        records.append({
            "capability_id": cap["capability_id"],
            "quote_char_count": len(quote),
            "quote_verified": verified,
            "verified_offset": pos,
            "origin": {"source_index": origin[0], "original_char_index": origin[1]},
            "ria_errors": ria_errors,
        })
    return capabilities, records
