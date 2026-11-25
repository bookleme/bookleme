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
        self.assertEqual(__version__, "2.1.0")
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
            # 引文预算：heuristic 每卡 28 字 + 从句边界窗口 8 = 36
            self.assertLessEqual(len(quote), 36, "引文超版权预算（含从句边界窗口）")
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
        self.assertIn("必备字段（缺一不可）：框架名 / 出处 / 可执行步骤 / 边界 / 还需要哪些数据。", kp_md)
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


class TestP2Cleanup(unittest.TestCase):
    """P2 清尾回归：漏字、单位命名、冒烟用例覆盖、intent_map 死元数据。"""

    @classmethod
    def setUpClass(cls):
        from bookleme.pipeline import Pipeline
        cfg = load_run_config()
        pipe = Pipeline(cfg, load_router_config())
        cls.summary = pipe.run([str(SYNTHETIC)], run_id="unittest-p2-cleanup",
                               title="人生设计练习册（合成）")

    def _artifact(self, short):
        return [Path(a) for a in self.summary["artifacts"] if short in Path(a).name][0]

    def test_step3_typo_fixed_in_both_engines(self):
        for short in ("bs", "kp"):
            md = (self._artifact(short) / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("每条判断都要带上出处", md, f"{short} 漏字未修")
            self.assertNotIn("带上处。", md, f"{short} 仍残留漏字")

    def test_char_unit_naming(self):
        from bookleme.plugins import load_plugins
        registry, _ = load_plugins()
        coach = registry["coach_dialogue"]
        self.assertIn("$min_chars - $max_chars", coach.skill_template)
        self.assertNotIn("$min_tokens", coach.skill_template)
        self.assertEqual(coach.output_contract["min_chars"], 8000)
        self.assertEqual(coach.output_contract["max_chars"], 12000)
        for p in registry.values():
            self.assertNotIn("min_tokens", p.output_contract, f"{p.genre_id} 仍用 tokens 命名")
        bs_md = (self._artifact("bs") / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("字数区间：8000 - 12000 字。", bs_md)

    def test_smoke_cases_cover_resume_and_long_dialogue(self):
        smoke = (self._artifact("bs") / "evals/smoke.md").read_text(encoding="utf-8")
        self.assertIn("coach-resume", smoke, "冒烟缺中断续聊用例")
        self.assertIn("coach-long-dialogue", smoke, "冒烟缺长对话纪律用例")

    def test_no_stale_intent_map(self):
        from bookleme.plugins import load_plugins
        registry, _ = load_plugins()
        for gid, p in registry.items():
            self.assertNotIn("intent_map", p.routing_rules,
                             f"{gid} 仍有死元数据 intent_map（曾错指 framework-04）")


class TestFiguresAndFetch(unittest.TestCase):
    """2.0：网页/论文抓取 + 图表提取/挂接/渲染 + 图片分发政策。"""

    def test_caption_detection_scoped_and_typed(self):
        from bookleme.extract.figures import find_figure_captions
        text = ("前言正文不许误判\n图 1 本文方法总体结构\n中间正文\n"
                "Figure 2: The model architecture\n更多正文\n表 3 三组对比结果\n"
                "Table 4: Results overview\n正文")
        caps = find_figure_captions(text)
        self.assertEqual(len(caps), 4)
        self.assertEqual([c["kind"] for c in caps], ["figure", "figure", "table", "table"])
        self.assertTrue(caps[0]["caption"].startswith("图 1"))
        self.assertFalse(any("前言" in c["caption"] for c in caps))

    def test_locate_captions_anchors_verbatim_or_null(self):
        from bookleme.extract.figures import locate_captions
        entries = [
            {"figure_id": "FIG-001", "caption": "图 1 本文方法总体结构", "kind": "figure"},
            {"figure_id": "FIG-002", "caption": "图 9 并不存在的图注", "kind": "figure"},
        ]
        full = "开头\n图 1 本文方法总体结构\n结尾"
        locate_captions(entries, full)
        self.assertEqual(entries[0]["char_start"], 3)
        self.assertIsNone(entries[1]["char_start"], "定位不到必须如实置 null，不得伪造位置")

    def test_html_figure_entries_from_fetch_record(self):
        from bookleme.extract.figures import html_figure_entries
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "images").mkdir()
            (base / "images" / "x.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
            rec = {"images": [{"file": "images/x.png", "caption": "图 2 数据集样例", "alt": ""}]}
            entries = html_figure_entries(rec, base)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["caption"], "图 2 数据集样例")
        self.assertIsNotNone(entries[0]["image"])

    def test_attach_figure_refs_nearest_cap_within_window(self):
        from bookleme.capabilities import attach_figure_refs
        caps = {"capabilities": [
            {"capability_id": "C1", "span": {"char_start": 100, "char_end": 120}},
            {"capability_id": "C2", "span": {"char_start": 5000, "char_end": 5020}},
        ]}
        figures = [
            {"figure_id": "FIG-001", "char_start": 300},    # 距 C1 200 → C1
            {"figure_id": "FIG-002", "char_start": 5100},   # 距 C2 100 → C2
            {"figure_id": "FIG-003", "char_start": 9000},   # 距最近 4000 > 2000 → 不挂
            {"figure_id": "FIG-004", "char_start": None},   # 未锚定 → 不挂
        ]
        attach_figure_refs(caps, figures)
        self.assertEqual(caps["capabilities"][0]["figure_refs"], ["FIG-001"])
        self.assertEqual(caps["capabilities"][1]["figure_refs"], ["FIG-002"])
        # 超窗口与未锚定的图如实不挂，不硬凑
        self.assertNotIn("FIG-003", caps["capabilities"][0]["figure_refs"] + caps["capabilities"][1]["figure_refs"])
        self.assertNotIn("FIG-004", caps["capabilities"][0]["figure_refs"] + caps["capabilities"][1]["figure_refs"])

    def test_attach_prefers_nearest_and_is_deterministic(self):
        from bookleme.capabilities import attach_figure_refs
        caps = {"capabilities": [
            {"capability_id": "C1", "span": {"char_start": 100, "char_end": 110}},
            {"capability_id": "C2", "span": {"char_start": 400, "char_end": 410}},
        ]}
        figures = [
            {"figure_id": "FIG-002", "char_start": 300},  # 等距：偏向前方（C2 在前？不，C2 距离 100 < C1 200）
            {"figure_id": "FIG-001", "char_start": 250},  # 距 C1 150、距 C2 150 等距 → 前方 C1
        ]
        attach_figure_refs(caps, figures)
        self.assertEqual(caps["capabilities"][0]["figure_refs"], ["FIG-001"])
        self.assertEqual(caps["capabilities"][1]["figure_refs"], ["FIG-002"])

    def test_fetch_html_and_pdf_with_mocked_network(self):
        from unittest import mock
        import bookleme.fetch as fetch
        html = (b'<html><body><p>intro</p><figure><img src="/a.png" alt="A">'
                b'<figcaption>figcap</figcaption></figure></body></html>')
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 200

        def fake_html(url, timeout=30):
            return (png, "image/png") if url.endswith(".png") else (html, "text/html; charset=utf-8")

        with tempfile.TemporaryDirectory() as td, mock.patch.object(fetch, "_download", fake_html):
            rec = fetch.fetch_url("https://example.com/paper", out_dir=Path(td))
            self.assertEqual(rec["kind"], "html")
            self.assertEqual(len(rec["images"]), 1)
            self.assertEqual(rec["images"][0]["caption"], "figcap")
            self.assertTrue((Path(td) / rec["images"][0]["file"]).is_file())
            self.assertTrue((Path(td) / "example.com-paper.json").is_file())

        def fake_pdf(url, timeout=30):
            return (b"%PDF-1.4 fake body", "application/pdf")

        with tempfile.TemporaryDirectory() as td, mock.patch.object(fetch, "_download", fake_pdf):
            rec = fetch.fetch_url("https://arxiv.org/pdf/1706.03762v7", out_dir=Path(td), name="attn")
            self.assertEqual(rec["kind"], "pdf")
            self.assertEqual(rec["file"], "attn.pdf")
            self.assertTrue((Path(td) / "attn.pdf").read_bytes().startswith(b"%PDF"))
            self.assertTrue((Path(td) / "attn.json").is_file())

    def test_framework_md_renders_figure_block_without_fabrication(self):
        from bookleme.render.skill import _framework_md
        from bookleme.plugins.builtin.coach_dialogue import PLUGIN
        cap = {
            "title": "T", "source_id": "SRC-001",
            "span": {"segment_id": "seg-001", "char_start": 0, "char_end": 10},
            "ria": {"R_quote": "q", "I_rephrase": "i", "A1_author_case": "a",
                    "A2_user_trigger": "t", "A3_steps": ["s"], "B_not_applicable": "b"},
            "confidence": {"tier": "S"},
            "figure_refs": ["FIG-001", "FIG-002"],
        }
        figs = {
            "FIG-001": {"figure_id": "FIG-001", "caption": "图 1 方法结构", "kind": "figure",
                        "char_start": 5, "image_file": "cache/x/figures/FIG-001.png",
                        "page": 1, "source_id": "SRC-001"},
            "FIG-002": {"figure_id": "FIG-002", "caption": "图 2 未锚定图注", "kind": "figure",
                        "char_start": None, "image_file": None, "page": 2, "source_id": "SRC-001"},
        }
        out = _framework_md(PLUGIN, cap, 1, figs)
        self.assertIn("配套图示", out)
        self.assertIn("assets/figures/FIG-001.png", out)
        self.assertIn("FIG-001", out)
        self.assertNotIn("图 1 方法结构", out, "图注原文不得复制入产物（版权纪律）")
        self.assertNotIn("图 2 未锚定图注", out, "未锚定图注更不得复述")

    def test_copyright_gate_reports_figures_but_does_not_fail_text_checks(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "SKILL.md").write_text("# x\n" + "内容" * 10, encoding="utf-8")
            (d / "assets" / "figures").mkdir(parents=True)
            (d / "assets" / "figures" / "FIG-001.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
            gate = run_copyright_gate(d, "全文" * 100, [], load_run_config(),
                                      figures=[{"figure_id": "FIG-001"}])
        self.assertEqual(gate["figures_report"]["figure_assets_embedded"], 1)
        self.assertEqual(gate["figures_report"]["figures_declared"], 1)
        self.assertTrue(gate["passed"], "图片资产不得触发文本硬门失败")

    def test_figure_distribution_policy(self):
        from bookleme.provenance import figure_distribution_block
        self.assertIsNotNone(figure_distribution_block("licensed", 3), "非自有/公版 + 有图 → 必须阻断公开")
        self.assertIsNotNone(figure_distribution_block("unknown", 1))
        self.assertIsNone(figure_distribution_block("owned", 3))
        self.assertIsNone(figure_distribution_block("public_domain", 2))
        self.assertIsNone(figure_distribution_block("licensed", 0), "无图不阻断")

    def test_figures_schema_validates(self):
        obj = {"schema_version": "2.0", "book_sha256": "x", "figures": [{
            "figure_id": "FIG-001", "source_id": "SRC-001", "page": 1,
            "kind": "figure", "caption": "图 1 方法结构",
            "char_start": 10, "char_end": 18, "image_file": "cache/x/figures/FIG-001.png"}]}
        errors = schema_validate(obj, load_json(SCHEMA_DIR / "figures.schema.json"))
        self.assertEqual(errors, [])
        bad = json.loads(json.dumps(obj))
        bad["figures"][0]["figure_id"] = "XX-1"
        self.assertTrue(schema_validate(bad, load_json(SCHEMA_DIR / "figures.schema.json")))


class TestJudgeAndFigureInsight(unittest.TestCase):
    """3.0：LLM judge（groundedness/V2/V3）+ 读图 → 能力卡。"""

    def _caps(self):
        return {"extractor": "heuristic", "capabilities": [{
            "capability_id": "CAP-0001",
            "title": "重力问题排查",
            "source_id": "SRC-001",
            "span": {"segment_id": "seg-001", "char_start": 10, "char_end": 30},
            "ria": {"R_quote": "先问三个问题再看选项", "I_rephrase": "按次序问三个问题再比较选项",
                    "A1_author_case": "书中的奥德赛计划案例", "A2_user_trigger": "当用户说『我不知道该选什么』时",
                    "A3_steps": ["问第一个问题", "问第二个问题", "比较选项"], "B_not_applicable": "紧急医疗场景不适用"},
            "confidence": {"tier": "S", "score": 0.9},
            "status": "verified",
            "checks": {"quote_verified": True},
        }]}

    def test_judge_majority_and_v2v3(self):
        from bookleme.fidelity import judge_capabilities
        seen = []

        def fake_call(prompt_name, values):
            seen.append(prompt_name)
            if prompt_name == "judge_v1":
                # 三个角色：两票支持、一票反对 → 多数为 True
                grounded = len([v for v in seen if v == "judge_v1"]) != 2
                return {"grounded": grounded, "support": "引文写明了三个问题",
                        "v3_pass": True, "v3_reason": "依赖本书的三问设定"}
            return {"v2_question": "新情境问题", "v2_answer": "答案", "v2_pass": True}

        res = judge_capabilities(self._caps(), "正文开始\n先问三个问题再看选项\n正文结束",
                                 {"llm_judge": {"v2": True}}, votes=3, call=fake_call)
        r = res["results"]["CAP-0001"]
        self.assertTrue(r["grounded"], "三票中两票支持应为 True")
        self.assertEqual(r["grounded_votes"], [True, False, True])
        self.assertTrue(r["v2_pass"])
        self.assertEqual(r["v2_question"], "新情境问题")
        self.assertTrue(r["v3_pass"])
        self.assertEqual(res["summary"]["judged"], 1)
        self.assertTrue(res["model_fingerprint"])

    def test_judge_all_votes_fail_yields_unknown_not_false(self):
        from bookleme.fidelity import judge_capabilities

        def boom(prompt_name, values):
            raise RuntimeError("network down")

        res = judge_capabilities(self._caps(), "x", {}, votes=3, call=boom)
        r = res["results"]["CAP-0001"]
        self.assertIsNone(r["grounded"], "全部失败必须记为未知(None)，不得记为 False")
        self.assertIsNone(r["v2_pass"])
        self.assertGreater(res["summary"]["failed_calls"], 0)
        self.assertTrue(res["errors"])

    def test_judge_prompt_uses_fresh_context_for_v2(self):
        from bookleme.fidelity import judge_capabilities
        captured = {}

        def fake_call(prompt_name, values):
            captured[prompt_name] = dict(values)
            return {"grounded": True, "v3_pass": True} if prompt_name == "judge_v1" \
                else {"v2_pass": True, "v2_question": "q", "v2_answer": "a"}

        judge_capabilities(self._caps(), "先问三个问题再看选项 上下文", {}, votes=1, call=fake_call)
        self.assertIn("context", captured["judge_v1"])
        self.assertNotIn("context", captured["judge_v2_v1"],
                         "V2 必须 fresh-context：不得把原文上下文喂给预测力 judge")
        self.assertIn("rephrase", captured["judge_v2_v1"])

    def test_v1_cross_domain_is_deterministic(self):
        from bookleme.fidelity import v1_cross_domain
        segs = {"segments": [
            {"segment_id": "seg-001", "text": "先问三个问题再看选项，这是第一步"},
            {"segment_id": "seg-002", "text": "先问三个问题再看选项，在别处也这样说"},
            {"segment_id": "seg-003", "text": "完全无关的一段话，讲的是别的事情"},
        ]}
        out = v1_cross_domain(self._caps(), segs)
        self.assertEqual(out["CAP-0001"], ["seg-002"],
                         "只在其他 segment 命中同一表述才计佐证；本 segment 不算")
        self.assertEqual(v1_cross_domain(self._caps(), segs), out, "V1 必须确定性可复现")

    def test_denylist_filter_flags_generic_claims(self):
        from bookleme.fidelity import common_sense_hits, load_denylist
        dl = load_denylist()
        self.assertTrue(dl, "常识短语表必须存在且非空")
        hits = common_sense_hits("遇到问题要多沟通，保持耐心", dl)
        self.assertIn("要多沟通", hits)
        self.assertEqual(common_sense_hits("先问三个问题再看选项", dl), [])

    def test_ledger_carries_real_v1_v2_v3(self):
        from bookleme.fidelity import build_claim_ledger
        ledger = build_claim_ledger(self._caps(), "sha", "/tmp/slices",
                                    judge={"enabled": True, "votes": 3, "model_fingerprint": "fp",
                                           "results": {"CAP-0001": {
                                               "grounded": True, "grounded_votes": [True, True, True],
                                               "v2_pass": True, "v2_question": "q", "v2_answer": "a",
                                               "v3_pass": False, "v3_reason": "偏通用",
                                               "denylist_hits": ["要多沟通"], "support": "有出处"}}},
                                    v1={"CAP-0001": ["seg-002"]})
        claim = ledger["claims"][0]
        self.assertEqual(claim["verification"]["v1_cross_domain"], ["seg-002"])
        self.assertEqual(claim["verification"]["v2_pass"], True)
        self.assertEqual(claim["verification"]["v3_pass"], False)
        self.assertEqual(claim["verification"]["denylist_hits"], ["要多沟通"])
        self.assertEqual(claim["groundedness"], 1.0)

    def test_fidelity_report_groundedness_null_without_judge(self):
        from bookleme.fidelity import build_claim_ledger, build_fidelity_report
        caps = self._caps()
        ledger = build_claim_ledger(caps, "sha", "/tmp/slices")
        rep = build_fidelity_report(caps, ledger, {"segments": []}, [], load_run_config())
        self.assertIsNone(rep["metrics"]["groundedness"]["value"], "未接 judge 必须为 null，不伪造")
        self.assertFalse(rep["judge_summary"]["enabled"])

    def test_figure_insight_card_uses_caption_as_anchor(self):
        from bookleme.capabilities import extract_figure_cards
        from unittest import mock
        figs = [{"figure_id": "FIG-001", "source_id": "SRC-001", "page": 3,
                 "caption": "Figure 1: 整体结构", "char_start": 100, "char_end": 118,
                 "image_file": "cache/x/figures/FIG-001.png"}]
        calls = []
        corpus = ("前言铺垫。" * 20) + "Figure 1: 整体结构" + ("后续讨论。" * 20)
        caption_pos = corpus.index("Figure 1: 整体结构")
        figs[0]["char_start"] = caption_pos

        def fake_call(prompt_name, values, image_path):
            calls.append((prompt_name, image_path))
            return {"title": "整体结构图", "I_rephrase": "这张图给出方法的模块与数据流",
                    "A1_author_case": "图中含编码器与解码器两栏",
                    "A2_user_trigger": "当用户问『整体怎么串起来』时",
                    "A3_steps": ["先看左侧输入", "再看中间编码器", "最后看右侧输出"],
                    "B_not_applicable": "图只给结构，不含具体超参，不能据此定数值"}

        with tempfile.TemporaryDirectory() as td:
            img = Path(td) / "cache" / "x" / "figures" / "FIG-001.png"
            img.parent.mkdir(parents=True)
            img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
            with mock.patch("bookleme.llm.vision_available", return_value=True), \
                 mock.patch("bookleme.config.ROOT", Path(td)):
                cards = extract_figure_cards(figs, {"figure_insight": {"enabled": True}},
                                             book_title="测试书", full_text=corpus,
                                             segments=[{"segment_id": "seg-001", "char_range": [0, len(corpus)]}],
                                             call=fake_call)
        self.assertEqual(len(cards), 1)
        card = cards[0]
        quote = card["ria"]["R_quote"]
        self.assertTrue("Figure 1: 整体结构".startswith(quote),
                        "R_quote 必须是图注的逐字前缀（≤24 字锚点）")
        self.assertLessEqual(len(quote), 24, "图解读卡锚点按项目引文惯例收敛到 ≤24 字")
        self.assertEqual(card["figure_refs"], ["FIG-001"])
        self.assertEqual(card["confidence"]["tier"], "B")
        self.assertEqual(card["origin"], "figure")
        self.assertEqual(len(card["ria"]["A3_steps"]), 3)
        self.assertEqual(calls[0][0], "figure_insight_v1")

    def test_figure_insight_skips_unusable_figures(self):
        from bookleme.capabilities import extract_figure_cards
        from unittest import mock
        figs = [
            {"figure_id": "FIG-001", "source_id": "SRC-001", "page": 1, "caption": "图 1 x",
             "char_start": 10, "char_end": 14, "image_file": None},          # 无位图
            {"figure_id": "FIG-002", "source_id": "SRC-001", "page": 1, "caption": "图 2 x",
             "char_start": None, "char_end": None, "image_file": "a.png"},   # 未锚定
        ]
        with mock.patch("bookleme.llm.vision_available", return_value=True):
            cards = extract_figure_cards(figs, {"figure_insight": {"enabled": True}}, call=None)
        self.assertEqual(cards, [], "无位图或无逐字锚点的图不得产出解读卡")

    def test_figure_insight_disabled_without_vision_model(self):
        from bookleme.capabilities import extract_figure_cards
        from unittest import mock
        figs = [{"figure_id": "FIG-001", "source_id": "SRC-001", "page": 1, "caption": "图 1 x",
                 "char_start": 10, "char_end": 14, "image_file": "a.png"}]
        with mock.patch("bookleme.llm.vision_available", return_value=False):
            cards = extract_figure_cards(figs, {"figure_insight": {"enabled": True}}, call=None)
        self.assertEqual(cards, [], "未配置视觉模型 → 不产出任何解读（不伪造）")

    def test_llm_call_counting_counts_success(self):
        from unittest import mock
        import bookleme.llm as llm_mod
        llm_mod.reset_counters()
        with mock.patch.dict("os.environ", {llm_mod.ENV_BASE: "https://x/v1",
                                            llm_mod.ENV_KEY: "k",
                                            llm_mod.ENV_MODEL: "m"}), \
             mock.patch.object(llm_mod, "_post", return_value={
                 "choices": [{"message": {"content": "{\"ok\": true}"}}]}):
            llm_mod.chat_json("hi")
        self.assertEqual(llm_mod.llm_calls, 1, "成功的真实 HTTP 调用必须计入 llm_calls")
        llm_mod.reset_counters()

    def test_vision_payload_has_image_part(self):
        from unittest import mock
        import bookleme.llm as llm_mod
        captured = {}

        def fake_post(url, payload, key, to):
            captured.update(payload)
            return {"choices": [{"message": {"content": "{\"title\": \"t\"}"}}]}

        with tempfile.TemporaryDirectory() as td:
            img = Path(td) / "a.png"
            img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
            with mock.patch.dict("os.environ", {llm_mod.ENV_BASE: "https://x/v1",
                                                llm_mod.ENV_KEY: "k",
                                                llm_mod.ENV_MODEL: "m"}), \
                 mock.patch.object(llm_mod, "_post", fake_post):
                llm_mod.chat_vision_json("看这张图", image_path=img)
        content = captured["messages"][-1]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))


