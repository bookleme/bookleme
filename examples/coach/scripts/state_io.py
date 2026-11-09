"""Minimal cross-turn state helper. Runtime state lives outside the skill package."""
import json
import os
from pathlib import Path


def state_path(slug, session_id, state_dir):
    return Path(state_dir) / slug / session_id / "state.json"


def load(slug, session_id, state_dir):
    p = state_path(slug, session_id, state_dir)
    if not p.exists():
        return {"slug": slug, "session_id": session_id, "current_state": "opening",
                "turn_index": 0, "asked_questions": [], "answers": [],
                "skipped_reverse": [], "version": 1}
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save(state, slug, session_id, state_dir):
    p = state_path(slug, session_id, state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("state.json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
