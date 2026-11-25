"""Plugin discovery with explicit priority and a pre-load safety scan."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from .validator import validate_plugin

PRIORITY = ["builtin", "user", "external"]  # later overrides earlier


def _load_file(path: Path):
    spec = importlib.util.spec_from_file_location(f"bookleme_plugin_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load plugin from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin = getattr(module, "PLUGIN", None)
    if plugin is None:
        raise ValueError(f"{path} does not define PLUGIN")
    plugin.source_path = str(path)
    return plugin


def load_plugins(extra_dir: str | None = None) -> tuple[dict[str, object], list[dict]]:
    """Return (registry, diagnostics). Higher priority overrides lower on same genre_id."""
    from ..config import ROOT

    dirs = {
        "builtin": ROOT / "bookleme/plugins/builtin",
        "user": ROOT / "bookleme/plugins/user",
    }
    if extra_dir:
        dirs["external"] = Path(extra_dir)

    registry: dict[str, object] = {}
    diagnostics: list[dict] = []
    for level in PRIORITY:
        directory = dirs.get(level)
        if not directory or not directory.exists():
            continue
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("__"):
                continue
            try:
                plugin = _load_file(path)
                errors = validate_plugin(plugin, str(path))
                if errors:
                    diagnostics.append({"path": str(path), "level": level,
                                        "status": "rejected", "errors": errors})
                    continue
                prev = registry.get(plugin.genre_id)
                if prev is not None:
                    diagnostics.append({"path": str(path), "level": level,
                                        "status": "override",
                                        "note": f"覆盖 {getattr(prev, 'source_path', '')}"})
                registry[plugin.genre_id] = plugin
                diagnostics.append({"path": str(path), "level": level, "status": "loaded"})
            except Exception as exc:
                diagnostics.append({"path": str(path), "level": level,
                                    "status": "error", "errors": [f"{type(exc).__name__}: {exc}"]})
    return registry, diagnostics


def resolve_plugin(registry: dict[str, object], engine: str, genres: list[str]) -> tuple[object | None, str]:
    """Pick the plugin for an engine; fall back is recorded honestly in the reason."""
    preferred = "knowledge_reference" if engine == "knowledge_pack" else genres[0] if genres else ""
    plugin = registry.get(preferred)
    if plugin is not None and engine in getattr(plugin, "default_engines", []):
        return plugin, f"preferred:{preferred}"

    for gid, candidate in registry.items():
        if engine in getattr(candidate, "default_engines", []) and (
            engine == "knowledge_pack" or getattr(candidate, "engine_kind", "") == "behavior"
        ):
            return candidate, f"fallback:{gid} (preferred={preferred!r} unavailable)"

    if engine == "behavior_skill" and preferred in registry:
        return registry[preferred], f"forced:{preferred} (default_engines mismatch)"
    return None, f"no-plugin-for-{engine}"
