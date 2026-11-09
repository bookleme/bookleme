"""Deterministic trigger-face (description) generation."""

from __future__ import annotations

import re


def build_description(plugin, book_title: str, config: dict) -> str:
    words = list(plugin.trigger_words)
    if not (config["trigger_words_min"] <= len(words) <= config["trigger_words_max"]):
        raise ValueError(f"trigger_words 数量须在 {config['trigger_words_min']}-{config['trigger_words_max']} 之间")
    if not all(re.fullmatch(r"[\u4e00-\u9fff]{2,12}", w) for w in words):
        raise ValueError("trigger_words 必须全部为中文词")

    safe_title = book_title.replace("<", "").replace(">", "").strip()
    desc = (
        f"当{'、'.join(words)}时使用。"
        f"基于《{safe_title}》的结构化衍生框架，把作者的方法编译成可执行流程；"
        "不含原文段落，书中未涉及的问题会明确说明。"
    )
    hits = sum(1 for w in words if w in desc)
    if not (3 <= hits <= 5):
        raise ValueError(f"description 命中的中文触发词数 {hits} 不在 3-5")
    if len(desc) > 1024 or "<" in desc or ">" in desc or desc.startswith("[TODO:"):
        raise ValueError("description 违反官方校验器规则")
    return desc
