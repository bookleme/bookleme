"""BookLeme stage DAG S0-S9.

Deterministic ETL + plugin-driven rendering. No LLM API calls in this batch:
S4 uses a deterministic (markup / heuristic) capability extractor and S3
ambiguity resolution uses a deterministic fallback with explicit honesty flags.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from . import llm
from .config import (
    CACHE_DIR, DEFAULT_RUN_CONFIG, ITERATION_LOG_PATH, LOG_DIR, OFFICIAL_QUICK_VALIDATE,
    OUT_DIR, PROGRESS_PATH, ROOT, ROUTER_CONFIG, SCHEMA_DIR, STATE_PATH, dump_json, load_json,
)
from .hashing import sha256_file, sha256_text, stage_input_hash
from .state import StateStore
from .extract import SUPPORTED_EXTENSIONS, extract_source, merge
from .segment import segment_text
from .router import route
from .capabilities import extract_capabilities
from .fidelity import build_claim_ledger, build_fidelity_report, verify_quotes
from .render import build_description, render_skill
from .plugins import load_plugins, resolve_plugin
from .validate import lint_skill_dir, run_copyright_gate, validate_skill
from .eval import run_smoke
from .provenance import build_manifest
from .install import install_skill
from .schema_check import validate as schema_validate

SCHEMA_FOR = {
    "sources.json": "sources.schema.json",
    "segments.json": "segments.schema.json",
    "capabilities.json": "capabilities.schema.json",
    "capabilities_verified.json": "capabilities.schema.json",
    "claim_ledger.json": "claim_ledger.schema.json",
    "provenance_manifest.json": "provenance.schema.json",
    "router_result.json": "router_result.schema.json",
    "state.json": "state.schema.json",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Logger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lines: list[str] = []

    def __call__(self, msg: str) -> None:
        line = f"[{_now()}] {msg}"
        self.lines.append(line)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(msg, flush=True)


class PipelineError(RuntimeError):
    pass


class Pipeline:
    def __init__(self, config: dict, router_cfg: dict, milestone: str = "M0-M2"):
        self.config = config
        self.router_cfg = router_cfg
        self.milestone = milestone
        self.state = StateStore(STATE_PATH)

    # ---------- helpers ----------
    def _write(self, path: Path, obj: dict, log: Logger) -> None:
        dump_json(Path(path), obj)
        name = Path(path).name
        if name in SCHEMA_FOR:
            errors = schema_validate(obj, load_json(SCHEMA_DIR / SCHEMA_FOR[name]))
            if errors:
                raise PipelineError(f"{name} 未通过 schema 校验：{errors[:5]}")
        log(f"    wrote {path}")

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def _official_validate(self, skill_dir: Path) -> dict:
        if not OFFICIAL_QUICK_VALIDATE.exists():
            return {"status": "unavailable", "reason": "official quick_validate.py not found"}
        env = os.environ.copy()
        vendor = ROOT / ".vendor"
        env["PYTHONPATH"] = str(vendor) + os.pathsep + env.get("PYTHONPATH", "")
        try:
            proc = subprocess.run(
                [sys.executable, str(OFFICIAL_QUICK_VALIDATE), str(skill_dir)],
                capture_output=True, text=True, env=env, timeout=60,
            )
            return {"status": "passed" if proc.returncode == 0 else "failed",
                    "returncode": proc.returncode,
                    "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}
        except Exception as exc:
            return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}

    # ---------- main ----------
    def run(self, input_paths: list[str], *, run_id: str | None = None,
            engine: str | None = None, genre: str | None = None, no_router: bool = False,
            install: bool = False, title: str | None = None, author: str = "",
            isbn: str = "", language: str = "zh", user_rights: str | None = None,
            public: bool = False, confirm_public: str | None = None,
            extra_plugin_dir: str | None = None, dry_run: bool = False) -> dict:

        run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        llm.reset_counters()  # per-run LLM 调用计数
        log_path = LOG_DIR / self.milestone / f"run-{run_id}.log"
        log = Logger(log_path)
        out_dir = OUT_DIR / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        log(f"[BATCH] 计划总量：9 个 stage (S0-S9)，输入源 {len(input_paths)} 个；里程碑 {self.milestone}")
        log(f"[BATCH] 实时日志：{log_path}（进度 {PROGRESS_PATH} / {STATE_PATH}）")
        log("[BATCH] 预计完成：约 30-45 分钟（heuristic 估计，非承诺）")
        self._write_text(PROGRESS_PATH,
                         f"# BookLeme 进度（最新批次 {run_id}）\n\n"
                         f"- 计划总量：S0-S9 共 9 个 stage；输入源 {len(input_paths)} 个\n"
                         f"- 日志绝对路径：{log_path}\n"
                         f"- 预计完成：约 30-45 分钟（估计）\n\n"
                         f"## Stage 记录\n")

        rights = user_rights or self.config["user_rights"]
        book_title = title or Path(input_paths[0]).stem
        model_fingerprint = f"deterministic-{__version__} (no LLM judge in this batch)"

        # ---------------- S0 Intake ----------------
        log("S0 Intake")
        sources: list[dict] = []
        for i, raw in enumerate(input_paths, 1):
            p = Path(raw).expanduser().resolve()
            if not p.is_file():
                raise PipelineError(f"输入文件不存在：{p}")
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                raise PipelineError(f"不支持的格式：{p.suffix}")
            # 用文件 mtime 而非当前时间：sources.json 是共享 IR，含易变时间会
            # 让不同 run_id 互相覆盖并打断 S1 的幂等。
            mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
            sources.append({
                "source_id": f"SRC-{i:03d}", "origin": "local", "kind": p.suffix.lower(),
                "path": str(p), "url": "", "sha256": sha256_file(p), "bytes": p.stat().st_size,
                "mime": mimetypes.guess_type(p.name)[0] or "application/octet-stream",
                "tier": "S", "license_note": f"user_rights={rights}",
                "retrieved_at": mtime, "extract_status": "pending", "figure_text_lost": False,
            })
        public_dir = ROOT / "sources/public"
        public_data: dict[str, dict] = {}
        if public_dir.exists():
            for f in sorted(public_dir.glob("*.json")):
                data = load_json(f)
                sid = f"SRC-{len(sources) + 1:03d}"
                public_data[sid] = data
                sources.append({
                    "source_id": sid, "origin": "public", "kind": "public-json",
                    "path": str(f), "url": data.get("url", ""),
                    "sha256": sha256_text(data.get("content", "")),
                    "bytes": len(data.get("content", "").encode("utf-8")),
                    "mime": "text/plain", "tier": data.get("tier", "B"),
                    "license_note": data.get("license_note", ""),
                    "retrieved_at": data.get("retrieved_at", ""),
                    "extract_status": "pending", "figure_text_lost": False,
                })
        if not sources:
            raise PipelineError("没有可用输入源")

        book_sha256 = sha256_text("|".join(s["sha256"] for s in sources))
        cache = CACHE_DIR / book_sha256[:12]
        cache.mkdir(parents=True, exist_ok=True)
        # sources.json 是跨 run 共享 IR（内容须稳定）；provenance_manifest.json
        # 含 run_id / generated_at，必须按 run 隔离，否则不同 run 会串味。
        s0_paths = [cache / "sources.json", out_dir / "provenance_manifest.json"]
        s0_hash = stage_input_hash([DEFAULT_RUN_CONFIG, str(book_title), rights]
                                   + [s["path"] for s in sources])
        self.state.ensure_run(run_id, book_sha256, model_fingerprint,
                              engine_config_hash=stage_input_hash([self.config, self.router_cfg]))
        if self.state.should_skip(run_id, "S0", s0_hash, s0_paths):
            log("S0 SKIP（input_sha256 未变且产物齐全）")
            sources_obj = load_json(s0_paths[0])
            manifest = load_json(s0_paths[1])
        else:
            sources_obj = {
                "schema_version": "1.0",
                "run_id": f"shared-{book_sha256[:12]}",  # 稳定标识，不随 run 变化
                "book_sha256": book_sha256, "sources": sources,
            }
            manifest = build_manifest(
                run_id=run_id, title=book_title, author=author, isbn=isbn,
                language=language, book_sha256=book_sha256, file_count=len(sources),
                user_rights=rights, sources=sources, config=self.config,
                model_fingerprint=model_fingerprint,
            )
            self._write(s0_paths[0], sources_obj, log)
            self._write(s0_paths[1], manifest, log)
            self.state.mark(run_id, "S0", s0_hash, s0_paths)

        # ---------------- S1 Extract ----------------
        log("S1 Extract（确定性 ETL）")
        s1_paths = [cache / "full_text.txt", cache / "char_map.json",
                    cache / "toc.json", cache / "extraction_report.json"]
        s1_hash = stage_input_hash([s0_paths[0], DEFAULT_RUN_CONFIG])
        if self.state.should_skip(run_id, "S1", s1_hash, s1_paths):
            log("S1 SKIP")
            full_text = s1_paths[0].read_text(encoding="utf-8")
            char_map = load_json(s1_paths[1])
            toc_loaded = load_json(s1_paths[2])
            # toc.json 落盘为 {"schema_version", "entries": [...]}，而
            # merge() 在内存里返回的是 list；两条路径必须统一，否则 S3 重算会炸。
            toc = toc_loaded.get("entries", []) if isinstance(toc_loaded, dict) else toc_loaded
        else:
            results = []
            report_rows = []
            for src in sources:
                if src["origin"] == "public":
                    data = public_data.get(src["source_id"], {})
                    res = {"raw_text": data.get("content", ""), "toc": [], "status": "ok",
                           "figure_text_lost": False, "ocr_used": False,
                           "source_id": src["source_id"], "path": src["path"]}
                    src["tier"] = data.get("tier", "B")
                else:
                    res = extract_source(src)
                    res["source_id"] = src["source_id"]
                    res["path"] = src["path"]
                    src["extract_status"] = res["status"]
                    src["figure_text_lost"] = bool(res.get("figure_text_lost"))
                results.append(res)
                report_rows.append({
                    "source_id": src["source_id"], "status": res["status"],
                    "reason": res.get("reason", ""),
                    "figure_text_lost": res.get("figure_text_lost", False),
                    "ocr_used": res.get("ocr_used", False),
                    "chars": len(res.get("raw_text", "")),
                })
            full_text, char_map, toc = merge(results)
            self._write_text(s1_paths[0], full_text)
            self._write(s1_paths[1], {"schema_version": "1.0", "map": char_map,
                                      "strategy": "nfkc+strip-zero-width"}, log)
            self._write(s1_paths[2], {"schema_version": "1.0", "entries": toc}, log)
            self._write(s1_paths[3], {"schema_version": "1.0", "run_id": run_id,
                                      "sources": report_rows,
                                      "llm_calls": 0}, log)
            degraded = [r for r in report_rows if r["status"] != "ok"]
            if degraded:
                self._write(out_dir / "degradation_log.json",
                            {"schema_version": "1.0", "degraded_sources": degraded}, log)
            self.state.mark(run_id, "S1", s1_hash, s1_paths,
                            degraded=bool(degraded), note=f"{len(degraded)} 个源降级")

        # ---------------- S2 Segment ----------------
        log("S2 Segment（中英文标题 + 窗口兜底）")
        s2_paths = [cache / "segments.json"]
        # 纳入 segment 源码：改分段规则后必须自动失效缓存，否则旧 segments.json
        # 会被误当成新代码产物（真实书稿目录污染就是这么被掩盖的）。
        segment_sources = sorted((Path(__file__).parent / "segment").glob("*.py"))
        s2_hash = stage_input_hash([s1_paths[0], s1_paths[2], DEFAULT_RUN_CONFIG]
                                   + segment_sources)
        if self.state.should_skip(run_id, "S2", s2_hash, s2_paths):
            log("S2 SKIP")
            segments = load_json(s2_paths[0])
        else:
            segments = segment_text(full_text, toc, self.config)
            segments["book_sha256"] = book_sha256
            self._write(s2_paths[0], segments, log)
            slices_dir = cache / "slices"
            slices_dir.mkdir(parents=True, exist_ok=True)
            for seg in segments["segments"]:
                start, end = seg["char_range"]
                self._write_text(slices_dir / f"{seg['segment_id']}.md",
                                 f"# {seg['heading']}\n\n{full_text[start:end]}\n")
            self.state.mark(run_id, "S2", s2_hash, s2_paths,
                            degraded=segments.get("low_confidence", False),
                            note=f"method={segments['method']}")

        # ---------------- S3 Router ----------------
        log("S3 Router（12 确定性特征 + 歧义兜底）")
        # 路由结果依赖 per-run 的 --engine / --genre / --no-router 覆盖参数，
        # 必须按 run 隔离；放进共享 cache 会让不同参数的 run 互相串味。
        s3_paths = [out_dir / "router_result.json"]
        s3_hash = stage_input_hash([s1_paths[0], s2_paths[0], ROUTER_CONFIG,
                                    str(engine), str(genre), str(no_router)])
        if self.state.should_skip(run_id, "S3", s3_hash, s3_paths):
            log("S3 SKIP")
            router_result = load_json(s3_paths[0])
        else:
            router_result, evidence = route(
                full_text, segments["segments"], toc, self.router_cfg,
                engine_override=engine, genre_override=genre, no_router=no_router,
            )
            self._write(s3_paths[0], router_result, log)
            if evidence:
                self._write(out_dir / "router_evidence.json", evidence, log)
            self.state.mark(run_id, "S3", s3_hash, s3_paths,
                            degraded=router_result["override_source"] == "ambiguity",
                            note=f"top1={router_result['top1']} margin={router_result['margin']}")
        log(f"    体裁 {router_result['genres']} → 引擎 {router_result['engines']} "
            f"({router_result['override_source']})")

        # ---------------- S4 Capabilities ----------------
        log("S4 Capabilities（本批为确定性抽取器，未接 LLM）")
        s4_paths = [cache / "capabilities.json"]
        capability_sources = sorted((Path(__file__).parent / "capabilities").glob("*.py"))
        llm_sources = sorted((Path(__file__).parent / "llm").rglob("*"))
        s4_hash = stage_input_hash([s1_paths[0], s2_paths[0], DEFAULT_RUN_CONFIG]
                                   + capability_sources + llm_sources)
        if self.state.should_skip(run_id, "S4", s4_hash, s4_paths):
            log("S4 SKIP")
            caps = load_json(s4_paths[0])
        else:
            caps = extract_capabilities(full_text, segments["segments"], self.config,
                                        book_title=book_title)
            caps["book_sha256"] = book_sha256
            # genre_tags / engine_targets 是 per-run 的路由结果，不能写进共享
            # capabilities.json；保持为空数组，渲染阶段按本次 engines 过滤。
            self._write(s4_paths[0], caps, log)
            self.state.mark(run_id, "S4", s4_hash, s4_paths,
                            degraded=caps["extractor"] == "heuristic",
                            note=f"extractor={caps['extractor']} caps={len(caps['capabilities'])}")
        log(f"    extractor={caps['extractor']}，原子能力 {len(caps['capabilities'])} 个")

        # ---------------- S5 Fidelity ----------------
        log("S5 Fidelity（逐字引文校验 + 7 指标）")
        s5_paths = [cache / "capabilities_verified.json", cache / "claim_ledger.json",
                    cache / "fidelity_report.json"]
        # 纳入 fidelity 源码：改指标定义 / 未验证假设表后必须自动失效缓存，
        # 否则旧 fidelity_report.json 会被误当成新代码产物。
        fidelity_sources = sorted((Path(__file__).parent / "fidelity").glob("*.py"))
        s5_hash = stage_input_hash([s4_paths[0], s1_paths[0], DEFAULT_RUN_CONFIG]
                                   + fidelity_sources)
        if self.state.should_skip(run_id, "S5", s5_hash, s5_paths):
            log("S5 SKIP")
            caps_v = load_json(s5_paths[0])
            ledger = load_json(s5_paths[1])
            fidelity = load_json(s5_paths[2])
        else:
            caps_v, quote_records = verify_quotes(
                json.loads(json.dumps(caps, ensure_ascii=False)), full_text,
                char_map.get("map", char_map) if isinstance(char_map, dict) else char_map,
                self.config,
            )
            ledger = build_claim_ledger(caps_v, book_sha256, str(cache / "slices"))
            fidelity = build_fidelity_report(caps_v, ledger, segments, quote_records, self.config)
            self._write(s5_paths[0], caps_v, log)
            self._write(s5_paths[1], ledger, log)
            self._write(s5_paths[2], fidelity, log)
            self.state.mark(run_id, "S5", s5_hash, s5_paths,
                            note=f"verified={sum(1 for c in caps_v['capabilities'] if c['status']=='verified')}")
        verified_caps = [c for c in caps_v["capabilities"] if c["status"] == "verified"]
        if not verified_caps:
            raise PipelineError("S5 没有任何 verified capability，无法渲染产物")

        # ---------------- S6 Render ----------------
        log("S6 Render（插件驱动，两引擎共享 IR）")
        registry, diagnostics = load_plugins(extra_plugin_dir)
        self._write(out_dir / "plugin_resolution.json",
                    {"schema_version": "1.0", "available": sorted(registry), "diagnostics": diagnostics}, log)
        if not registry:
            raise PipelineError("没有可用体裁插件")
        artifacts: list[dict] = []
        plugin_files = [Path(getattr(p, "source_path", "")) for p in registry.values()]
        s6_paths = [out_dir / "build_manifest.json"]
        s6_hash = stage_input_hash([s5_paths[0], s2_paths[0], s3_paths[0], DEFAULT_RUN_CONFIG]
                                   + plugin_files)
        if self.state.should_skip(run_id, "S6", s6_hash, s6_paths) and (out_dir / "build").exists():
            log("S6 SKIP")
            build_manifest_obj = load_json(s6_paths[0])
            artifacts = build_manifest_obj["artifacts"]
        else:
            for eng in router_result["engines"]:
                plugin, reason = resolve_plugin(registry, eng, router_result["genres"])
                if plugin is None:
                    raise PipelineError(f"S6 找不到引擎 {eng} 的插件：{reason}")
                short = "kp" if eng == "knowledge_pack" else "bs"
                slug = f"book-{book_sha256[:8]}-{short}"
                display = f"{book_title[:12]}·{plugin.display_name_zh}"
                description = build_description(plugin, book_title, self.config)
                ctx = {
                    "slug": slug, "display_name": display, "description": description,
                    "book_title": book_title, "author": author, "engine": eng,
                    "run_id": run_id, "config": self.config,
                    "verified_capabilities": verified_caps,
                    "segments": segments, "provenance_manifest": manifest,
                    "fidelity_report": fidelity, "router_result": router_result,
                }
                files = plugin.render(ctx)
                target = out_dir / "build" / eng / f"{display}（{slug}）"
                for rel, content in files.items():
                    self._write_text(target / rel, content)
                artifacts.append({
                    "engine": eng, "genre_id": plugin.genre_id, "plugin_reason": reason,
                    "slug": slug, "display_name": display, "description": description,
                    "skill_dir": str(target), "files": sorted(files),
                })
                log(f"    {eng}: {target}（{len(files)} 个文件）")
            build_manifest_obj = {"schema_version": "1.0", "run_id": run_id,
                                  "shared_ir": [str(p) for p in [s1_paths[0], s2_paths[0],
                                                                 s4_paths[0], s5_paths[1]]],
                                  "artifacts": artifacts}
            self._write(s6_paths[0], build_manifest_obj, log)
            self.state.mark(run_id, "S6", s6_hash, s6_paths)

        # ---------------- S7 Validate ----------------
        log("S7 Validate（quick_validate + 官方校验器 + lint + copyright_gate）")
        s7_paths = [out_dir / "validation_report.json"]
        s7_hash = stage_input_hash([s6_paths[0], s1_paths[0], DEFAULT_RUN_CONFIG]
                                   + [Path(a["skill_dir"]) / "SKILL.md" for a in artifacts])
        if self.state.should_skip(run_id, "S7", s7_hash, s7_paths):
            log("S7 SKIP")
            validation = load_json(s7_paths[0])
        else:
            quotes = [c["ria"]["R_quote"] for c in verified_caps]
            per_artifact = []
            shingle_max = 0.0
            for art in artifacts:
                target = Path(art["skill_dir"])
                qv = validate_skill(target)
                official = self._official_validate(target)
                lint = lint_skill_dir(target, self.config["skill_body_max_lines"])
                gate = run_copyright_gate(target, full_text, quotes, self.config)
                shingle_max = max(shingle_max, gate["checks"][3]["value"])
                passed = not qv and not lint and gate["passed"] and official["status"] != "failed"
                per_artifact.append({
                    "engine": art["engine"], "skill_dir": str(target),
                    "quick_validate_errors": qv, "official_validator": official,
                    "lint_errors": lint, "copyright_gate": gate, "all_passed": passed,
                })
            validation = {
                "schema_version": "1.0", "run_id": run_id,
                "all_passed": all(a["all_passed"] for a in per_artifact),
                "shingle_overlap_max_measured": shingle_max,
                "artifacts": per_artifact,
            }
            self._write(s7_paths[0], validation, log)
            self.state.mark(run_id, "S7", s7_hash, s7_paths)
            if not validation["all_passed"]:
                failures = [a for a in per_artifact if not a["all_passed"]]
                raise PipelineError(f"S7 硬门失败，产物不安装不发布：{json.dumps(failures, ensure_ascii=False)[:1200]}")

        # distribution decision as a start-flag gate, never asked mid-run
        if public and confirm_public != "PUBLISH":
            raise PipelineError("公开分发必须在启动命令显式给 --public --confirm-public PUBLISH")
        self._write(out_dir / "distribution_decision.json", {
            "schema_version": "1.0", "default": "private",
            "requested_public": public, "confirm_public": confirm_public or "",
            "user_rights": rights, "hard_gates_passed": validation["all_passed"],
            "note": "默认私有；本批不执行任何远端发布动作。",
        }, log)

        # ---------------- S8 Install (optional) ----------------
        if install and not dry_run:
            log("S8 Install（写入技能真源）")
            receipts = []
            for art in artifacts:
                category = (self.config["category_knowledge"] if art["engine"] == "knowledge_pack"
                            else self.config["category_behavior"])
                receipt = install_skill(
                    Path(art["skill_dir"]), category=category,
                    display_name=art["display_name"], slug=art["slug"],
                    frontmatter_name=art["slug"], distribution="private",
                )
                receipts.append(receipt)
            self._write(out_dir / "install_receipt.json",
                        {"schema_version": "1.0", "receipts": receipts}, log)
            self.state.mark(run_id, "S8", stage_input_hash([s7_paths[0]]),
                            [out_dir / "install_receipt.json"])
        else:
            log("S8 SKIP（未请求 --install；本批不写技能真源）")
            self.state.mark(run_id, "S8", "skipped", [], status="skipped", note="install=false")

        # ---------------- S9 Eval ----------------
        log("S9 Eval（冒烟 + 指标汇总）")
        s9_paths = [out_dir / "metrics.json"]
        # metrics.json 抄录了 fidelity_report 的指标与未验证假设表，故一并纳入。
        s9_hash = stage_input_hash([s7_paths[0], s6_paths[0], s5_paths[2]])
        if self.state.should_skip(run_id, "S9", s9_hash, s9_paths):
            log("S9 SKIP")
        else:
            metrics = {
                "schema_version": "1.0", "run_id": run_id,
                "extractor": caps_v["extractor"],
                "llm_calls": llm.llm_calls,
                "model_fingerprint": (llm.model_fingerprint("capability_extract_v1")
                                      if caps_v["extractor"] == "llm" else None),
                "fidelity": fidelity["metrics"],
                "smoke": [], "router": router_result,
                "unverified_assumptions": fidelity["unverified_assumptions"],
                "note": ("S4 已接入 LLM 抽取器（引文仍逐字回验）；S3 judge 仍为确定性实现。"
                         if caps_v["extractor"] == "llm"
                         else "S4 为确定性抽取器；heuristic 指标值为 null，不伪造。"),
            }
            refusal_values = []
            for art in artifacts:
                plugin = registry.get(art["genre_id"])
                smoke = run_smoke(Path(art["skill_dir"]), plugin, art["description"],
                                  verified_caps, validation)
                metrics["smoke"].append({"engine": art["engine"], **smoke})
                refusal_values.append(smoke["metrics"]["negative_refusal_rate"]["value"])
            metrics["fidelity"]["shingle_overlap_max"]["value"] = validation["shingle_overlap_max_measured"]
            metrics["fidelity"]["negative_refusal_rate"]["value"] = (
                min(refusal_values) if refusal_values else None
            )
            self._write(s9_paths[0], metrics, log)
            self.state.mark(run_id, "S9", s9_hash, s9_paths)

        with PROGRESS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"\n- [{_now()}] run {run_id} 完成：S0-S9 全部执行/跳过幂等；"
                     f"产物 {len(artifacts)} 个；validation.all_passed={validation['all_passed']}\n")
        with ITERATION_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"\n## run {run_id} ({_now()})\n"
                     f"- book_sha256={book_sha256}\n"
                     f"- extractor={caps_v['extractor']}, caps={len(caps_v['capabilities'])}, "
                     f"verified={len(verified_caps)}\n"
                     f"- router={router_result['genres']} engines={router_result['engines']} "
                     f"margin={router_result['margin']}\n"
                     f"- artifacts={len(artifacts)}, all_passed={validation['all_passed']}\n"
                     f"- log={log_path}\n")

        summary = {
            "run_id": run_id, "book_sha256": book_sha256,
            "cache_dir": str(cache), "out_dir": str(out_dir), "log": str(log_path),
            "artifacts": [a["skill_dir"] for a in artifacts],
            "validation_all_passed": validation["all_passed"],
            "metrics_path": str(out_dir / "metrics.json"),
            "validation_path": s7_paths[0].__str__(),
            "llm_calls": llm.llm_calls,
        }
        log(f"[BATCH] 完成：{len(artifacts)} 个产物，all_passed={validation['all_passed']}；"
            f"日志 {log_path}")
        return summary