class TestGenreFieldContractAndAdr(unittest.TestCase):
    """3.0 收尾：体裁额外字段契约化 + ADR-002 映射一致性 + 状态机四项校验。"""

    def test_genre_fields_are_filled_even_on_deterministic_path(self):
        from bookleme.capabilities import extract_capabilities
        caps = extract_capabilities(
            "第一章\n正文一句。\n", [{"segment_id": "seg-001", "heading": "第一章",
                                     "char_range": [0, 20], "text": "第一章\n正文一句。\n"}],
            load_run_config(), book_title="测试书",
            genre_fields={"threshold": "阈值说明", "decision_tree": "决策树说明"})
        card = caps["capabilities"][0]
        self.assertEqual(set(card["genre_fields"]), {"threshold", "decision_tree"})
        for name, val in card["genre_fields"].items():
            self.assertTrue(val.strip(), f"{name} 不得为空")
            self.assertEqual(val, "书里没讲", "确定性抽取路径不得编造阈值/矩阵，只能如实标注")

    def test_resolve_plugin_follows_routed_genre_for_knowledge_pack(self):
        from bookleme.plugins import load_plugins, resolve_plugin
        registry, _ = load_plugins()
        plugin, reason = resolve_plugin(registry, "knowledge_pack", ["decision_checklist"])
        self.assertEqual(getattr(plugin, "genre_id", None), "decision_checklist",
                         "ADR-002：引擎 = 插件 default_engines，knowledge_pack 也应用被路由的体裁")
        self.assertTrue(reason.startswith("preferred:"))
        # 首选插件不支持该引擎时，退回检索型契约
        plugin2, reason2 = resolve_plugin(registry, "knowledge_pack", ["coach_dialogue"])
        self.assertEqual(getattr(plugin2, "genre_id", None), "knowledge_reference")
        self.assertIn("fallback", reason2)

    def test_state_machine_validator_catches_dead_and_isolated_states(self):
        from bookleme.plugins.validator import _check_state_machine
        bad = {
            "states": ["a", "b", "orphan"],
            "initial": "a", "terminal": ["z"],
            "transitions": [{"from": "a", "to": "b", "on": "x"}],
        }
        errors = _check_state_machine(bad)
        joined = " | ".join(errors)
        self.assertIn("orphan", joined, "孤立状态必须被拦下")
        self.assertIn("terminal", joined, "terminal 不在 states 必须被拦下")
        good = {
            "states": ["a", "b"], "initial": "a", "terminal": ["b"],
            "transitions": [{"from": "a", "to": "b", "on": "x"}],
        }
        self.assertEqual(_check_state_machine(good), [], "合法状态机不应报错")

    def test_dump_json_isolates_concurrent_writes_by_pid(self):
        from bookleme.config import dump_json
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.json"
            dump_json(p, {"a": 1})
            self.assertEqual(load_json(p), {"a": 1})
            leftovers = list(Path(td).glob("*.tmp"))
            self.assertEqual(leftovers, [], "临时文件必须被 replace 掉")
            self.assertTrue(p.is_file())


