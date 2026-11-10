"""BookLeme regression tests. Standard-library unittest only (zero dependencies)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bookleme import __version__
from bookleme.capabilities.ria import validate_ria
from bookleme.config import ROOT, SCHEMA_DIR, STATE_PATH, load_json, load_router_config, load_run_config
from bookleme.fidelity.overlap import shingle_jaccard, total_quote_ratio
from bookleme.fidelity.quotes import verify_quotes
from bookleme.hashing import sha256_text, stage_input_hash
from bookleme.plugins import load_plugins, validate_plugin
from bookleme.render import build_description
from bookleme.router import compute_features, normalize_features
from bookleme.schema_check import validate as schema_validate
from bookleme.state import StateStore
from bookleme.validate import lint_skill_dir, run_copyright_gate, validate_skill, validate_text

SYNTHETIC = ROOT / "evals/cases/synthetic/coach_book.md"


class TestBasics(unittest.TestCase):
    def test_version_and_configs(self):
        self.assertEqual(__version__, "0.1.0")
        cfg = load_run_config()
        self.assertEqual(cfg["max_quote_chars"], 150)
        self.assertIn("weights", load_router_config())

    def test_all_schemas_loadable_and_state_valid(self):
        for f in sorted(SCHEMA_DIR.glob("*.schema.json")):
            with self.subTest(schema=f.name):
                self.assertIsInstance(load_json(f), dict)
        if STATE_PATH.exists():
            errors = schema_validate(load_json(STATE_PATH),
                                     load_json(SCHEMA_DIR / "state.schema.json"))
            self.assertEqual(errors, [], f"state.json 不合 schema: {errors}")

    def test_normalize_is_scoped_not_whole_text_nfkc(self):
        # 上游 sanitize.py:168-171 明确禁止整篇 NFKC；普通文本必须逐字节保留，
        # 只有康熙部首 U+2F00-2FDF 折叠为对应表意字。
        from bookleme.extract.base import normalize
        raw = "ＡＢＣ１２３ ① ﬃ ㍿ 判断⼒\u200b"
        text, cmap = normalize(raw)
        for fragment in ("ＡＢＣ１２３", "①", "ﬃ", "㍿"):
            self.assertIn(fragment, text, f"合法文本被改写：{fragment!r}")
        self.assertIn("判断力", text, "康熙部首未被折叠")
        self.assertNotIn("\u200b", text)
        self.assertEqual(len(text), len(cmap))
        self.assertEqual(text, normalize(raw)[0], "归一必须确定性可复现")

    def test_hashing_is_deterministic(self):
        a = stage_input_hash([SYNTHETIC, "x", {"b": 2, "a": 1}])
        b = stage_input_hash([SYNTHETIC, "x", {"a": 1, "b": 2}])
        self.assertEqual(a, b)
        self.assertEqual(sha256_text("abc"), sha256_text("abc"))

    def test_state_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.json")
            store.ensure_run("r1", "sha", "fp")
            out = Path(tmp) / "out.json"
            out.write_text("{}", encoding="utf-8")
            h = "hash-1"
            self.assertFalse(store.should_skip("r1", "S5", h, [out]))
            store.mark("r1", "S5", h, [out])
            self.assertTrue(store.should_skip("r1", "S5", h, [out]))
            self.assertFalse(store.should_skip("r1", "S5", "hash-2", [out]))
            out.unlink()
            self.assertFalse(store.should_skip("r1", "S5", h, [out]))


class TestRouter(unittest.TestCase):
    def test_features_deterministic_and_normalised(self):
        text = SYNTHETIC.read_text(encoding="utf-8")
        segments = [{"segment_id": "seg-001", "heading": "第一章", "level": 1,
                     "char_range": [0, len(text)]}]
        f1 = compute_features(text, segments, [])
        f2 = compute_features(text, segments, [])
        self.assertEqual(f1, f2)
        self.assertEqual(set(f1), set(load_router_config()["features"]))
        norm = normalize_features(f1, load_router_config())
        self.assertTrue(all(0.0 <= v <= 1.0 for v in norm.values()))


class TestPlugins(unittest.TestCase):
    def test_builtin_plugins_validate(self):
        registry, diagnostics = load_plugins()
        self.assertGreaterEqual(len(registry), 2)
        for gid, plugin in registry.items():
            with self.subTest(plugin=gid):
                self.assertEqual(validate_plugin(plugin, plugin.source_path), [])
        self.assertTrue(all(d["status"] == "loaded" for d in diagnostics))

    def test_description_has_3_to_5_chinese_triggers(self):
        registry, _ = load_plugins()
        cfg = load_run_config()
        for gid, plugin in registry.items():
            with self.subTest(plugin=gid):
                desc = build_description(plugin, "测试之书", cfg)
                hits = sum(1 for w in plugin.trigger_words if w in desc)
                self.assertTrue(3 <= hits <= 5)
                self.assertLessEqual(len(desc), 1024)
                self.assertNotIn("<", desc)
                self.assertNotIn(">", desc)


class TestRealBookFixes(unittest.TestCase):
    """真实书稿（《斯坦福大学人生设计课》PDF）暴露的缺陷回归测试。"""

    def test_toc_duplicate_headings_collapse_to_body(self):
        # 目录行「第1章 …」与正文标题重名，不得制造短假段；正文出现应胜出。
        from bookleme.segment.headings import segment_text
        toc_row = "第1章 分析测评你目前的生活\n第2章 创建人生的指南针\n"
        body = ("第1章 分析测评你目前的生活\n" + "这是第一章的正文内容。" * 150 + "\n"
                "第2章 创建人生的指南针\n" + "这是第二章的正文内容。" * 150 + "\n")
        full = "目录\n" + toc_row + "献词\n推荐序\n" + body
        segs = segment_text(full, [], load_run_config())["segments"]
        self.assertEqual(len(segs), 2, f"目录行未被合并：{[s['heading'] for s in segs]}")
        for s in segs:
            self.assertGreater(s["char_range"][1] - s["char_range"][0], 1000)
        # 全文无失覆盖：段区间连续铺满
        self.assertEqual(segs[0]["char_range"][0], 0)
        self.assertEqual(segs[-1]["char_range"][1], len(full))
        for a, b in zip(segs, segs[1:]):
            self.assertEqual(a["char_range"][1], b["char_range"][0])

    def test_heuristic_quote_is_verbatim_substring(self):
        # 引文必须是原文逐字子串（不得折叠空白），否则 S5 find() 失败、char_start=-1。
        from bookleme.capabilities.extract import extract_capabilities
        from bookleme.segment.headings import segment_text
        body = ("第1章 分析测评你目前的生活\n在斯坦福大学的设计工作室有这样一个标牌，"
                "上面写着一句话。\n" + "后续正文。" * 80 + "\n")
        segs = segment_text(body, [], load_run_config())["segments"]
        caps = extract_capabilities(body, segs, load_run_config())
        self.assertEqual(caps["extractor"], "heuristic")
        self.assertGreaterEqual(len(caps["capabilities"]), 1)
        for cap in caps["capabilities"]:
            quote = cap["ria"]["R_quote"]
            self.assertIn(quote, body, f"引文非逐字子串：{quote!r}")
            self.assertLessEqual(len(quote), 24, "引文超版权预算（含从句边界窗口）")
        # 引文定位必须可解析
        pos = body.find(caps["capabilities"][0]["ria"]["R_quote"])
        self.assertGreaterEqual(pos, 0)
        self.assertEqual(caps["capabilities"][0]["span"]["char_start"], pos)

    def test_heuristic_quote_not_from_toc_row(self):
        # 合并段前置目录区，引文不得来自目录行，必须来自真实正文首句。
        from bookleme.capabilities.extract import _first_sentence_quote, _heading_content_start
        body = ("第1章 分析测评你目前的生活\n第2章 创建人生的指南针\n"
                "第1章 分析测评你目前的生活\n真正正文的第一句话在这里。后面还有很多。")
        start = _heading_content_start(body, "第1章 分析测评你目前的生活")
        quote = _first_sentence_quote(body[start:], 24)
        self.assertEqual(quote, "真正正文的第一句话在这里。")


class TestLLMExtractor(unittest.TestCase):
    """LLM 抽取器：引文终身逐字、单卡失败不中断、不可用时回退 heuristic。"""

    def _fake_llm(self, answers):
        import bookleme.llm as llm_mod
        calls = {"n": 0}

        def fake_chat_json(user, system="", **kw):
            i = calls["n"]
            calls["n"] += 1
            a = answers[i] if i < len(answers) else answers[-1]
            if isinstance(a, Exception):
                raise a
            return a

        return llm_mod, fake_chat_json, calls

    def test_llm_quote_is_located_verbatim_back_to_source(self):
        from bookleme.capabilities.extract import extract_capabilities, _locate_quote_verbatim
        from bookleme.segment.headings import segment_text
        text = ("第1章 分析测评你目前的生活\n"
                "在斯坦福大学的设计工作室有这样一个标牌，上面写着一句话。\n" + "后续正文。" * 100 + "\n"
                "第2章 创建人生的指南针\n本章正文从这里开始，讲的是指南针。" + "继续。" * 100)
        segs = segment_text(text, [], load_run_config())["segments"]
        self.assertEqual(len(segs), 2)
        llm_mod, fake, calls = self._fake_llm([{
            "title": "你在这里仪表盘",
            "R_quote": "在斯坦福大学的设计工作室有这样一个标牌",  # 模型给的引文（逐字）
            "I_rephrase": "先量化现状再谈设计，四个维度各打分。",
            "A1_author_case": "书中以设计室标牌引出定位问题。",
            "A2_user_trigger": "当用户说『我很迷茫』『不知道现状』时",
            "A3_steps": ["给四个维度打分", "找出红灯项", "确认真问题"],
            "B_not_applicable": "不适用：需要专业诊断时。",
        }])
        orig = llm_mod.chat_json
        orig_avail = llm_mod.available
        llm_mod.chat_json, llm_mod.available = fake, lambda: True
        try:
            caps = extract_capabilities(text, segs, load_run_config(), book_title="测试书")
        finally:
            llm_mod.chat_json, llm_mod.available = orig, orig_avail
        self.assertEqual(caps["extractor"], "llm")
        self.assertEqual(calls["n"], len(segs))
        cap = caps["capabilities"][0]
        self.assertIn(cap["ria"]["R_quote"], text, "LLM 引文必须逐字可回溯")
        self.assertEqual(cap["confidence"]["tier"], "B")
        self.assertEqual(cap["span"]["char_start"],
                         text.find(cap["ria"]["R_quote"]))

    def test_llm_whitespace_variant_quote_collapses_to_source_slice(self):
        # 模型把原文换行写成空格时，必须切回原文子串而不是模型的空白版本。
        from bookleme.capabilities.extract import _locate_quote_verbatim
        text = "前文。\n在斯坦福大学的设计工作室\n有这样一个标牌。\n后文。"
        quote, pos = _locate_quote_verbatim(text, "在斯坦福大学的设计工作室 有这样一个标牌")
        self.assertEqual(quote, "在斯坦福大学的设计工作室\n有这样一个标牌")
        self.assertEqual(pos, text.find("在斯坦福大学的设计工作室\n"))

    def test_llm_failure_falls_back_to_heuristic(self):
        from bookleme.capabilities.extract import extract_capabilities
        from bookleme.segment.headings import segment_text
        text = ("第1章 甲\n甲章第一句在这里。" + "后面内容。" * 100 + "\n"
                "第2章 乙\n乙章第一句在这里。" + "后面内容。" * 100)
        segs = segment_text(text, [], load_run_config())["segments"]
        llm_mod, fake, calls = self._fake_llm([llm_mod_error()])
        orig = llm_mod.chat_json
        orig_avail = llm_mod.available
        llm_mod.chat_json, llm_mod.available = fake, lambda: True
        try:
            caps = extract_capabilities(text, segs, load_run_config(), book_title="测试书")
        finally:
            llm_mod.chat_json, llm_mod.available = orig, orig_avail
        self.assertEqual(caps["extractor"], "heuristic")
        self.assertGreaterEqual(len(caps["capabilities"]), 1)
        for cap in caps["capabilities"]:
            self.assertIn(cap["ria"]["R_quote"], text)

    def test_llm_unavailable_uses_heuristic_without_calls(self):
        from bookleme.capabilities.extract import extract_capabilities
        from bookleme.segment.headings import segment_text
        text = "第1章 甲\n甲章第一句在这里。" + "后面内容。" * 100
        # 单标题会走窗口兜底，这里给两个标题走 headings 路径
        text += "\n第2章 乙\n乙章第一句在这里。" + "后面内容。" * 100
        segs = segment_text(text, [], load_run_config())["segments"]
        import bookleme.llm as llm_mod
        orig_avail = llm_mod.available
        llm_mod.available = lambda: False
        try:
            caps = extract_capabilities(text, segs, load_run_config(), book_title="测试书")
        finally:
            llm_mod.available = orig_avail
        self.assertEqual(caps["extractor"], "heuristic")


def llm_mod_error():
    import bookleme.llm as llm_mod
    return llm_mod.LLMError("模拟调用失败")


class TestFidelity(unittest.TestCase):
    def test_quote_verification_and_ria(self):
        cfg = load_run_config()
        full = "原文句子一。原文句子二。" + "其他内容" * 50
        caps = {"schema_version": "1.0", "book_sha256": "", "extractor": "deterministic-markup",
                "capabilities": [{
                    "capability_id": "CAP-0001", "title": "T", "source_id": "SRC-001",
                    "span": {"segment_id": "seg-001", "char_start": -1, "char_end": -1},
                    "ria": {"R_quote": "原文句子一", "I_rephrase": "先确认前提再行动",
                            "A1_author_case": "书中案例", "A2_user_trigger": "当用户卡住时",
                            "A3_steps": ["一步", "二步"], "B_not_applicable": "不适用情形"},
                    "claims": ["CLM-0001"], "checks": {}, "confidence": {"tier": "S"},
                    "status": "draft"}]}
        verified, records = verify_quotes(caps, full, [], cfg)
        self.assertTrue(records[0]["quote_verified"])
        self.assertEqual(verified["capabilities"][0]["status"], "verified")
        self.assertEqual(validate_ria(caps["capabilities"][0]["ria"], cfg), [])

    def test_copyright_gate_blocks_a_verbatim_dump(self):
        cfg = load_run_config()
        full = "这是一段用于测试的原文内容，重复出现以避免统计偶然性。" * 40
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "skill"
            (d / "references").mkdir(parents=True)
            (d / "SKILL.md").write_text("---\nname: x\n---\n\n少量说明\n", encoding="utf-8")
            (d / "references" / "body.md").write_text(full[:600], encoding="utf-8")
            gate = run_copyright_gate(d, full, [full[:600]], cfg)
            self.assertFalse(gate["passed"])
            names = {c["name"] for c in gate["checks"] if not c["passed"]}
            self.assertTrue({"single_quote_char_limit", "total_quote_ratio",
                             "max_contiguous_copy_chars", "shingle_overlap_max"} & names)

    def test_shingle_and_ratio_helpers(self):
        self.assertAlmostEqual(shingle_jaccard("abcdefg", "abcdefg", 3), 1.0)
        self.assertGreater(total_quote_ratio(["abc"], "abc"), 0)


class TestValidation(unittest.TestCase):
    def test_quick_validate_rules(self):
        good = "---\nname: demo-skill\ndescription: 当用户迷茫时使用\n---\n\n## 核心定位\n\nx\n"
        self.assertEqual(validate_text(good), [])
        self.assertTrue(any("Unexpected key" in e for e in validate_text(
            "---\nname: demo\nversion: 5.1\ndescription: x\n---\n")))
        self.assertTrue(any("hyphen-case" in e for e in validate_text(
            "---\nname: Bad_Name\ndescription: x\n---\n")))
        self.assertTrue(any("TODO" in e for e in validate_text(
            "---\nname: demo\ndescription: [TODO: fill]\n---\n")))

    def test_generated_artifacts_pass_all_gates(self):
        builds = sorted((ROOT / "out").glob("*/build/*/*"))
        if not builds:
            self.skipTest("尚未生成产物，请先运行一次 bookleme run")
        for d in builds[-2:]:
            with self.subTest(artifact=d.name):
                self.assertEqual(validate_skill(d), [])
                self.assertEqual(lint_skill_dir(d), [])


class TestEndToEnd(unittest.TestCase):
    def test_router_result_is_per_run(self):
        """--engine/--genre 是 per-run 参数，不得被另一 run 的路由结果串味。"""
        from bookleme.pipeline import Pipeline
        cfg = load_run_config()
        pipe = Pipeline(cfg, load_router_config())
        dual = pipe.run([str(SYNTHETIC)], run_id="unittest-router-dual",
                        title="人生设计练习册（合成）")
        single = pipe.run([str(SYNTHETIC)], run_id="unittest-router-single",
                          title="人生设计练习册（合成）",
                          genre="coach_dialogue", engine="behavior_skill")
        self.assertEqual(len(dual["artifacts"]), 2)
        self.assertEqual(len(single["artifacts"]), 1)
        rd = load_json(Path(dual["out_dir"]) / "router_result.json")
        rs = load_json(Path(single["out_dir"]) / "router_result.json")
        self.assertEqual(rd["engines"], ["knowledge_pack", "behavior_skill"])
        self.assertEqual(rs["engines"], ["behavior_skill"])
        self.assertEqual(rs["override_source"], "cli")

    def test_shared_ir_is_run_independent(self):
        """不同 run_id 不得污染共享 IR，也不得让 provenance 追溯串味。

        注意 state.json 的阶段记录是 per-run 的：新 run_id 会重走各 stage，
        这属于设计行为。本测试验证的是共享 IR 内容稳定 + manifest 按 run 隔离，
        以及同一 run_id 重跑时 S1 能幂等跳过。
        """
        from bookleme.pipeline import Pipeline
        cfg = load_run_config()
        pipe = Pipeline(cfg, load_router_config())
        a = pipe.run([str(SYNTHETIC)], run_id="unittest-shared-a", title="人生设计练习册（合成）")
        sources_a = (Path(a["cache_dir"]) / "sources.json").read_text(encoding="utf-8")
        b = pipe.run([str(SYNTHETIC)], run_id="unittest-shared-b", title="人生设计练习册（合成）")
        sources_b = (Path(b["cache_dir"]) / "sources.json").read_text(encoding="utf-8")

        self.assertTrue(a["validation_all_passed"])
        self.assertTrue(b["validation_all_passed"])
        self.assertEqual(sources_a, sources_b, "共享 IR 被 run 专属字段/当前时间污染")
        self.assertTrue(load_json(Path(a["cache_dir"]) / "sources.json")["run_id"].startswith("shared-"))
        ma = load_json(Path(a["out_dir"]) / "provenance_manifest.json")
        mb = load_json(Path(b["out_dir"]) / "provenance_manifest.json")
        self.assertEqual(ma["run_id"], "unittest-shared-a")
        self.assertEqual(mb["run_id"], "unittest-shared-b")

        c = pipe.run([str(SYNTHETIC)], run_id="unittest-shared-b", title="人生设计练习册（合成）")
        self.assertIn("S1 SKIP", Path(c["log"]).read_text(encoding="utf-8"),
                      "同一 run_id 重跑时 S1 应因 input_sha256 未变而跳过")

    def test_pipeline_produces_two_valid_artifacts(self):
        from bookleme.pipeline import Pipeline
        cfg = load_run_config()
        pipe = Pipeline(cfg, load_router_config())
        summary = pipe.run([str(SYNTHETIC)], run_id="unittest-run",
                           title="人生设计练习册（合成）")
        self.assertTrue(summary["validation_all_passed"])
        self.assertEqual(len(summary["artifacts"]), 2)
        metrics = load_json(Path(summary["metrics_path"]))
        self.assertEqual(metrics["fidelity"]["negative_refusal_rate"]["value"], 1.0)
        self.assertEqual(metrics["llm_calls"] if "llm_calls" in metrics else 0, 0)
        for s in metrics["smoke"]:
            self.assertTrue(all(c["passed"] for c in s["cases"].values()))


class TestRuntimeStateContract(unittest.TestCase):
    """P0 回归：可中断续聊链路（写+读+运行期路径）与输出格式单一 schema。"""

    def _run_synthetic(self, run_id):
        from bookleme.pipeline import Pipeline
        cfg = load_run_config()
        pipe = Pipeline(cfg, load_router_config())
        summary = pipe.run([str(SYNTHETIC)], run_id=run_id, title="人生设计练习册（合成）")
        self.assertTrue(summary["validation_all_passed"])
        return summary

    def test_behavior_skill_wires_state_write_read_chain(self):
        summary = self._run_synthetic("unittest-state-contract")
        bs = [Path(a) for a in summary["artifacts"] if "bs" in Path(a).name][0]
        skill_md = (bs / "SKILL.md").read_text(encoding="utf-8")
        state_guide = (bs / "references/state-guide.md").read_text(encoding="utf-8")
        state_io = (bs / "scripts/state_io.py").read_text(encoding="utf-8")

        # 写入义务必须出现在工作流与 Gotchas（此前只写"恢复时读"，写入无人指示）
        self.assertIn("写入 state.json", skill_md, "工作流必须指示每轮写 state")
        self.assertIn("每轮问答结束把 current_state / asked_questions / answers 写入 state.json", skill_md)
        self.assertIn("恢复会话时先读取 state.json", skill_md)

        # 运行期路径必须可解析：不得再出现构建仓库相对路径 out/sessions
        self.assertNotIn("out/sessions", state_guide, "state-guide 不得给出构建期相对路径")
        self.assertIn("BOOKLEME_STATE_DIR", state_guide)
        self.assertIn("current_state 取值", state_guide)
        self.assertIn("opening / ask_q", state_guide, "状态机取值应渲染进 state-guide")

        # state_io.py 必须内置默认 state_dir，调用方可以不传
        self.assertIn("def default_state_dir()", state_io)
        self.assertIn("state_dir=None", state_io)

    def test_state_io_round_trip_and_default_dir(self):
        import os
        import types
        from bookleme.render.skill import _STATE_IO

        mod = types.ModuleType("state_io_under_test")
        exec(_STATE_IO, mod.__dict__)

        saved = os.environ.get("BOOKLEME_STATE_DIR")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["BOOKLEME_STATE_DIR"] = tmp
                self.assertEqual(mod.default_state_dir(), tmp)
                st = mod.load("slug-x", "sess-1")
                self.assertEqual(st["current_state"], "opening")
                self.assertEqual(st["asked_questions"], [])
                st["current_state"] = "ask_q"
                st["asked_questions"].append("Q1")
                mod.save(st, "slug-x", "sess-1")
                back = mod.load("slug-x", "sess-1")
                self.assertEqual(back["current_state"], "ask_q")
                self.assertEqual(back["asked_questions"], ["Q1"])
            # env 未设置时回落到 ~/.bookleme/sessions（只验路径，不落盘）
            os.environ.pop("BOOKLEME_STATE_DIR", None)
            self.assertTrue(mod.default_state_dir().endswith(str(
                Path.home() / ".bookleme" / "sessions")))
        finally:
            if saved is not None:
                os.environ["BOOKLEME_STATE_DIR"] = saved

    def test_output_example_is_single_schema_and_covers_sections(self):
        from bookleme.plugins import load_plugins
        summary = self._run_synthetic("unittest-state-contract")
        bs = [Path(a) for a in summary["artifacts"] if "bs" in Path(a).name][0]
        skill_md = (bs / "SKILL.md").read_text(encoding="utf-8")

        registry, _ = load_plugins()
        coach = registry["coach_dialogue"]
        contract = coach.output_contract
        # 正文层：契约的每个必备板块都要出现在输出格式与示例结构里
        for s in contract["sections"]:
            self.assertIn(f"### {s}", skill_md, f"示例结构缺少板块：{s}")
        # 溯源层：元信息附录独立成层，与正文不再互相矛盾
        self.assertIn("## 元信息附录", skill_md)
        self.assertIn("两层都要交付", skill_md)
        # 老的矛盾写法（示例只有元信息条目、无正文板块）已消除
        self.assertNotIn("示例结构：\n\n```\n## ", skill_md)


class TestOutputContractRendering(unittest.TestCase):
    """P1 回归：required_fields/交付约定渲染、blueprint-template 引用、session-map 落盘。"""

    @classmethod
    def setUpClass(cls):
        from bookleme.pipeline import Pipeline
        cfg = load_run_config()
        pipe = Pipeline(cfg, load_router_config())
        cls.summary = pipe.run([str(SYNTHETIC)], run_id="unittest-contract-p1",
                               title="人生设计练习册（合成）")

    def _artifact(self, short):
        return [Path(a) for a in self.summary["artifacts"] if short in Path(a).name][0]

    def test_required_fields_and_delivery_convention_rendered(self):
        bs_md = (self._artifact("bs") / "SKILL.md").read_text(encoding="utf-8")
        kp_md = (self._artifact("kp") / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("必备字段（缺一不可）：当前状态打分 / 重新定义后的真问题 / 三个平等 A 计划 / 证伪/放弃条件 / 最小原型。",
                      bs_md, "required_fields 必须渲染进 SKILL.md")
        self.assertIn("交付约定：以 Markdown 文件落盘（模板名 `blueprint.md`", bs_md)
        self.assertIn("必备字段（缺一不可）：框架名 / 出处 / 可执行步骤 / 边界。", kp_md)
        self.assertIn("模板名 `answer.md`", kp_md)

    def test_blueprint_template_referenced_and_has_checklist(self):
        bs = self._artifact("bs")
        skill_md = (bs / "SKILL.md").read_text(encoding="utf-8")
        tpl = (bs / "assets/blueprint-template.md").read_text(encoding="utf-8")
        self.assertIn("assets/blueprint-template.md", skill_md, "SKILL.md 必须引用蓝图模板（孤儿资产修复）")
        self.assertIn("## 必备字段核对", tpl)
        self.assertIn("- [ ] 证伪/放弃条件", tpl)
        self.assertIn("- [ ] 最小原型", tpl)

    def test_session_map_generated_and_linked(self):
        bs = self._artifact("bs")
        skill_md = (bs / "SKILL.md").read_text(encoding="utf-8")
        sm = (bs / "references/session-map.md").read_text(encoding="utf-8")
        self.assertIn("references/session-map.md", skill_md, "Step 2 必须挂 session-map")
        self.assertIn("默认阶段序", sm)
        self.assertIn("① 真问题甄别", sm)
        self.assertIn("6-9", sm)

    def test_s6_cache_hash_covers_renderer_sources(self):
        """结构锁：S6 缓存哈希必须纳入渲染器源码，改渲染器即失效（防陈旧产物）。"""
        src = (ROOT / "bookleme/pipeline.py").read_text(encoding="utf-8")
        self.assertIn("+ plugin_files + renderer_files", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
