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
    total = sum(len(q) for q in quotes)
    return total / max(1, len(artifact))