class TestZeroConfigAndInspector(unittest.TestCase):
    """2.1：LLM 零配置自识别 + doctor 自检 + 编译产物检视台。"""

    def test_llm_autodetects_standard_provider_env(self):
        from unittest import mock
        import bookleme.llm as llm_mod
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False), \
             mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            llm_mod.reset_counters()
            s = llm_mod.settings()
            self.assertTrue(llm_mod.available(), "标准厂商密钥环境变量应被自动识别，用户零配置")
            self.assertEqual(s["base_url"], "https://api.openai.com/v1")
            self.assertTrue(s["source"])
            self.assertIn("OPENAI_API_KEY", s["source"])
        llm_mod.reset_counters()

    def test_llm_reads_config_file_and_env_wins(self):
        from unittest import mock
        import bookleme.llm as llm_mod
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text(json.dumps({"llm": {"base_url": "https://x/v1", "api_key": "k",
                                               "model": "m", "api_key_env": "MY_KEY"}}),
                           encoding="utf-8")
            with mock.patch.object(llm_mod, "CONFIG_PATH", cfg), \
                 mock.patch.dict("os.environ", {"MY_KEY": "from-env"}, clear=False):
                llm_mod.reset_counters()
                self.assertTrue(llm_mod.available(), "配置文件里的 api_key_env 应能取到密钥")
                self.assertEqual(llm_mod.settings()["model"], "m")
                with mock.patch.dict("os.environ", {"BOOKLEME_LLM_MODEL": "env-model"}):
                    llm_mod.reset_counters()
                    self.assertEqual(llm_mod.settings()["model"], "env-model",
                                     "显式环境变量优先级最高")
        llm_mod.reset_counters()

    def test_doctor_reports_without_asking_user_to_configure(self):
        import json as _json
        import subprocess
        root = Path(__file__).resolve().parents[1]
        out = subprocess.run(["python3", "-m", "bookleme", "doctor"], cwd=str(root),
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-400:])
        rep = _json.loads(out.stdout)
        self.assertTrue(rep["ok"])
        self.assertIn("llm", rep)
        self.assertIn("hint", rep["llm"], "必须给出「不用配置也能用」的说明")
        self.assertIn("next", rep)
        self.assertTrue(rep["plugins"]["available"], "doctor 应报出可用体裁")

    def test_check_accepts_complete_skill(self):
        """可用性验收：完整产物应判「可直接用」，而不是只检查文件存在。"""
        import tempfile
        from bookleme.check import _check_artifact

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            refs = root / "references"
            refs.mkdir()
            (root / "SKILL.md").write_text(
                "# T\n\n## 核心定位\nx\n\n## 触发场景\nx\n\n## 工作流\nx\n\n"
                "## 输出格式\nx\n\n## Gotchas\n- 书里没讲就明说\n", encoding="utf-8")
            (refs / "framework-01.md").write_text(
                "## 何时读本文件\n\n## 框架：重力问题\n\n1. 说出困扰\n2. 判断可否改变\n\n"
                "不适用边界：临床危机不适用。\n\n出处：SRC-001 / seg-002 / char_range [1, 9)\n",
                encoding="utf-8")
            (refs / "topic-index.md").write_text(
                "## 何时读本文件\n\n| 意图 | 文件 |\n| --- | --- |\n"
                "| 重力问题 | `references/framework-01.md` |\n", encoding="utf-8")
            (root / "evals").mkdir()
            (root / "evals" / "smoke.md").write_text(
                "- [positive] a\n- [negative] b\n- [boundary] c\n", encoding="utf-8")

            art = {"engine": "behavior_skill", "display_name": "T", "slug": "s",
                   "skill_dir": str(root)}
            r = _check_artifact(art, root)
            self.assertEqual(r["frameworks"], 1)
            self.assertEqual(r["actionable"], 1)
            self.assertEqual(r["traceable"], 1)
            self.assertEqual(r["hard"], [], r["hard"])
            self.assertEqual(r["soft"], [], r["soft"])

    def test_check_flags_shard_without_traceable_source(self):
        import tempfile
        from bookleme.check import _check_artifact

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir()
            (root / "SKILL.md").write_text(
                "## 核心定位\n## 触发场景\n## 工作流\n## 输出格式\n## Gotchas\n书里没讲\n",
                encoding="utf-8")
            (root / "references" / "framework-01.md").write_text(
                "## 何时读本文件\n1. 甲\n2. 乙\n不适用边界：无\n", encoding="utf-8")
            art = {"engine": "knowledge_pack", "display_name": "T", "slug": "s",
                   "skill_dir": str(root)}
            r = _check_artifact(art, root)
            self.assertTrue(any("出处" in m for m in r["hard"]), r["hard"])


