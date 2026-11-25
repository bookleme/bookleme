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
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from . import llm
from .config import (
    CACHE_DIR, DEFAULT_RUN_CONFIG, ITERATION_LOG_PATH, LOG_DIR, OFFICIAL_QUICK_VALIDATE,
    OUT_DIR, PROGRESS_PATH, ROOT, ROUTER_CONFIG, SCHEMA_DIR, STATE_PATH, dump_json, load_json,
)
from .hashing import sha256_file, sha256_text, stage_input_hash
from .intake import expand_paths, infer_title, short_title
from .state import StateStore
from .extract import SUPPORTED_EXTENSIONS, extract_source, merge
from .extract.figures import extract_pdf_figures, html_figure_entries, locate_captions
from .segment import segment_text
from .router import route
from .capabilities import attach_figure_refs, extract_capabilities, extract_figure_cards
from .fidelity import (build_claim_ledger, build_fidelity_report, judge_capabilities,
                      v1_cross_domain, verify_quotes)
from .render import build_description, render_skill
from .plugins import load_plugins, resolve_plugin
from .validate import lint_skill_dir, run_copyright_gate, validate_skill
from .eval import run_smoke
from .provenance import build_manifest, figure_distribution_block
from .install import install_skill, preflight
from .schema_check import validate as schema_validate

