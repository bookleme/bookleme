"""Capability-to-claim conversion helpers."""

from __future__ import annotations


def capability_claims(caps: list[dict]) -> list[str]:
    return [c for cap in caps for c in cap.get("claims", [])]