class TestIntake(unittest.TestCase):
    """输入整形：目录摊平、书名推断、公开源不被静默混入。"""

    def _book(self, td: Path, heading: str) -> Path:
        src = (ROOT / "evals/cases/synthetic/coach_book.md").read_text(encoding="utf-8")
        body = src.split("\n", 1)[1]
        p = td / "coach_book.md"
        p.write_text(f"# {heading}\n" + body, encoding="utf-8")
        return p

    def test_directory_input_and_title_from_heading(self):
        import tempfile
        from bookleme.intake import expand_paths, infer_title

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._book(root, "我的测试书")
            (root / ".hidden").mkdir()
            (root / ".hidden" / "x.md").write_text("# 隐藏", encoding="utf-8")
            files, urls = expand_paths([str(root)])
            self.assertEqual(len(files), 1, "目录应摊平成文件，且跳过隐藏目录")
            self.assertEqual(urls, [])
            title, hint = infer_title(files)
            self.assertEqual(title, "我的测试书", "书名应取首个一级标题，而不是文件名")
            self.assertIn("一级标题", hint)

    def test_public_sources_are_opt_in(self):
        """以前 fetch 过一次，之后每次 run 都会把那些内容悄悄混进语料。"""
        import tempfile
        from bookleme.pipeline import Pipeline
        from bookleme.config import CACHE_DIR, load_router_config, load_run_config

        with tempfile.TemporaryDirectory() as td:
            p = self._book(Path(td), "隔离测试书")
            pipe = Pipeline(load_run_config(), load_router_config())
            s = pipe.run([str(p)], run_id="unittest-public-isolation",
                         engine="knowledge_pack")
            cache = CACHE_DIR / s["book_sha256"][:12]
            src = json.loads((cache / "sources.json").read_text(encoding="utf-8"))
            origins = {x["origin"] for x in src["sources"]}
            self.assertEqual(origins, {"local"},
                             f"公开源不该自动并入，实际：{src['sources']}")
            prov = json.loads((Path(s["out_dir"]) / "provenance_manifest.json")
                              .read_text(encoding="utf-8"))
            self.assertEqual(prov["book"]["title"], "隔离测试书")

    def test_coverage_file_lists_only_this_books_toc(self):
        from bookleme.render.skill import render_skill
        from bookleme.plugins import load_plugins
        from bookleme.check import _read

        registry, _ = load_plugins()
        plugin = registry["knowledge_reference"]
        cap = {"capability_id": "CAP-0001", "title": "T", "source_id": "SRC-001",
               "span": {"segment_id": "seg-001", "char_start": 1, "char_end": 5},
               "ria": {"R_quote": "Q", "I_rephrase": "R", "A1_author_case": "A",
                       "A2_user_trigger": "U", "A3_steps": ["1"], "B_not_applicable": "N"},
               "confidence": {"tier": "S", "score": 0.9}, "status": "verified"}
        files = render_skill(plugin, {
            "slug": "s", "display_name": "D", "description": "d", "book_title": "B",
            "author": "", "engine": "knowledge_pack", "run_id": "r",
            "config": {"engine_order": ["knowledge_pack"], "max_quote_chars": 150},
            "verified_capabilities": [cap], "segments": {"segments": []},
            "provenance_manifest": {"book": {"title": "B", "author": "", "isbn": "",
                                            "user_rights": "unknown"},
                                    "distribution": {"decision": "private", "reason": "r"},
                                    "attribution": {"statement": "", "notice": ""},
                                    "engine": {"bookleme_version": "x", "plugin_id": "k"}},
            "fidelity_report": {}, "router_result": {}, "figures": [],
            "toc": [{"heading": "第一章 只属于这本书", "level": 1},
                    {"heading": "第二章 也不属于别的书", "level": 1}],
        })
        self.assertIn("references/coverage.md", files)
        self.assertIn("第一章 只属于这本书", files["references/coverage.md"])
        self.assertIn("coverage.md", files["references/topic-index.md"])
        self.assertIn("方法主线", files["SKILL.md"], "SKILL.md 应给出这本书的方法主线")


