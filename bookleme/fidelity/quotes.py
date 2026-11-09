"""Verbatim quote verification against the normalised full text."""

from __future__ import annotations

from ..capabilities.ria import validate_ria


def verify_quotes(capabilities: dict, full_text: str, char_map: list, config: dict) -> tuple[dict, list[dict]]:
    records: list[dict] = []
    for cap in capabilities["capabilities"]:
        quote = cap["ria"]["R_quote"]
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