SCHEMA_FOR = {
    "sources.json": "sources.schema.json",
    "segments.json": "segments.schema.json",
    "capabilities.json": "capabilities.schema.json",
    "capabilities_verified.json": "capabilities.schema.json",
    "claim_ledger.json": "claim_ledger.schema.json",
    "figures.json": "figures.schema.json",
    "provenance_manifest.json": "provenance.schema.json",
    "router_result.json": "router_result.schema.json",
    "state.json": "state.schema.json",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_host_blocks(cache: Path, run_id: str) -> list[dict] | None:
    """载入宿主 Agent 承接抽取的能力卡（若已回填）。

    宿主判定结果落在 `cache/host_capabilities.json`（由 `bookleme judge
    --apply-capabilities` 写入）。有就用它 —— 这是「零配置拿到真内容」的
    关键：heuristic 模板句没有知识，宿主承接的卡才有。
    """
    p = Path(cache) / "host_capabilities.json"
    if not p.is_file():
        return None
    try:
        data = load_json(p)
    except (OSError, ValueError):
        return None
    blocks = data.get("blocks")
    if isinstance(blocks, list) and blocks:
        return blocks
    return None


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

    def detail(self, msg: str) -> None:
        """只进日志文件、不刷终端（中间产物的逐文件路径属于这类）。

        终端只留「阶段级」信息；用户要的全部绝对路径在 run 结束后的汇总 JSON 里。
        """
        line = f"[{_now()}] {msg}"
        self.lines.append(line)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


class PipelineError(RuntimeError):
    pass


class Pipeline:
    def __init__(self, config: dict, router_cfg: dict, milestone: str = "M0-M2"):
        self.config = config
        self.router_cfg = router_cfg
        self.milestone = milestone
        self.state = StateStore(STATE_PATH)

    # ---------- helpers ----------
    def _write(self, path: Path, obj: dict, log: Logger, quiet: bool = False) -> None:
        dump_json(Path(path), obj)
        name = Path(path).name
        if name in SCHEMA_FOR:
            errors = schema_validate(obj, load_json(SCHEMA_DIR / SCHEMA_FOR[name]))
            if errors:
                raise PipelineError(f"{name} 未通过 schema 校验：{errors[:5]}")
        # 中间产物默认只进日志文件：终端只留「阶段级」信息，完整路径在末尾汇总里给
        if not quiet:
            log.detail(f"wrote {path}")

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # 临时文件名带进程号：并发跑多个流水线时共用同名 .tmp 会互相覆盖
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
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
            extra_plugin_dir: str | None = None, dry_run: bool = False,
            include_public: bool = False) -> dict:

        run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        llm.reset_counters()  # per-run LLM 调用计数
        t_start = time.monotonic()
        # 用户手上可能是目录、网址，或一堆零散文件；先摊平再谈流水线，
        # 别把「整理输入」这件事留给用户（他给什么我们收什么）。
        local_inputs, urls = expand_paths(input_paths)
        if not local_inputs and not urls:
            raise PipelineError(
                "没有可用输入：目录里没有支持的文档"
                "（.md/.txt/.pdf/.docx/.epub/.html/.rtf/.mobi），也没给网址。")
        log_path = LOG_DIR / self.milestone / f"run-{run_id}.log"
        log = Logger(log_path)
        out_dir = OUT_DIR / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # 横幅只给「此刻有用」的信息：总量与日志路径。
        # 不再打「预计 30-45 分钟」——实测大部分批次几秒就跑完，那个估计是误导。
        log(f"[BATCH] 计划总量：9 个 stage (S0-S9)，输入源 {len(local_inputs) + len(urls)} 个")
        log(f"[BATCH] 实时日志：{log_path}（进度 {PROGRESS_PATH} / {STATE_PATH}）")
        progress_body = (f"# BookLeme 进度（最新批次 {run_id}）\n\n"
                         f"- 计划总量：S0-S9 共 9 个 stage；输入源 {len(local_inputs) + len(urls)} 个\n"
                         f"- 日志绝对路径：{log_path}\n"
                         f"- LLM 配置指纹：{llm.config_fingerprint()}"
                         f"（{llm.settings().get('source') or '未配置'}）\n\n"
                         f"## Stage 记录\n")
        self._write_text(PROGRESS_PATH, progress_body)
        # 同时留一份本次 run 专属的进度文件：并发跑时 progress.md 会被互相覆盖
        self._write_text(LOG_DIR / self.milestone / f"progress-{run_id}.md", progress_body)

        rights = user_rights or self.config["user_rights"]
        model_fingerprint = f"deterministic-{__version__} (no LLM judge in this batch)"

        # ---------------- S0 Intake ----------------
        log("S0 Intake")
        fetched: list[dict] = []
        if urls:
            # 网址 = 公开来源（tier B）。抓下来落进 sources/public，S0 后面按公开源吃进去，
            # 不需要用户先跑一次 fetch 再记路径。
            from .fetch import fetch_url
            for u in urls:
                try:
                    rec = fetch_url(u)
                except Exception as exc:
                    # 抓取失败最常见的是代理/证书问题；给出能自己走的下一步，
                    # 而不是把 SSL 栈丢给用户
                    raise PipelineError(
                        f"抓取 {u} 失败：{type(exc).__name__}: {str(exc)[:160]}。"
                        f"可以先手动下载，再用 --input 指向本地文件。") from exc
                fetched.append(rec)
                log(f"    抓取 {u} → sources/public（公开来源，tier B）")
        # 书名不该默认成文件名：先看文档自带的标题，再退回清洗过的文件名，
        # 并在日志里说清取自哪里（用户才知道要不要用 --title 覆盖）。
        if title:
            book_title = title
        else:
            book_title, title_hint = infer_title(local_inputs, fetched)
            log(f"    书名「{book_title}」（{title_hint}）")
        sources: list[dict] = []
        for i, raw in enumerate(local_inputs, 1):
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
        input_shas = {s["sha256"] for s in sources}
        # 公开源默认**不再无脑并入**：以前只要 fetch 过一次，之后每次 run 都会把那些
        # 内容悄悄混进语料（表现为书名是你的，覆盖章节和图却是别人的）。
        # 现在只纳入两种：本次通过 URL 抓取的，或用户显式 --include-public。
        wanted_urls = {r.get("url") for r in fetched if r.get("url")}
        skipped_public = 0
        if public_dir.exists():
            for f in sorted(public_dir.glob("*.json")):
                data = load_json(f)
                if not include_public and data.get("url") not in wanted_urls:
                    skipped_public += 1
                    continue
                if data.get("file"):
                    # 文件型公开源先算 sha：与 --input 传入的同一文件去重，防重复计源
                    pfile = public_dir / data["file"]
                    if not pfile.is_file() or sha256_file(pfile) in input_shas:
                        continue
                sid = f"SRC-{len(sources) + 1:03d}"
                public_data[sid] = data
                if data.get("file"):
                    # fetch 存的文件型公开源（论文 PDF 等）：sidecar JSON 指向实体文件
                    pfile = public_dir / data["file"]
                    sources.append({
                        "source_id": sid, "origin": "public", "kind": pfile.suffix.lower(),
                        "path": str(pfile), "url": data.get("url", ""),
                        "sha256": sha256_file(pfile), "bytes": pfile.stat().st_size,
                        "mime": mimetypes.guess_type(pfile.name)[0] or "application/octet-stream",
                        "tier": data.get("tier", "B"), "license_note": data.get("license_note", ""),
                        "retrieved_at": data.get("retrieved_at", ""),
                        "extract_status": "pending", "figure_text_lost": False,
                    })
                else:
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
        if skipped_public:
            log(f"    sources/public 里还有 {skipped_public} 个公开源未纳入"
                f"（要一起编译请加 --include-public）")
        if not sources:
            raise PipelineError("没有可用输入源")

        book_sha256 = sha256_text("|".join(s["sha256"] for s in sources))
        cache = CACHE_DIR / book_sha256[:12]
        cache.mkdir(parents=True, exist_ok=True)
        # sources.json 是跨 run 共享 IR（内容须稳定）；provenance_manifest.json
        # 含 run_id / generated_at，必须按 run 隔离，否则不同 run 会串味。
        s0_paths = [cache / "sources.json", out_dir / "provenance_manifest.json"]
        # 哈希必须含内容指纹：只含路径的话，重新抓取同一 URL（内容变了、路径没变）
        # 不会让 S0 失效，旧 sources.json / figures.json 会被误当成新结果复用。
        s0_hash = stage_input_hash([DEFAULT_RUN_CONFIG, str(book_title), rights]
                                   + [f"{s['path']}#{s['sha256']}" for s in sources])
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
        log("S1 Extract（确定性 ETL + 图表提取）")
        s1_paths = [cache / "full_text.txt", cache / "char_map.json",
                    cache / "toc.json", cache / "extraction_report.json",
                    cache / "figures.json"]
        s1_hash = stage_input_hash([s0_paths[0], DEFAULT_RUN_CONFIG])
        if self.state.should_skip(run_id, "S1", s1_hash, s1_paths):
            log("S1 SKIP")
            full_text = s1_paths[0].read_text(encoding="utf-8")
            char_map = load_json(s1_paths[1])
            toc_loaded = load_json(s1_paths[2])
            # toc.json 落盘为 {"schema_version", "entries": [...]}，而
            # merge() 在内存里返回的是 list；两条路径必须统一，否则 S3 重算会炸。
            toc = toc_loaded.get("entries", []) if isinstance(toc_loaded, dict) else toc_loaded
            figures_obj = load_json(s1_paths[4])
        else:
            results = []
            report_rows = []
            fig_entries: list[dict] = []
            for src in sources:
                data = public_data.get(src["source_id"], {})
                if src["origin"] == "public" and not data.get("file"):
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
                # ---- 2.0 图表提取：PDF 栅格图+图注 / 网页下载图+figcaption ----
                if src["kind"] == ".pdf" or src["path"].lower().endswith(".pdf"):
                    for e in extract_pdf_figures(Path(src["path"])):
                        e["source_id"] = src["source_id"]
                        fig_entries.append(e)
                elif data.get("images"):
                    for e in html_figure_entries(data, public_dir):
                        e["source_id"] = src["source_id"]
                        fig_entries.append(e)
            full_text, char_map, toc = merge(results)
            self._write_text(s1_paths[0], full_text)
            self._write(s1_paths[1], {"schema_version": "1.0", "map": char_map,
                                      "strategy": "nfkc+strip-zero-width"}, log)
            self._write(s1_paths[2], {"schema_version": "1.0", "entries": toc}, log)
            self._write(s1_paths[3], {"schema_version": "1.0", "run_id": run_id,
                                      "sources": report_rows,
                                      "llm_calls": 0}, log)
            # 图注在全局归一化语料中定位（逐字可溯）；定位不到则 position=null，
            # 图仍交付但如实标注未锚定，绝不伪造位置。
            locate_captions(fig_entries, full_text)
            fig_dir = cache / "figures"
            figures_out = []
            for i, e in enumerate(fig_entries, 1):
                fid = f"FIG-{i:03d}"
                image_file = None
                if e.get("image"):
                    fig_dir.mkdir(parents=True, exist_ok=True)
                    p = fig_dir / f"{fid}.{e.get('ext') or 'bin'}"
                    p.write_bytes(e["image"])
                    image_file = str(p.relative_to(ROOT))
                figures_out.append({
                    "figure_id": fid, "source_id": e["source_id"], "page": e.get("page"),
                    "kind": e["kind"], "caption": e["caption"],
                    "char_start": e.get("char_start"), "char_end": e.get("char_end"),
                    "anchor_kind": e.get("anchor_kind"),
                    "pairing_uncertain": bool(e.get("pairing_uncertain")),
                    "unlabeled": bool(e.get("unlabeled")),
                    "image_file": image_file,
                })
            figures_obj = {"schema_version": "2.0", "book_sha256": book_sha256,
                           "figures": figures_out}
            self._write(s1_paths[4], figures_obj, log)
            degraded = [r for r in report_rows if r["status"] != "ok"]
            if degraded:
                self._write(out_dir / "degradation_log.json",
                            {"schema_version": "1.0", "degraded_sources": degraded}, log)
            self.state.mark(run_id, "S1", s1_hash, s1_paths,
                            degraded=bool(degraded),
                            note=f"{len(degraded)} 个源降级；figures={len(figures_out)}")
        figures = figures_obj.get("figures", [])
        log(f"    图表 {len(figures)} 个"
            f"（带图 {sum(1 for f in figures if f['image_file'])}，"
            f"仅图注 {sum(1 for f in figures if not f['image_file'])}）")

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
        # 体裁插件的额外必填字段由插件自己声明（capability_schema.genre_fields），
        # 抽取阶段就要知道它们 —— 故此处提前加载插件，并把插件源码纳入 S4 哈希。
        registry_s4, _ = load_plugins(extra_plugin_dir)
        genre_names = "、".join(
            f"{g}（{getattr(registry_s4.get(g), 'display_name_zh', '')}）"
            for g in router_result["genres"]) or "无"
        log(f"    体裁 {genre_names} → 引擎 {router_result['engines']} "
            f"({router_result['override_source']})")

        # ---------------- S4 Capabilities ----------------
        log("S4 Capabilities（本批为确定性抽取器，未接 LLM）")
        s4_paths = [cache / "capabilities.json"]
        capability_sources = sorted((Path(__file__).parent / "capabilities").glob("*.py"))
        llm_sources = sorted((Path(__file__).parent / "llm").rglob("*"))
        plugin_files_s4 = sorted(str(Path(getattr(p, "source_path", "")).resolve())
                                 for p in registry_s4.values())
        primary_genre = (router_result.get("genres") or ["knowledge_reference"])[0]
        genre_fields = {}
        for gid in ([primary_genre] + list(router_result.get("genres") or [])):
            plugin = registry_s4.get(gid)
            spec = getattr(plugin, "capability_schema", None) or {}
            gf = spec.get("genre_fields")
            if isinstance(gf, dict) and gf:
                genre_fields = gf
                break
        if genre_fields:
            log(f"    体裁额外必填字段：{'、'.join(genre_fields)}")
        # LLM 生效配置进指纹：配了模型不重算、换模型指纹不变，都是「指标被当成同一次实验」
        llm_fp = llm.config_fingerprint()
        s4_hash = stage_input_hash([s1_paths[0], s2_paths[0], s1_paths[4], DEFAULT_RUN_CONFIG,
                                    llm_fp]
                                   + capability_sources + llm_sources + plugin_files_s4)
        if self.state.should_skip(run_id, "S4", s4_hash, s4_paths):
            log("S4 SKIP")
            caps = load_json(s4_paths[0])
        else:
            # 抽取通道优先级：宿主承接 > 外部模型 > heuristic 模板句。
            # heuristic 只会填「按「X」判断情境」这种模板句 —— 没有知识，
            # 等于把「去读原文」的活推回给用户。所以只要有宿主承接的能力卡，
            # 就用它，不再退化到模板句。
            host_blocks = _load_host_blocks(cache, run_id)
            caps = extract_capabilities(full_text, segments["segments"], self.config,
                                        book_title=book_title, genre_fields=genre_fields,
                                        host_blocks=host_blocks)
            caps["book_sha256"] = book_sha256
            # genre_tags / engine_targets 是 per-run 的路由结果，不能写进共享
            # capabilities.json；保持为空数组，渲染阶段按本次 engines 过滤。
            # figure_refs：图注落在能力卡 char 区间内则挂接（2.0）。
            attach_figure_refs(caps, figures)
            # 3.0：读图 → 能力卡（视觉模型）。未配置视觉模型 → 不产出任何解读（图仍交付）。
            fig_cards = extract_figure_cards(figures, self.config, book_title=book_title,
                                             full_text=full_text,
                                             segments=segments["segments"],
                                             genre_fields=genre_fields)
            if fig_cards:
                caps["capabilities"].extend(fig_cards)
                # extractor 枚举只描述「正文卡的抽取方式」，图解读卡另计数量；
                # 改写 extractor 会破坏 schema 枚举（如 "heuristic+figure-insight"）。
                caps["figure_cards"] = len(fig_cards)
                log(f"    读图生成能力卡 {len(fig_cards)} 张（图示 → 要点，视觉模型）")
            # 每张卡记下**来源等级**（与 provenance 的 sources[].tier 同源），
            # 免得下游把「抽取方式等级」误当来源等级写进 claim ledger。
            # 必须在图解读卡并入之后再赋：否则新卡没有 source_tier，下游会退化成 C。
            tier_by_sid = {s["source_id"]: s.get("tier", "C") for s in sources}
            for cap in caps["capabilities"]:
                cap["source_tier"] = tier_by_sid.get(cap.get("source_id", ""), "C")
            self._write(s4_paths[0], caps, log)
            # 没走宿主承接时导出抽取工单：模板句卡没有知识，得让宿主来填。
            if not host_blocks and caps.get("extractor") == "heuristic":
                try:
                    from .judge.capability import build_worklist as build_cap_worklist
                    wl = build_cap_worklist(full_text, segments["segments"],
                                            book_title,
                                            genre_fields=genre_fields)
                    wl_path = out_dir / "capability_worklist.json"
                    self._write(wl_path, wl, log)
                    log(f"    能力卡抽取工单已导出：{wl_path}"
                        f"（{wl['item_count']} 个章节待提炼）")
                    log("    → 宿主 Agent 承接：逐节提炼成可执行规则，回填后重跑 "
                        "`bookleme run` 即生效")
                except Exception as exc:
                    log(f"    抽取工单导出失败：{type(exc).__name__}: {exc}")
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
        llm_sources_s5 = sorted((Path(__file__).parent / "llm").rglob("*"))
        s5_hash = stage_input_hash([s4_paths[0], s1_paths[0], DEFAULT_RUN_CONFIG,
                                    llm.config_fingerprint()]
                                   + fidelity_sources + llm_sources_s5)
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
            # judge（可选）：groundedness / V2 / V3 的真实判定。
            # 两条通道：
            # 1) 配置了外部模型 → 直接调（保持向后兼容）；
            # 2) 没配置 → **导出工单给宿主 Agent**。BookLeme 是 harness，
            #    宿主 Agent 本身就是大模型，让用户去配 API key 让它自己调
            #    外部模型，是把在场能做的事外包出去——多一道配置、多一把密钥。
            #    确定性那半（逐字回验/覆盖率/版权门）不受影响，照常产出。
            judge_result = None
            v1 = v1_cross_domain(caps_v, segments)
            jcfg = self.config.get("llm_judge") or {}
            if jcfg.get("enabled", True) and llm.available():
                judge_result = judge_capabilities(caps_v, full_text, self.config,
                                                  votes=int(jcfg.get("votes", 3)))
                log(f"    judge 已运行：judged={judge_result['summary']['judged']}"
                    f"（{judge_result['votes']} 票多数，fingerprint="
                    f"{judge_result['model_fingerprint']}）")
            else:
                # 导出工单：宿主 Agent 承接，无需用户配置任何东西
                try:
                    from .judge import build_worklist
                    worklist = build_worklist(caps_v, full_text, self.config,
                                              votes=int(jcfg.get("votes", 3)))
                    wl_path = out_dir / "judge_worklist.json"
                    self._write(wl_path, worklist, log)
                    log(f"    judge 工单已导出：{wl_path}"
                        f"（{worklist['item_count']} 条待判）")
                    log("    → 宿主 Agent 承接：读工单逐条判断，写 answers.json 后执行")
                    log(f"       `bookleme judge --run-id {run_id} --apply answers.json`")
                    log("    → 在那之前，groundedness/V2/V3 保持 null（不伪造）")
                except Exception as exc:
                    log(f"    judge 工单导出失败：{type(exc).__name__}: {exc}")
            ledger = build_claim_ledger(caps_v, book_sha256, str(cache / "slices"),
                                        judge=judge_result, v1=v1)
            fidelity = build_fidelity_report(caps_v, ledger, segments, quote_records,
                                             self.config, judge=judge_result)
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
        renderer_files = sorted((Path(__file__).parent / "render").glob("*.py"))
        s6_paths = [out_dir / "build_manifest.json"]
        s6_hash = stage_input_hash([s5_paths[0], s2_paths[0], s3_paths[0], s1_paths[4],
                                    DEFAULT_RUN_CONFIG]
                                   + plugin_files + renderer_files)
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
                display = f"{short_title(book_title)}·{plugin.display_name_zh}"
                description = build_description(plugin, book_title, self.config)
                ctx = {
                    "slug": slug, "display_name": display, "description": description,
                    "book_title": book_title, "author": author, "engine": eng,
                    "run_id": run_id, "config": self.config,
                    "verified_capabilities": verified_caps,
                    "segments": segments, "provenance_manifest": manifest,
                    "fidelity_report": fidelity, "router_result": router_result,
                    "figures": figures, "toc": toc,
                }
                files = plugin.render(ctx)
                target = out_dir / "build" / eng / f"{display}（{slug}）"
                for rel, content in files.items():
                    self._write_text(target / rel, content)
                # 2.0：全部图片资产入产物（图是交付物本体）；未挂接的图也保留
                asset_rels = []
                for fobj in figures:
                    fid = fobj["figure_id"]
                    if not fobj.get("image_file"):
                        continue
                    src_img = ROOT / fobj["image_file"]
                    rel = f"assets/figures/{fid}{src_img.suffix}"
                    dst = target / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(src_img.read_bytes())
                    asset_rels.append(rel)
                artifacts.append({
                    "engine": eng, "genre_id": plugin.genre_id, "plugin_reason": reason,
                    "slug": slug, "display_name": display, "description": description,
                    "skill_dir": str(target), "files": sorted(list(files) + asset_rels),
                    "figure_assets": asset_rels,
                })
                log(f"    {eng}: {target}（{len(files)} 个文件 + {len(asset_rels)} 张图）")
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
            # 图注进入引文集合：它们是逐字原文文本，必须计入引文比（诚实口径）
            quotes = [c["ria"]["R_quote"] for c in verified_caps] + [
                f["caption"] for f in figures
                if f.get("caption") and f.get("char_start") is not None
            ]
            per_artifact = []
            shingle_max = 0.0
            for art in artifacts:
                target = Path(art["skill_dir"])
                qv = validate_skill(target)
                official = self._official_validate(target)
                lint = lint_skill_dir(target, self.config["skill_body_max_lines"])
                gate = run_copyright_gate(target, full_text, quotes, self.config,
                                          figures=figures)
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
                # 报错要能直接读懂并知道下一步：哪道门、哪个值超了、怎么改
                problems = []
                for a in per_artifact:
                    for chk in a.get("copyright_gate", {}).get("checks", []):
                        if not chk.get("passed"):
                            problems.append(f"{a['engine']} · {chk['name']}：实测 {chk.get('value')} "
                                            f"超过上限 {chk.get('ceiling')}")
                    for e in a.get("quick_validate_errors", []) or []:
                        problems.append(f"{a['engine']} · 产物格式：{e}")
                    for e in a.get("lint_errors", []) or []:
                        problems.append(f"{a['engine']} · 版式：{e}")
                raise PipelineError(
                    "S7 硬门未过，产物不安装、不发布：\n  - "
                    + "\n  - ".join(problems[:8])
                    + f"\n  完整报告：{out_dir / 'validation_report.json'}")

        # distribution decision as a start-flag gate, never asked mid-run
        if public and confirm_public != "PUBLISH":
            raise PipelineError("公开分发必须在启动命令显式给 --public --confirm-public PUBLISH")
        # 2.0 图片分发政策：原文图片资产随衍生笔记公开 = 复制传播原图，非自有/公版禁止
        fig_with_images = sum(1 for f in figures if f.get("image_file"))
        block_reason = figure_distribution_block(rights, fig_with_images)
        if public and block_reason:
            raise PipelineError(block_reason)
        self._write(out_dir / "distribution_decision.json", {
            "schema_version": "2.0", "default": "private",
            "requested_public": public, "confirm_public": confirm_public or "",
            "user_rights": rights, "hard_gates_passed": validation["all_passed"],
            "figures_total": len(figures), "figures_embedded": fig_with_images,
            "note": "默认私有；含原文图片时非自有/公版禁止公开；本批不执行任何远端发布动作。",
        }, log)

        # ---------------- S8 Install (optional) ----------------
        install_receipts: list[dict] = []
        if install and not dry_run:
            log("S8 Install（写入技能真源）")
            preflight([
                {"category": (self.config["category_knowledge"] if art["engine"] == "knowledge_pack"
                              else self.config["category_behavior"]),
                 "display_name": art["display_name"], "slug": art["slug"],
                 "skill_dir": art["skill_dir"]}
                for art in artifacts
            ])
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
            install_receipts = receipts
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
                "book_title": book_title,
                "book_sha256": book_sha256,
                "llm_calls": llm.llm_calls,
                "model_fingerprint": (llm.model_fingerprint("capability_extract_v1")
                                      if caps_v["extractor"] == "llm" else None),
                "fidelity": fidelity["metrics"],
                "smoke": [], "router": router_result,
                "figures": {
                    "total": len(figures),
                    "with_images": sum(1 for f in figures if f.get("image_file")),
                    "caption_only": sum(1 for f in figures if not f.get("image_file")),
                    "anchored": sum(1 for f in figures if f.get("char_start") is not None),
                    "caps_with_figures": sum(1 for c in caps_v["capabilities"]
                                             if c.get("figure_refs")),
                },
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
            "installed": [r.get("target_abs", "") for r in install_receipts],
            "next": [
                f"看这次能不能用：python3 -m bookleme check {run_id}",
                f"看指标：python3 -m bookleme eval --run-id {run_id}",
                ("已装到技能目录，直接按 SKILL.md 的「触发场景」提问即可。"
                 if install_receipts else
                 "想装到技能目录：同一条命令加 --install（有缓存，重跑很快）"),
            ],
        }
        log(f"[BATCH] 完成：{len(artifacts)} 个产物，all_passed={validation['all_passed']}；"
            f"耗时 {time.monotonic() - t_start:.1f}s；"
            f"日志 {log_path}")
        log(f"[BATCH] 下一步：{summary['next'][0]}")
        if not install_receipts:
            log(f"[BATCH] {summary['next'][2]}")
        return summary