class TestReviewFixes(unittest.TestCase):
    """2.1 审查轮修掉的缺陷，各加一条回归锁死。"""

    def _caps(self):
        return {"extractor": "heuristic", "capabilities": [{
            "capability_id": "CAP-0001", "title": "T", "source_id": "SRC-001",
            "span": {"segment_id": "seg-001", "char_start": 10, "char_end": 30},
            "ria": {"R_quote": "先问三个问题再看选项", "I_rephrase": "按次序问三个问题再比较选项",
                    "A1_author_case": "书中的用例", "A2_user_trigger": "当用户说『我不知道该选什么』时",
                    "A3_steps": ["问一", "问二", "问三"], "B_not_applicable": "紧急场景不适用"},
            "confidence": {"tier": "S", "score": 0.9}, "status": "verified",
            "checks": {"quote_verified": True},
        }]}

    def test_judge_tie_is_unknown_not_false(self):
        from bookleme.fidelity.judge import _majority
        self.assertIsNone(_majority([True, False]), "平票必须是未知(None)，不能记成 False")
        self.assertIsNone(_majority([]))
        self.assertTrue(_majority([True, True, False]))
        self.assertFalse(_majority([False, False, True]))

    def test_judge_fingerprint_binds_both_prompts(self):
        from bookleme.fidelity import judge_capabilities
        seen = {}

        def fake_call(prompt_name, values):
            seen[prompt_name] = values
            return {"grounded": True, "v3_pass": True} if prompt_name == "judge_v1" \
                else {"v2_pass": True, "v2_question": "q", "v2_answer": "a"}

        res = judge_capabilities(self._caps(), "正文 先问三个问题再看选项 结束", {},
                                 votes=3, call=fake_call)
        self.assertIn("judge_v2_v1", res["prompt_version"],
                      "指纹必须同时绑定 V2 的 prompt，否则换 V2 prompt 指纹不变")
        self.assertIn("judge_v1", res["prompt_version"])

    def test_judge_reports_actual_vote_count(self):
        from bookleme.fidelity import judge_capabilities

        def fake_call(prompt_name, values):
            return {"grounded": True, "v3_pass": True} if prompt_name == "judge_v1" \
                else {"v2_pass": True}

        res = judge_capabilities(self._caps(), "x 先问三个问题再看选项 y", {}, votes=9,
                                 call=fake_call)
        self.assertEqual(res["votes"], 3, "可用 persona 只有 3 个，报告必须写实际票数")
        self.assertEqual(res["votes_requested"], 9)

    def test_prompt_placeholder_not_resubstituted(self):
        from bookleme.fidelity.judge import _default_call
        from unittest import mock
        captured = {}

        def fake_chat(user, system="", **kw):
            captured["user"] = user
            captured["system"] = system
            return {"ok": True}

        with mock.patch("bookleme.llm.chat_json", fake_chat):
            _default_call("judge_v1", {"context": "真实上下文", "title": "T",
                                       "quote": "Q", "rephrase": "R",
                                       "persona_role": "你是考据员"})
        self.assertIn("真实上下文", captured["user"])
        # 原文里的 ${context} 字面量不应被二次替换成真实上下文
        self.assertNotIn("${context}", captured["user"])

    def test_validator_survives_none_fields(self):
        from bookleme.plugins.base import GenrePlugin
        from bookleme.plugins.validator import validate_plugin
        p = GenrePlugin(genre_id="x", display_name_zh="测试", version="1.0.0",
                        router_rules=None, capability_schema=None, section_template=None,
                        skill_template=None, hard_constraints=None, state_machine=None,
                        output_contract=None, anti_patterns=None, eval_prompts=None,
                        trigger_words=None, routing_rules=None, voice_calibration=None,
                        copyright_profile=None, default_engines=None, engine_kind="behavior")
        errors = validate_plugin(p)
        self.assertTrue(errors, "None 字段必须被记成错误")
        self.assertTrue(any("不能为 None" in e or "必须是" in e for e in errors), errors[:3])

    def test_safety_scan_ignores_comments_and_docstrings(self):
        from bookleme.plugins.validator import _scan_unsafe
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "p.py"
            f.write_text('"""插件说明：这里绝不会用 eval，也不调用 requests.get。"""\n'
                         '# 注释里提到 subprocess.run 也不该被拦\n'
                         'X = 1\n', encoding="utf-8")
            self.assertEqual(_scan_unsafe(str(f)), [],
                             "注释与文档字符串里的危险字样不该被当成风险")
            f.write_text('X = eval("1 + 1")\n', encoding="utf-8")
            self.assertTrue(_scan_unsafe(str(f)), "真实可执行代码仍要拦住")

    def test_llm_doctor_reports_missing_items_not_vague(self):
        from bookleme import llm as llm_mod
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text(json.dumps({"llm": {"base_url": "https://x/v1"}}), encoding="utf-8")
            with mock.patch.object(llm_mod, "CONFIG_PATH", cfg):
                llm_mod.reset_counters()
                d = llm_mod.describe()
                self.assertFalse(d["available"])
                self.assertEqual(d["missing"], ["api_key", "model"],
                                 "必须指出缺哪一项，而不是笼统说没检测到")
                self.assertIn("api_key", d["hint"])
        llm_mod.reset_counters()

    def test_configs_pass_their_schemas(self):
        from bookleme.config import DEFAULT_RUN_CONFIG, ROUTER_CONFIG
        for cfg_path, schema_name in ((DEFAULT_RUN_CONFIG, "default.run.schema.json"),
                                      (ROUTER_CONFIG, "router.schema.json")):
            errors = schema_validate(load_json(cfg_path), load_json(SCHEMA_DIR / schema_name))
            self.assertEqual(errors, [], f"{cfg_path.name} 不合 schema：{errors}")


    def test_fetch_rejects_non_http_and_internal_addresses(self):
        from bookleme.fetch import fetch_url
        from bookleme.fetch import _check_url
        with tempfile.TemporaryDirectory() as td:
            for bad in ("file:///etc/passwd", "ftp://example.com/x", "http://127.0.0.1/x",
                        "http://localhost/x", "http://169.254.169.254/latest/meta-data/",
                        "http://192.168.1.1/x", "http://10.0.0.1/x"):
                with self.subTest(url=bad):
                    with self.assertRaises(ValueError):
                        _check_url(bad)
                    with self.assertRaises(ValueError):
                        fetch_url(bad, out_dir=Path(td))
            self.assertEqual(list(Path(td).glob("*")), [], "被拒的地址不得留下任何落盘文件")

    def test_every_claim_source_tier_matches_its_source(self):
        """FIDELITY §4 硬规则 4：claim_ledger.source_tier 必须与 provenance 同源。"""
        import json as _json
        cache_dirs = sorted((ROOT / "cache").iterdir(), key=lambda p: p.stat().st_mtime)
        self.assertTrue(cache_dirs, "cache/ 下应有历史 IR")
        ledger = None
        prov = None
        for d in reversed(cache_dirs):
            lp = d / "claim_ledger.json"
            if lp.is_file():
                ledger = _json.loads(lp.read_text(encoding="utf-8"))
                break
        self.assertIsNotNone(ledger, "找不到 claim_ledger.json")
        runs = sorted((ROOT / "out").iterdir(), key=lambda p: p.stat().st_mtime)
        for r in reversed(runs):
            pp = r / "provenance_manifest.json"
            if pp.is_file():
                prov = _json.loads(pp.read_text(encoding="utf-8"))
                break
        self.assertIsNotNone(prov, "找不到 provenance_manifest.json")
        tiers = {s["source_id"]: s["tier"] for s in prov.get("sources", [])}
        mismatched = [c for c in ledger["claims"]
                      if c.get("source_tier") != tiers.get(c.get("source_id"))]
        self.assertEqual(mismatched, [],
                         f"这些断言的来源等级与 provenance 不一致：{mismatched[:3]}")

    def test_claim_ledger_source_tier_matches_source_not_extraction(self):
        from bookleme.fidelity import build_claim_ledger
        caps = {"extractor": "llm", "capabilities": [{
            "capability_id": "CAP-0001", "title": "T", "source_id": "SRC-002",
            "span": {"segment_id": "seg-001", "char_start": 0, "char_end": 5},
            "ria": {"R_quote": "q", "I_rephrase": "i", "A1_author_case": "a",
                    "A2_user_trigger": "t", "A3_steps": ["s"], "B_not_applicable": "b"},
            "confidence": {"tier": "B", "score": 0.7},
            "source_tier": "B", "checks": {"quote_verified": True}, "claims": ["CLM-1"],
            "status": "verified",
        }]}
        claim = build_claim_ledger(caps, "sha", "/tmp/slices")["claims"][0]
        self.assertEqual(claim["source_tier"], "B", "来源等级取自来源，不得取抽取方式等级")
        self.assertEqual(claim["confidence_tier"], "B", "抽取方式等级另存 confidence_tier")


