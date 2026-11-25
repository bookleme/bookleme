"""Verbatim-copy measurements used by both fidelity and copyright gates."""

from __future__ import annotations


def _shingles(text: str, n: int) -> set[str]:
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def shingle_jaccard(a: str, b: str, n: int = 13) -> float:
    sa, sb = _shingles(a, n), _shingles(b, n)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def shingle_set(text: str, n: int = 13) -> set[str]:
    """公开的 shingle 集合接口（V1 跨域佐证计数等确定性统计用）。"""
    return _shingles(text, n)


def max_contiguous_copy(source: str, artifact: str) -> int:
    """Longest artifact substring that also occurs in the source (bounded scan)."""
    if not source or not artifact:
        return 0
    best = 0
    # Sample windows from the artifact; full O(n*m) is unnecessary for a gate.
    window = 200
    step = max(1, window // 2)
    for start in range(0, len(artifact), step):
        chunk = artifact[start:start + window]
        for size in (window, 150, 80, 40):
            probe = chunk[:size]
            if len(probe) <= best:
                break
            if probe in source:
                best = max(best, len(probe))
                break
    return min(best, window)


def total_quote_ratio(quotes: list[str], artifact: str) -> float:
    """引文字数 / 产物字数（**相对产物**）。

    保留这个指标是为了兼容既有报告口径，但**它不是版权问题的正确刻度**：
    分母是产物字数，于是书越短、卡越少，被罚得越重。同一份引文（1383 字）
    在 25K 字的文章上占 7.5%，在 300K 字的书上只占 0.77% —— 它测的是书的
    长度，不是抄了多少。版权真正要问的是「你从原作里搬走了多少」，
    那是 `source_quote_ratio` 的刻度。
    """
    total = sum(len(q) for q in quotes)
    return total / max(1, len(artifact))


def source_quote_ratio(quotes: list[str], source: str) -> float:
    """引文字数 / **源文**字数 —— 版权问题的正确刻度。

    这才是「从原作搬走了多少比例」的度量：与源文长度无关，与产物长短无关。
    短文被编译成技能时不会因为「书短」而被误判为过度复制；长文也不会因为
    产物膨胀而显得清白。

    但**极短源文**会让比例失真：源文 2,368 字、6 张卡、112 字引文 → 4.73%，
    这个数字看着刺眼，但实际只搬走了 112 个字——绝对量微不足道。
    所以分母设下限 `MIN_SOURCE_BASE`（默认 20,000 字）：源文短于下限时，
    按下限算——**短文享受不到比例优惠，但也不因「短」而被重罚**。
    绝对量的兜底由第 1 条（单条 ≤150 字）承担。

    为什么要这个下限：比例门本意是拦「成规模照抄」，而「规模」是绝对量概念。
    源文 2 千字时不存在成规模照抄的可能——整本书都能背下来。
    """
    total = sum(len(q) for q in quotes)
    base = max(len(source), MIN_SOURCE_BASE)
    return total / base


#: 比例门的分母下限：源文短于此值时按此值算（见 source_quote_ratio 注释）
MIN_SOURCE_BASE = 20000
