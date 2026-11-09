"""BookLeme command line interface. Zero third-party dependencies."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from . import __version__
from .config import DEFAULT_RUN_CONFIG, OUT_DIR, ROUTER_CONFIG, load_json, load_router_config, load_run_config
from .pipeline import Pipeline, PipelineError
from .plugins.validator import validate_plugin
from .validate import lint_skill_dir, validate_skill
from .state import StateStore
from .schema_check import validate as schema_validate


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bookleme", description="把一本书编译成可安装的 Agent Skill")
    parser.add_argument("--version", action="version", version=f"bookleme {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="运行 S0-S9 编译流水线")
    run.add_argument("--input", nargs="+", required=True, help="本地有权文件路径（可多个）")
    run.add_argument("--engine", choices=["auto", "knowledge_pack", "behavior_skill", "both"], default=None)
    run.add_argument("--genre", default=None, help="强制指定体裁插件 id")
    run.add_argument("--no-router", action="store_true", help="关闭路由，双引擎全出")
    run.add_argument("--install", action="store_true", help="写入技能真源（默认关闭）")
    run.add_argument("--dry-run", action="store_true", help="不安装（默认即不安装）")
    run.add_argument("--title", default=None)
    run.add_argument("--author", default="")
    run.add_argument("--isbn", default="")
    run.add_argument("--language", default="zh")
    run.add_argument("--user-rights", choices=["owned", "licensed", "public_domain", "unknown"], default=None)
    run.add_argument("--public", action="store_true")
    run.add_argument("--confirm-public", default=None)
    run.add_argument("--plugin-dir", default=None)
    run.add_argument("--run-id", default=None)

    plugin = sub.add_parser("plugin", help="体裁插件工具")
    psub = plugin.add_subparsers(dest="plugin_cmd", required=True)
    pv = psub.add_parser("validate", help="校验插件 16 个必填字段")
    pv.add_argument("file", help="插件 .py 绝对路径")

    val = sub.add_parser("validate", help="校验一个 skill 产物目录")
    val.add_argument("skill_dir")

    ev = sub.add_parser("eval", help="查看某次 run 的指标")
    ev.add_argument("--run-id", required=True)

    sch = sub.add_parser("schema", help="校验所有 JSON Schema 文件与 state.json")
    sch.add_argument("--state", action="store_true")
    return parser


def _plugin_validate(path: str) -> int:
    p = Path(path).resolve()
    spec = importlib.util.spec_from_file_location("bookleme_cli_plugin", p)
    if spec is None or spec.loader is None:
        print(json.dumps({"passed": False, "errors": [f"无法加载 {p}"]}, ensure_ascii=False, indent=2))
        return 1
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin = getattr(module, "PLUGIN", None)
    if plugin is None:
        print(json.dumps({"passed": False, "errors": ["文件未定义 PLUGIN"]}, ensure_ascii=False, indent=2))
        return 1
    plugin.source_path = str(p)
    errors = validate_plugin(plugin, str(p))
    print(json.dumps({"passed": not errors, "genre_id": getattr(plugin, "genre_id", ""),
                      "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def _validate_skill_dir(path: str) -> int:
    p = Path(path).resolve()
    qv = validate_skill(p)
    lint = lint_skill_dir(p)
    print(json.dumps({"skill_dir": str(p), "quick_validate_errors": qv,
                      "lint_errors": lint, "all_passed": not qv and not lint},
                     ensure_ascii=False, indent=2))
    return 0 if not qv and not lint else 1


def _schema_check(state: bool) -> int:
    from .config import SCHEMA_DIR, STATE_PATH
    results = {}
    for f in sorted(SCHEMA_DIR.glob("*.schema.json")):
        try:
            load_json(f)
            results[f.name] = "ok"
        except Exception as exc:
            results[f.name] = f"invalid: {exc}"
    if state and STATE_PATH.exists():
        state_obj = load_json(STATE_PATH)
        errors = schema_validate(state_obj, load_json(SCHEMA_DIR / "state.schema.json"))
        results["state.json"] = "ok" if not errors else f"invalid: {errors[:3]}"
    ok = all(v == "ok" for v in results.values())
    print(json.dumps({"passed": ok, "files": results}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "run":
        overrides = {
            "user_rights": args.user_rights,
            "genre": args.genre,
            "install": args.install or None,
        }
        cfg = load_run_config(overrides)
        router_cfg = load_router_config()
        pipe = Pipeline(cfg, router_cfg)
        try:
            summary = pipe.run(
                args.input, run_id=args.run_id,
                engine=None if args.engine in (None, "auto") else args.engine,
                genre=args.genre, no_router=args.no_router,
                install=args.install, title=args.title, author=args.author,
                isbn=args.isbn, language=args.language, user_rights=args.user_rights,
                public=args.public, confirm_public=args.confirm_public,
                extra_plugin_dir=args.plugin_dir, dry_run=args.dry_run,
            )
        except PipelineError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.command == "plugin" and args.plugin_cmd == "validate":
        return _plugin_validate(args.file)
    if args.command == "validate":
        return _validate_skill_dir(args.skill_dir)
    if args.command == "eval":
        metrics = OUT_DIR / args.run_id / "metrics.json"
        if not metrics.exists():
            print(f"[ERROR] 未找到 {metrics}", file=sys.stderr)
            return 1
        print(json.dumps(load_json(metrics), ensure_ascii=False, indent=2))
        return 0
    if args.command == "schema":
        return _schema_check(args.state)
    return 2