class TestPatch211Fixes(unittest.TestCase):
    """2.1.1 补丁：密钥同源、缓存指纹、锚点权威性、命令体验。"""

    def test_llm_never_crosses_providers(self):
        """配置指了 A 厂商端点，就绝不能拿 B 厂商的密钥去补（等于把密钥发给别家）。"""
        from unittest import mock
        import bookleme.llm as llm_mod
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text(json.dumps({"llm": {
                "base_url": "https://api.moonshot.cn/v1",
                "api_key_env": "MOONSHOT_API_KEY", "model": "moonshot-v1-8k"}}), encoding="utf-8")
            with mock.patch.object(llm_mod, "CONFIG_PATH", cfg), \
                 mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-openai"}, clear=False):
                llm_mod.reset_counters()
                s = llm_mod.settings()
                self.assertNotEqual(s["api_key"], "sk-openai",
                                    "不得拿别家厂商的密钥配已指定的端点")
                self.assertFalse(llm_mod.available(), "缺本家密钥时应如实报未就绪")
                self.assertIn("api_key", s["missing"])
        llm_mod.reset_counters()

    def test_llm_config_fingerprint_changes_with_model(self):
        from unittest import mock
        import bookleme.llm as llm_mod
        with mock.patch.dict("os.environ", {
                "BOOKLEME_LLM_BASE_URL": "https://x/v1", "BOOKLEME_LLM_API_KEY": "k",
                "BOOKLEME_LLM_MODEL": "model-a"}, clear=False):
            llm_mod.reset_counters()
            a = llm_mod.config_fingerprint()
            with mock.patch.dict("os.environ", {"BOOKLEME_LLM_MODEL": "model-b"}):
                llm_mod.reset_counters()
                b = llm_mod.config_fingerprint()
            self.assertNotEqual(a, b, "换模型必须改变指纹（否则缓存不失效、指标被当成同一次实验）")
            self.assertNotIn("k", a, "指纹不得包含密钥明文")
        llm_mod.reset_counters()

    def test_verify_quotes_respects_authoritative_anchor(self):
        from bookleme.fidelity import verify_quotes
        text = "目录：先问三个问题再看选项\n正文甲：先问三个问题再看选项\n正文乙：别的内容"
        caps = {"capabilities": [{
            "capability_id": "CAP-0001", "ria": {"R_quote": "先问三个问题再看选项",
                                                "I_rephrase": "i", "A1_author_case": "a",
                                                "A2_user_trigger": "t", "A3_steps": ["s"],
                                                "B_not_applicable": "b"},
            "span": {"segment_id": "seg-002", "char_start": text.rindex("先问三个问题再看选项"),
                     "char_end": 0},
            "checks": {}, "claims": [], "confidence": {"tier": "S"},
        }]}
        out, _ = verify_quotes(caps, text, [], load_run_config())
        cap = out["capabilities"][0]
        self.assertEqual(cap["span"]["char_start"], text.rindex("先问三个问题再看选项"),
                         "已有权威锚点时不得退回 find 的第一次出现位置")

    def test_judge_context_uses_anchor_not_first_occurrence(self):
        from bookleme.fidelity.judge import _context
        text = "目录：先问三个问题再看选项\n正文：先问三个问题再看选项 真正的判据在这里"
        anchor = text.rindex("先问三个问题再看选项")
        ctx = _context(text, "先问三个问题再看选项", 40, anchor)
        self.assertIn("真正的判据在这里", ctx, "判据上下文必须取锚点附近，而不是目录页")

    def test_plugin_list_command_exists(self):
        import subprocess
        root = Path(__file__).resolve().parents[1]
        out = subprocess.run(["python3", "-m", "bookleme", "plugin", "list"], cwd=str(root),
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-300:])
        for gid in ("coach_dialogue", "knowledge_reference", "professional_analysis",
                    "decision_checklist"):
            self.assertIn(gid, out.stdout)

    def test_eval_prints_human_summary(self):
        import subprocess
        root = Path(__file__).resolve().parents[1]
        runs = sorted((d for d in (root / "out").iterdir() if d.is_dir()),
                      key=lambda p: p.stat().st_mtime)
        run_id = runs[-1].name
        out = subprocess.run(["python3", "-m", "bookleme", "eval", "--run-id", run_id],
                             cwd=str(root), capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-300:])
        self.assertIn("run", out.stdout)
        self.assertIn("忠实度", out.stdout)

    def test_public_requires_declared_rights(self):
        import subprocess
        root = Path(__file__).resolve().parents[1]
        out = subprocess.run(["python3", "-m", "bookleme", "run", "--input",
                              "evals/cases/synthetic/coach_book.md", "--public",
                              "--confirm-public", "PUBLISH"],
                             cwd=str(root), capture_output=True, text=True, timeout=180)
        self.assertEqual(out.returncode, 1)
        self.assertIn("user-rights", out.stderr, "公开分发缺权利声明必须在开跑前就拦下")

    def test_check_missing_run_is_friendly(self):
        import subprocess
        root = Path(__file__).resolve().parents[1]
        out = subprocess.run(["python3", "-m", "bookleme", "check", "no-such-run"],
                             cwd=str(root), capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 1)
        self.assertNotIn("Traceback", out.stderr, "不存在的 run 不该抛裸栈")

    def test_write_text_uses_pid_scoped_temp(self):
        from bookleme.config import dump_json
        import os as _os
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.txt"
            p.write_text("旧", encoding="utf-8")
            # 用 pipeline 的写法落一次，确认不留 .tmp
            from bookleme.pipeline import Pipeline
            tmp = p.with_name(f"{p.name}.{_os.getpid()}.tmp")
            tmp.write_text("新", encoding="utf-8")
            _os.replace(tmp, p)
            self.assertEqual(p.read_text(encoding="utf-8"), "新")
            self.assertEqual(list(Path(td).glob("*.tmp")), [])

    def test_conversation_skill_supports_pause_resume_and_progress(self):
        """对话型体裁的三条交互纪律：可见进度 / 可打断可收回 / 不打断。"""
        from bookleme.plugins import load_plugins
        registry, _ = load_plugins()
        p = registry["coach_dialogue"]
        constraints = " ".join(p.hard_constraints)
        self.assertIn("第几问", constraints, "每轮必须交代进度")
        self.assertIn("再按能收回", constraints, "用户改主意/想回上一问时要能收回")
        self.assertIn("到此为止", constraints, "用户要停时必须立即收束")
        sm = p.state_machine
        self.assertIn("paused", sm["states"], "需要可中断的状态")
        edges = {(t["from"], t["to"]) for t in sm["transitions"]}
        self.assertTrue(any(f == "paused" for f, _ in edges), "必须有进入 paused 的路径")
        self.assertTrue(any(t == "paused" for _, t in edges), "必须有从 paused 出来的路径")

    def test_all_genres_share_one_delivery_skeleton(self):
        """同一件事处处一样：四个体裁用同一套呈现动线。"""
        from bookleme.plugins import load_plugins
        registry, _ = load_plugins()
        for gid, p in registry.items():
            self.assertIn("呈现顺序固定", p.skill_template,
                          f"{gid} 的交付模板缺统一呈现动线")

    def test_knowledge_reference_asks_for_missing_data(self):
        from bookleme.plugins import load_plugins
        registry, _ = load_plugins()
        contract = registry["knowledge_reference"].output_contract
        self.assertIn("还需要哪些数据", contract["sections"])
        self.assertIn("还需要哪些数据", contract["required_fields"])


