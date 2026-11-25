"""BookLeme command line interface. Zero third-party dependencies."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from . import __version__
from .config import DEFAULT_RUN_CONFIG, OUT_DIR, ROOT, ROUTER_CONFIG, load_json, load_router_config, load_run_config
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
    run.add_argument("--engine", choices=["auto", "knowledge_pack", "behavior_skill", "both"], default=None,
                     help="产物形态；默认按体裁自动决定，一般不用指定")
    run.add_argument("--genre", default=None,
                     help="强制指定体裁插件 id（可用值见 `bookleme plugin list`）；默认由路由自动判定")
    run.add_argument("--no-router", action="store_true", help="跳过体裁判定，两个引擎都出")
    run.add_argument("--install", action="store_true", help="写入技能真源（默认关闭，只出产物不落盘）")
    run.add_argument("--dry-run", action="store_true",
                     help="（已废弃：默认就是不安装。保留只为兼容旧命令，会提示一声）")
    run.add_argument("--title", default=None)
    run.add_argument("--author", default="")
    run.add_argument("--isbn", default="")
    run.add_argument("--language", default="zh")
    run.add_argument("--user-rights", choices=["owned", "licensed", "public_domain", "unknown"], default=None,
                     help="仅在要公开分发时才需要声明；默认按「权利未确认」处理（私有自用、禁止公开）")
    run.add_argument("--public", action="store_true", help="申请公开分发（需同时给 --confirm-public PUBLISH）")
    run.add_argument("--confirm-public", default=None, help="公开分发的裸词确认：PUBLISH")
    run.add_argument("--plugin-dir", default=None, help="额外的体裁插件目录（不存在会明确报错，不再静默忽略）")
    run.add_argument("--run-id", default=None)

    plugin = sub.add_parser("plugin", help="体裁插件工具")
    psub = plugin.add_subparsers(dest="plugin_cmd", required=True)
    pl = psub.add_parser("list", help="列出可用体裁插件")
    pl.add_argument("--json", action="store_true", help="输出 JSON")
    pv = psub.add_parser("validate", help="校验插件 18 个必填字段")
    pv.add_argument("file", help="插件 .py 绝对路径")

    val = sub.add_parser("validate", help="校验一个 skill 产物目录")
    val.add_argument("skill_dir")

    fet = sub.add_parser("fetch", help="抓取公开网页/论文到 sources/public（2.0）")
    fet.add_argument("url", help="http(s) 地址（网页或 PDF 论文）")
    fet.add_argument("--name", default=None, help="自定义文件名（slug）")
    fet.add_argument("--tier", choices=["A", "B", "C"], default="B",
                     help="来源分级（见 docs/COPYRIGHT.md）：A=作者访谈或官方讲义 / "
                          "B=权威书评与公开网络内容 / C=推算；网页抓取默认 B")
    fet.add_argument("--license-note", default="", help="授权说明（自行核实后填写）")
    fet.add_argument("--no-images", action="store_true", help="不下载页面图片")

    ev = sub.add_parser("eval", help="查看某次 run 的指标")
    ev.add_argument("--run-id", required=True)
    ev.add_argument("--json", action="store_true", help="输出完整 JSON（默认给人话摘要）")

    sch = sub.add_parser("schema", help="校验所有 JSON Schema 文件与 state.json")
    sch.add_argument("--state", action="store_true")

    doc = sub.add_parser("doctor", help="自检：环境、LLM 可用性、最近一次运行（无需你配置任何东西）")
    doc.add_argument("--run-id", default=None, help="指定要体检的 run（默认最近一次）")

    ins = sub.add_parser("inspect", help="生成编译产物检视台（单文件 HTML，离线可看）")
    ins.add_argument("run_id", nargs="?", default=None, help="run id（默认最近一次）")
    ins.add_argument("--open", action="store_true", help="生成后直接打开")
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


def _plugin_list(as_json: bool) -> int:
    from .plugins import load_plugins
    registry, diagnostics = load_plugins()
    rows = []
    for gid in sorted(registry):
        p = registry[gid]
        rows.append({"genre_id": gid, "display_name_zh": getattr(p, "display_name_zh", ""),
                     "version": getattr(p, "version", ""),
                     "default_engines": getattr(p, "default_engines", [])})
    if as_json:
        print(json.dumps({"plugins": rows,
                          "broken": [d for d in diagnostics if d.get("status") in ("rejected", "error")]},
                         ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("没有可用插件。")
        return 0
    print("可用体裁插件（--genre <id> 选用）：\n")
    for r in rows:
        print(f"  {r['genre_id']:<22} {r['display_name_zh']:<12} "
              f"{'/'.join(r['default_engines'])}")
    broken = [d for d in diagnostics if d.get("status") in ("rejected", "error")]
    if broken:
        print("\n有插件未加载：")
        for d in broken:
            print(f"  {d.get('path', '')}: {str(d.get('errors'))[:160]}")
    return 0


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
    # 配置也要过 schema：配置写错时给出「哪一项不合规」，而不是跑到一半报 KeyError
    for cfg_path, schema_name in ((DEFAULT_RUN_CONFIG, "default.run.schema.json"),
                                  (ROUTER_CONFIG, "router.schema.json")):
        key = f"configs/{cfg_path.name}"
        try:
            errors = schema_validate(load_json(cfg_path), load_json(SCHEMA_DIR / schema_name))
            results[key] = "ok" if not errors else f"invalid: {errors[:5]}"
        except Exception as exc:
            results[key] = f"invalid: {exc}"
    if state and STATE_PATH.exists():
        state_obj = load_json(STATE_PATH)
        errors = schema_validate(state_obj, load_json(SCHEMA_DIR / "state.schema.json"))
        results["state.json"] = "ok" if not errors else f"invalid: {errors[:3]}"
    ok = all(v == "ok" for v in results.values())
    print(json.dumps({"passed": ok, "files": results}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def _print_eval_summary(run_id: str, data: dict) -> None:
    """人话摘要：这次编得怎么样、哪里要留意、null 意味着什么。"""
    fid = data.get("fidelity", {}) or {}
    figs = data.get("figures", {}) or {}
    judge = data.get("judge_summary", {}) or {}

    def fmt(key):
        m = fid.get(key)
        if not isinstance(m, dict):
            return "—"
        v = m.get("value")
        if v is None:
            return "未判定"
        if isinstance(v, (int, float)) and 0 <= v <= 1:
            return f"{v * 100:.1f}%"
        return str(v)

    print(f"run {run_id} · 抽取方式 {data.get('extractor') or '—'} · "
          f"LLM 调用 {data.get('llm_calls', 0)} 次")
    print("  忠实度：覆盖度 " + fmt("coverage_score")
          + " · 逐字违规率 " + fmt("verbatim_violation_rate")
          + " · 无支撑断言率 " + fmt("unsupported_claim_rate")
          + " · groundedness " + fmt("groundedness"))
    if figs:
        print(f"  图示：{figs.get('total', 0)} 张（带位图 {figs.get('with_images', 0)}，"
              f"仅图注 {figs.get('caption_only', 0)}，已锚定 {figs.get('anchored', 0)}）")
    if judge.get("enabled"):
        print(f"  judge：判定 {judge.get('judged', 0)} 张卡，"
              f"支持 {judge.get('grounded', 0)}，未判定 {judge.get('grounded_unknown', 0)}，"
              f"调用失败 {judge.get('failed_calls', 0)}")
    else:
        print("  judge：未接入（groundedness / V2 / V3 如实为 null，未伪造）")
    nulls = [k for k, v in fid.items()
             if isinstance(v, dict) and v.get("value") is None]
    if nulls:
        print("  注意：以下指标未判定 —— " + "、".join(nulls) + "（原因见 metrics.json 的 note）")
    print(f"  完整指标：{OUT_DIR / run_id / 'metrics.json'}")


def _doctor(run_id: str | None) -> int:
    """自检：把「需要人判断的事」收进系统，输出结论 + 下一步，而不是让用户去配环境。"""
    from . import llm
    from .config import CACHE_DIR, SKILLS_ROOT
    from .plugins import load_plugins

    registry, diagnostics = load_plugins()
    runs = []
    if OUT_DIR.exists():
        for d in OUT_DIR.iterdir():
            if d.is_dir():
                runs.append((d.stat().st_mtime, d.name))
    runs.sort(reverse=True)
    target = run_id or (runs[0][1] if runs else "")
    last = {"run_id": target}
    if target:
        rdir = OUT_DIR / target
        val = rdir / "validation_report.json"
        met = rdir / "metrics.json"
        if val.is_file():
            v = load_json(val)
            last["all_passed"] = v.get("all_passed")
            last["artifacts"] = len(v.get("artifacts", []))
        if met.is_file():
            m = load_json(met)
            last["figures"] = m.get("figures", {})
            last["extractor"] = m.get("extractor")
            last["groundedness"] = (m.get("fidelity", {}).get("groundedness", {}) or {}).get("value")
    report = {
        "ok": True,
        "llm": llm.describe(),
        "paths": {
            "root": str(ROOT), "out": str(OUT_DIR), "cache": str(CACHE_DIR),
            "skills_root": str(SKILLS_ROOT),
            "skills_root_exists": SKILLS_ROOT.exists(),
        },
        "plugins": {
            "available": sorted(registry),
            "broken": [d for d in diagnostics if d.get("status") in ("rejected", "error")],
        },
        "runs_on_disk": len(runs),
        "last_run": last,
        "next": [
            "读图（多模态）由使用本技能的智能体完成，无需配置视觉模型",
            "编译期 judge/抽取是可选项：没有 LLM 也照常出产物，指标如实记 null",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "run":
        # ── 开跑前把「用户能自己判断的事」拦在这里，别等流水线跑一半才报错 ──
        if args.public and args.confirm_public != "PUBLISH":
            print("[ERROR] 公开分发需要同时给 --public --confirm-public PUBLISH（裸词确认）。"
                  "只想自己用就不要加 --public。", file=sys.stderr)
            return 1
        if args.public and not args.user_rights:
            print("[ERROR] 公开分发必须先声明使用权利：加 --user-rights "
                  "owned|licensed|public_domain。权利未确认时不能公开分发。", file=sys.stderr)
            return 1
        if args.public and args.user_rights == "unknown":
            print("[ERROR] --user-rights unknown 与 --public 冲突：权利未确认不得公开分发。",
                  file=sys.stderr)
            return 1
        if args.plugin_dir and not Path(args.plugin_dir).expanduser().is_dir():
            print(f"[ERROR] 插件目录不存在：{args.plugin_dir}", file=sys.stderr)
            return 1
        if args.dry_run:
            print("[提示] --dry-run 已废弃：默认就不安装产物。加 --install 才会写入技能真源。",
                  file=sys.stderr)
        if args.genre:
            from .plugins import load_plugins
            registry, _ = load_plugins(args.plugin_dir)
            if args.genre not in registry:
                print(f"[ERROR] 没有这个体裁插件：{args.genre}\n"
                      f"       可用：{', '.join(sorted(registry))}\n"
                      f"       （不给 --genre 时由路由自动判定）", file=sys.stderr)
                return 1
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
                extra_plugin_dir=args.plugin_dir,
            )
        except PipelineError as exc:
            # 失败也要给出「东西在哪、怎么继续」——只留一句报错等于把人扔在半路
            from datetime import datetime as _dt
            effective_run = args.run_id or _dt.now().strftime("%Y%m%d-%H%M%S")
            out_dir = OUT_DIR / effective_run
            log_path = ROOT / "logs" / "M0-M2" / f"run-{effective_run}.log"
            empty = out_dir.is_dir() and not any(out_dir.iterdir())
            if empty:
                out_dir.rmdir()          # 没产出东西就别留空目录冒充「有结果」
            print(f"[ERROR] {exc}", file=sys.stderr)
            print(f"        run_id : {effective_run}", file=sys.stderr)
            if not empty:
                print(f"        产物   : {out_dir}", file=sys.stderr)
            print(f"        日志   : {log_path}", file=sys.stderr)
            return 1
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.command == "doctor":
        return _doctor(args.run_id)
    if args.command == "inspect":
        from .inspect import write
        run_id = args.run_id
        if not run_id:
            runs = sorted((d.stat().st_mtime, d.name) for d in OUT_DIR.iterdir() if d.is_dir())
            if not runs:
                print("[ERROR] 还没有任何 run，先跑一次 `bookleme run`。", file=sys.stderr)
                return 1
            run_id = runs[-1][1]
        try:
            path = write(run_id)
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"run_id": run_id, "inspect": str(path),
                          "note": "单文件 HTML：双击即可打开，图片走相对路径（需与 build/ 同目录）"},
                         ensure_ascii=False, indent=2))
        if args.open:
            import webbrowser
            webbrowser.open(f"file://{path}")
        return 0
    if args.command == "fetch":
        from .fetch import fetch_url
        try:
            record = fetch_url(args.url, name=args.name, tier=args.tier,
                               license_note=args.license_note,
                               save_images=not args.no_images)
        except Exception as exc:
            print(f"[ERROR] 抓取失败：{exc}", file=sys.stderr)
            return 1
        summary = {k: record.get(k, "") for k in ("kind", "url", "tier", "retrieved_at", "bytes")}
        summary["images"] = len(record.get("images", []))
        summary["content_chars"] = len(record.get("content", ""))
        summary["record"] = str(ROOT / "sources" / "public")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.command == "plugin" and args.plugin_cmd == "list":
        return _plugin_list(args.json)
    if args.command == "plugin" and args.plugin_cmd == "validate":
        return _plugin_validate(args.file)
    if args.command == "validate":
        return _validate_skill_dir(args.skill_dir)
    if args.command == "eval":
        metrics = OUT_DIR / args.run_id / "metrics.json"
        if not metrics.exists():
            print(f"[ERROR] 未找到 {metrics}", file=sys.stderr)
            return 1
        data = load_json(metrics)
        if getattr(args, "json", False):
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        _print_eval_summary(args.run_id, data)
        return 0
    if args.command == "schema":
        return _schema_check(args.state)
    return 2
