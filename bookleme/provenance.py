"""Provenance manifest and distribution decision (copyright engineering)."""

from __future__ import annotations

from datetime import datetime, timezone

from . import __version__


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_manifest(*, run_id: str, title: str, author: str, isbn: str, language: str,
                   book_sha256: str, file_count: int, user_rights: str,
                   sources: list[dict], config: dict, plugin_id: str = "",
                   model_fingerprint: str = "") -> dict:
    all_checks_passed = True  # overwritten by S7 via update_distribution
    decision, reason = decide_distribution(user_rights, all_checks_passed)
    return {
        "manifest_version": "1.0",
        "run_id": run_id,
        "book": {
            "title": title, "author": author, "isbn": isbn, "language": language,
            "sha256": book_sha256, "file_count": file_count, "user_rights": user_rights,
        },
        "sources": sources,
        "derivative": {
            "contains_original_text": False,
            "max_quote_chars": config["max_quote_chars"],
            "shingle_overlap_ceiling": config["shingle_overlap_ceiling"],
            "total_quote_ratio_ceiling": config["total_quote_ratio_ceiling"],
            "max_contiguous_copy_chars": config["max_contiguous_copy_chars"],
        },
        "distribution": {
            "default": "private",
            "decision": decision,
            "reason": reason,
            "confirmed_by": "",
        },
        "attribution": {
            "author": author, "book": title, "isbn": isbn,
            "statement": "本技能为结构化衍生笔记，不含原书段落；非原书替代品；版权与商标归原权利人所有。",
            "notice": "仅供学习，支持正版。书中未涉及的问题会明确说明。",
        },
        "engine": {
            "bookleme_version": __version__,
            "plugin_id": plugin_id,
            "model_fingerprint": model_fingerprint,
        },
        "generated_at": _now(),
    }


def decide_distribution(user_rights: str, all_hard_checks_passed: bool) -> tuple[str, str]:
    if user_rights == "unknown":
        return "blocked", "user_rights=unknown: 无法确认使用权，强制私有且禁止公开"
    if not all_hard_checks_passed:
        return "blocked", "版权硬检查未全部通过"
    if user_rights == "public_domain":
        return "publishable", "公版书且硬检查通过（默认仍保持 private）"
    return "private", "自有/授权书籍生成的衍生笔记默认私有；公开需启动前显式确认"