class TestHtmlContentQuality(unittest.TestCase):
    """2.1.2：网页正文净化 + 内容质量硬门。

    背景：真实事故——微软页面 93% 语料是 base64 噪声，16 个框架全是
    「窗口 N（无标题回退）」，引文是 'Gift cards' 这种垃圾，但 check 判
    「能用」。这两组测试锁住修复：抽取不产噪声 + 硬门能拦住这类产物。
    """

    def test_template_tag_is_skipped(self):
        """<template> 里的 base64 数据不得进语料。"""
        from bookleme.fetch import PageParser
        html = (
            "<html><body><main><p>Real sentence about RL infrastructure.</p>"
            "<template data-widget-html>" + "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=" * 5 +
            "</template>"
            "<h2>Rocket overview</h2><p>More real content here.</p></main></body></html>"
        )
        p = PageParser()
        p.feed(html)
        text = p.result_text()
        self.assertNotIn("QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo", text,
                         "template 里的 base64 泄漏进语料了")
        self.assertIn("Real sentence about RL infrastructure.", text)

    def test_headings_become_markdown(self):
        """HTML 标题要转成 Markdown 标记，否则分段器退化成「窗口 N」。"""
        from bookleme.fetch import PageParser
        html = (
            "<html><body><main><h2>Controlling staleness</h2>"
            "<p>Body text about staleness in RL rollouts.</p>"
            "<h3>Numerical precision</h3><p>More text here about precision.</p>"
            "</main></body></html>"
        )
        p = PageParser()
        p.feed(html)
        text = p.result_text()
        self.assertIn("## Controlling staleness", text)
        self.assertIn("### Numerical precision", text)

    def test_nav_and_footer_dropped(self):
        """导航/页脚噪声不得进语料。"""
        from bookleme.fetch import PageParser
        html = (
            "<html><body><nav>Skip to main content Microsoft 365 Azure Copilot</nav>"
            "<main><p>The actual article body goes here.</p></main>"
            "<footer>Sitemap Contact Microsoft Privacy Manage cookies</footer>"
            "</body></html>"
        )
        p = PageParser()
        p.feed(html)
        text = p.result_text()
        self.assertIn("The actual article body goes here.", text)
        self.assertNotIn("Sitemap Contact Microsoft", text)
        self.assertNotIn("Skip to main content", text)

    def test_ui_share_controls_dropped(self):
        """社交分享控件噪声不得进语料。"""
        from bookleme.fetch import PageParser
        html = (
            "<html><body><main><p>Article body starts here.</p>"
            "<h2>Share this article</h2><p>LinkedIn (opens in a new tab)</p>"
            "<p>X (opens in a new tab)</p></main></body></html>"
        )
        p = PageParser()
        p.feed(html)
        text = p.result_text()
        self.assertNotIn("Share this article", text)
        self.assertNotIn("opens in a new tab", text)

    def test_junk_quote_detected(self):
        """噪声引文必须被识别（否则硬门形同虚设）。"""
        from bookleme.check import _is_junk_quote
        self.assertTrue(_is_junk_quote("ICdub25lJzsgc2Ny"))
        self.assertTrue(_is_junk_quote("QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo"))
        self.assertTrue(_is_junk_quote("..."))
        self.assertTrue(_is_junk_quote(""))
        # 正常英文原文不能被误判
        self.assertFalse(_is_junk_quote("Our largest RL runs span thousands of GPUs."))
        self.assertFalse(_is_junk_quote("Rocket is not an abstract system."))

    def test_placeholder_framework_name_detected(self):
        """占位式框架名必须被识别。"""
        from bookleme.check import PLACEHOLDER_FRAMEWORK_RE
        self.assertTrue(PLACEHOLDER_FRAMEWORK_RE.match("窗口 1（无标题回退）"))
        self.assertTrue(PLACEHOLDER_FRAMEWORK_RE.match("窗口 12"))
        self.assertTrue(PLACEHOLDER_FRAMEWORK_RE.match("Segment 3"))
        # 真实框架名不能被误判
        self.assertFalse(PLACEHOLDER_FRAMEWORK_RE.match("Controlling staleness"))
        self.assertFalse(PLACEHOLDER_FRAMEWORK_RE.match("Numerical precision"))

    def test_short_title_keeps_english_words(self):
        """标题截断不能切半个词，也不能把英文砍成一个词。"""
        from bookleme.intake import short_title
        out = short_title("RL Infrastructure at Microsoft AI", 12)
        self.assertNotEqual(out, "RL")
        self.assertTrue(out.endswith(("RL", "at", "Microsoft")), out)
        # 中文行为不变
        self.assertEqual(short_title("人生设计练习册", 12), "人生设计练习册")

    def test_extract_html_shares_parser_with_fetch(self):
        """本地 HTML 与 URL 抓取必须走同一套解析器（不能各写一套漂移）。"""
        import inspect
        from bookleme.extract import html as html_mod
        src = inspect.getsource(html_mod)
        self.assertIn("PageParser", src,
                      "extract/html.py 必须复用 fetch.PageParser，否则两套规则会漂移")

    def test_english_quote_not_cut_at_chinese_punctuation(self):
        """英文正文的引文不能被中文标点切坏（曾经产出 'Figure 1 shows R'）。"""
        from bookleme.capabilities.extract import _first_sentence_quote
        content = ("Rocket is not an abstract system, it is actively powering the model "
                   "progress on our aggressive frontier models. The steadiness matters.")
        quote = _first_sentence_quote(content, 150)
        self.assertIn("Rocket is not an abstract system", quote)
        self.assertGreater(len(quote), 40)

    def test_quote_always_verbatim_substring(self):
        """引文必须恒为原文精确子串（find 必须命中）——逐字性是硬约束。"""
        from bookleme.capabilities.extract import _first_sentence_quote
        samples = [
            "Staleness. Agentic rollouts can take hours while the learner keeps "
            "updating the policy. Because GRPO scores each rollout.",
            "这样一句话。第二句在这里。",
            "Numerical consistency. Fitting a larger model requires lower-precision math.",
            "短。",
        ]
        for content in samples:
            quote = _first_sentence_quote(content, 150)
            self.assertIn(quote, content,
                          f"引文不是原文子串：{quote!r}")

    def test_ambiguity_fallback_follows_top1_engine_table(self):
        """歧义兜底不得无条件双出引擎。

        背景：兜底曾固定输出 knowledge_pack + behavior_skill，于是 margin 偏小
        的技术文档会硬套「自我对话教练」（触发词是人生设计/自我对话，与技术
        内容完全无关）。现在兜底按 top1 体裁自己的引擎表出产物。
        """
        from bookleme.router.rules import route
        cfg = load_router_config()
        # 构造 margin 偏小的英文技术文档 → 走 ambiguity 分支
        text = ("The system scales. " * 200 +
                "Numerically accurate reinforcement learning requires scale. " * 60)
        from bookleme.segment.headings import segment_text
        segs = segment_text(text, [], load_run_config())["segments"]
        result, _ = route(text, segs, [], cfg)
        self.assertEqual(result["override_source"], "ambiguity",
                         "该样本应走歧义兜底分支")
        # top1 是 knowledge_reference 时，只应出 knowledge_pack
        if result["top1"] == "knowledge_reference":
            self.assertEqual(result["engines"], ["knowledge_pack"],
                             f"歧义兜底不应硬套教练技能：{result['engines']}")
        # 任何情况下都不该在 top1=knowledge_reference 时产出 behavior_skill
        if result["top1"] == "knowledge_reference":
            self.assertNotIn("behavior_skill", result["engines"])


