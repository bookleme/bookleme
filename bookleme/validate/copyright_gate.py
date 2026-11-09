"""Six deterministic no-verbatim-copy checks. Any failure blocks install/publish."""

from __future__ import annotations

from pathlib import Path

from ..fidelity.overlap import max_contiguous_copy, shingle_jaccard, total_quote_ratio

_FORBIDDEN_NAMES = {"full_text.txt", "char_map.json"}


def run_copyright_gate(skill_dir: Path, full_text: str, quotes: list[str], config: dict) -> dict:
    skill_dir = Path(skill_dir)
    texts: dict[str, str] = {}
    for path in sorted(skill_dir.rglob("*")):
        if path.is_file() and path.suffix in {".md", ".py", ".json"}:
            texts[str(path.relative_to(skill_dir))] = path.read_text(encoding="utf-8", errors="replace")
    artifact = "\n".join(texts.values())
    present = [q for q in quotes if q and q in artifact]

    checks: list[dict] = []

    def add(name: str, passed: bool, value, ceiling) -> None:
        checks.append({"name": name, "passed": bool(passed), "value": value, "ceiling": ceiling})

    bad_quote = [q for q in quotes if len(q) > config["max_quote_chars"]]
    add("single_quote_char_limit", not bad_quote, max((len(q) for q in quotes), default=0),
        config["max_quote_chars"])
    ratio = total_quote_ratio(present, artifact)
    add("total_quote_ratio", ratio <= config["total_quote_ratio_ceiling"], round(ratio, 6),
        config["total_quote_ratio_ceiling"])
    contiguous = max_contiguous_copy(full_text, artifact)
    add("max_contiguous_copy_chars", contiguous <= config["max_contiguous_copy_chars"], contiguous,
        config["max_contiguous_copy_chars"])
    overlap = shingle_jaccard(full_text, artifact, config["shingle_size"])
    add("shingle_overlap_max", overlap <= config["shingle_overlap_ceiling"], round(overlap, 6),
        config["shingle_overlap_ceiling"])
    raw_found = sorted(p.name for p in skill_dir.rglob("*") if p.is_file() and p.name in _FORBIDDEN_NAMES)
    raw_found += sorted(p.name for p in skill_dir.rglob("*") if p.suffix.lower() in {".pdf", ".epub", ".mobi", ".azw3"})
    add("raw_text_in_artifact", not raw_found, raw_found, [])
    import re
    has_merged_source_block = bool(re.search(r"^SOURCE: ", artifact, re.M))
    add("derivative_contains_original_text", not has_merged_source_block,
        has_merged_source_block, False)

    passed = all(c["passed"] for c in checks)
    return {
        "passed": passed,
        "checks": checks,
        "artifact_chars": len(artifact),
        "quote_chars_present": sum(len(q) for q in present),
        "note": "任一失败 → S7 abort，产物不安装、不发布。",
    }
