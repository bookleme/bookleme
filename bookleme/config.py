"""Configuration loading. JSON is used instead of YAML for zero-dependency operation."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("BOOKLEME_HOME") or Path(__file__).resolve().parents[1]).resolve()

CONFIG_DIR = ROOT / "configs"
SCHEMA_DIR = ROOT / "schemas"
DEFAULT_RUN_CONFIG = CONFIG_DIR / "default.run.json"
ROUTER_CONFIG = CONFIG_DIR / "router.json"

CACHE_DIR = ROOT / "cache"
OUT_DIR = ROOT / "out"
LOG_DIR = ROOT / "logs"
STATE_PATH = ROOT / "state.json"
PROGRESS_PATH = ROOT / "progress.md"
ITERATION_LOG_PATH = ROOT / "ITERATION_LOG.md"

# The only location outside the workspace we are allowed to write to.
SKILLS_ROOT = Path(os.environ.get("BOOKLEME_SKILLS_ROOT", str(Path.home() / "Desktop/skills")))
OFFICIAL_QUICK_VALIDATE = SKILLS_ROOT / ".system/skill-creator/scripts/quick_validate.py"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def dump_json(path: Path, obj: object) -> None:
    """Atomic write: temp file + os.replace, so a crashed stage never leaves a half file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)


def load_run_config(overrides: dict | None = None) -> dict:
    cfg = load_json(DEFAULT_RUN_CONFIG)
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


def load_router_config() -> dict:
    return load_json(ROUTER_CONFIG)