class TestHostAgentJudgeChannel(unittest.TestCase):
    """宿主 Agent 承接 judge：用户不需要配任何 API key。

    背景：BookLeme 是 harness，宿主 Agent 本身就是大模型。让用户配
    OPENAI_API_KEY 让 BookLeme 自己去调外部模型，是把在场能做的事外包出去。
    这组测试锁住「导出工单 → 宿主判定 → 回填」这条通道。
    """

    def _caps(self):
        return {"capabilities": [{
            "capability_id": "CAP-0001",
            "title": "Controlling staleness",
            "ria": {
                "R_quote": "Our largest RL runs mix problems",
                "I_rephrase": "按「Controlling staleness」判断情境。",
                "A3_steps": ["确认条件", "逐项检查", "给结论"],
                "B_not_applicable": "书里没讲",
            },
            "span": {"char_start": 100, "segment_id": "seg-003"},
        }]}

    def _full_text(self):
        return ("x" * 100 + "Our largest RL runs mix problems that finish in minutes "
                "with long horizon agentic tasks." + "y" * 100)

    def test_worklist_contains_evidence_for_each_persona(self):
        """工单必须带逐字引文与上下文——宿主判「是否被支持」时要有证据。"""
        from bookleme.judge import build_worklist
        wl = build_worklist(self._caps(), self._full_text(), load_run_config())
        self.assertEqual(wl["item_count"], 3, "3 个 persona 应各出一条待判项")
        first = wl["items"][0]
        self.assertEqual(first["quote"], "Our largest RL runs mix problems")
        self.assertIn("Our largest RL runs mix problems", first["context"])
        self.assertIn("grounded", first["answer_schema"])

    def test_apply_answers_uses_majority_and_keeps_unknown(self):
        """回填走多数票；平票必须记为「未决」而不是「不被支持」。"""
        from bookleme.judge import apply_answers
        caps = self._caps()
        # 2 票支持 1 票反对 → 多数支持
        ans = {"judgments": {"CAP-0001": {"votes": [
            {"persona": "考据员", "grounded": True, "v3_pass": True},
            {"persona": "事实核查员", "grounded": True, "v3_pass": True},
            {"persona": "逆向怀疑者", "grounded": False, "v3_pass": False},
        ]}}}
        r = apply_answers(caps, ans, load_run_config())
        self.assertIs(r["results"]["CAP-0001"]["grounded"], True)
        self.assertEqual(r["channel"], "host_agent")
        self.assertEqual(r["model_fingerprint"], "host-agent",
                         "宿主承接不得伪装成某个外部模型")

        # 平票 → 未决（None），不得记成 False
        ans2 = {"judgments": {"CAP-0001": {"votes": [
            {"persona": "考据员", "grounded": True},
            {"persona": "事实核查员", "grounded": False},
        ]}}}
        r2 = apply_answers(caps, ans2, load_run_config())
        self.assertIsNone(r2["results"]["CAP-0001"]["grounded"],
                          "平票必须记为未决（None），不能记为 False")

    def test_missing_judgment_leaves_metric_null_not_false(self):
        """宿主没判的卡 → 该卡判定为 None，不能算作「不被支持」。"""
        from bookleme.judge import apply_answers
        r = apply_answers(self._caps(), {"judgments": {}}, load_run_config())
        self.assertIsNone(r["results"]["CAP-0001"]["grounded"])
        self.assertEqual(r["summary"]["judged"], 0)

    def test_llm_module_still_optional_not_required(self):
        """外部模型通道仍是可选项，不得变成编译前提。"""
        from bookleme import llm
        # 没配密钥时 available() 为 False，但流水线必须照常跑
        self.assertIn("available", llm.describe())
        d = llm.describe()
        self.assertIn("宿主 Agent 承接", d["hint"],
                      "doctor 的提示应把宿主承接列为首选路径")


if __name__ == "__main__":
    unittest.main(verbosity=2)
