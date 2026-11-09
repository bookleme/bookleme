"""Idempotent run state. Read before write, atomic replace, hash-gated stage skip.

Mirrors the discipline in harness-iteration-loop/SKILL.md (state.json,
write-before-read, baseline comparison) without importing any of it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import STATE_PATH, dump_json
from .hashing import sha256_file


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StateStore:
    def __init__(self, path: Path = STATE_PATH):
        self.path = Path(path)

    def read(self) -> dict:
        if not self.path.exists():
            return {"schema_version": "1.0", "latest_run_id": "", "runs": {}}
        with self.path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def write(self, data: dict) -> None:
        dump_json(self.path, data)

    def ensure_run(self, run_id: str, book_sha256: str, model_fingerprint: str,
                   engine_config_hash: str = "", plugin_hash: str = "") -> dict:
        data = self.read()  # write-before-read
        data["latest_run_id"] = run_id
        run = data["runs"].get(run_id)
        if run is None:
            run = {
                "created_at": _now(),
                "book_sha256": book_sha256,
                "model_fingerprint": model_fingerprint,
                "engine_config_hash": engine_config_hash,
                "plugin_hash": plugin_hash,
                "stages": {},
            }
            data["runs"][run_id] = run
        else:
            run["book_sha256"] = book_sha256
            run["model_fingerprint"] = model_fingerprint
            run["engine_config_hash"] = engine_config_hash
            run["plugin_hash"] = plugin_hash
        self.write(data)
        return run

    def get_stage(self, run_id: str, stage: str) -> dict | None:
        return self.read().get("runs", {}).get(run_id, {}).get("stages", {}).get(stage)

    def should_skip(self, run_id: str, stage: str, input_sha256: str,
                    output_paths: list[Path]) -> bool:
        rec = self.get_stage(run_id, stage)
        if not rec or rec.get("status") != "completed":
            return False
        if rec.get("input_sha256") != input_sha256:
            return False
        return all(Path(p).exists() for p in output_paths)

    def mark(self, run_id: str, stage: str, input_sha256: str,
             output_paths: list[Path], status: str = "completed",
             degraded: bool = False, note: str = "", attempts: int = 1) -> None:
        data = self.read()  # write-before-read
        run = data.setdefault("runs", {}).setdefault(run_id, {"created_at": _now(), "stages": {}})
        stages = run.setdefault("stages", {})
        prev = stages.get(stage, {})
        stages[stage] = {
            "status": status,
            "input_sha256": input_sha256,
            "output_sha256": sha256_file(output_paths[0]) if output_paths and Path(output_paths[0]).exists() else "",
            "outputs": [str(Path(p)) for p in output_paths],
            "ts": _now(),
            "attempts": prev.get("attempts", 0) + attempts if status == "completed" else attempts,
            "degraded": degraded,
            "note": note,
        }
        data["latest_run_id"] = run_id
        self.write(data)
