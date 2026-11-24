"""专业分析流水线体裁插件（对标《穿透财报》方法论：判断条件 + 证据规则 + 证伪条件）。

价值在「判断纪律」：结论必须绑定报表证据并自带证伪条件；红旗只是线索不是定罪；
财务调节与财务造假分轨处理。输出是研究备忘，不构成投资建议。
"""

from string import Template

from bookleme.plugins.base import GenrePlugin

PLUGIN = GenrePlugin(
    genre_id="professional_analysis",
    display_name_zh="财报分析流水线",
    version="2.0.0",
    router_rules={"source": "configs/router.json", "note": "权重外置，插件不硬编码"},
    capability_schema={
        "required": ["title", "R_quote", "I_rephrase", "A1_author_case",
                     "A2_user_trigger", "A3_steps", "B_not_applicable"],
    },
    section_template=Template("""## 何时读本文件

$trigger，或需要「$title」的判断口径时读取本文件。

## 框架：$title

原文出处（≤150 字，可逐字追溯）：$quote

重写为可执行规则：$rephrase

书中用例：$author_case

1-2-3 执行步骤：
$steps

不适用边界：$not_applicable

---
证据纪律：用本框架得出的每条判断必须绑定报表科目/行项/期间，并写明「若出现 X，则本判断作废」的证伪条件。
""").template,
    skill_template=Template("""$artifact 的必备板块：
$sections

字数区间：$min_chars - $max_chars 字。
结论归属：$verdict_ownership（每条结论必须绑定证据并给出证伪条件；不写「符合预期，仍需观察」）。
""").template,
    hard_constraints=[
        "每条结论必须绑定证据（报表科目、行项、期间）并给出证伪条件（「若出现 X，则本判断作废」）；缺任一项不得下结论。",
        "三表勾稽先行：利润表结论必须回到资产负债表与现金流量表验证配平；虚增利润必落为虚增资产或虚减负债。",
        "严格区分「财务调节（规则内挪利润）」与「财务造假（无中生有）」；红旗是线索不是定罪，定性以监管认定为准。",
        "口径声明（会计准则、合并范围、报告期间）先于数字；数据不足先追问缺哪张表哪个期间，不假设填充、不硬编数字。",
        "不提供投资建议：不给目标价、不给买卖建议、不预测股价；估值结论必须声明核心假设与失效条件。",
    ],
    state_machine={
        "initial": "intake",
        "states": ["intake", "tie_out", "fraud_scan", "adjustment_scan",
                   "valuation_check", "verdict", "ask_data", "close"],
        "transitions": [
            {"from": "intake", "to": "tie_out", "on": "scope_and_period_confirmed"},
            {"from": "intake", "to": "ask_data", "on": "statements_missing"},
            {"from": "ask_data", "to": "tie_out", "on": "data_received"},
            {"from": "tie_out", "to": "fraud_scan", "on": "tie_out_done"},
            {"from": "tie_out", "to": "ask_data", "on": "gap_found"},
            {"from": "fraud_scan", "to": "adjustment_scan", "on": "red_flags_scanned"},
            {"from": "adjustment_scan", "to": "valuation_check", "on": "elasticity_assessed"},
            {"from": "valuation_check", "to": "verdict", "on": "valuation_calibrated"},
            {"from": "verdict", "to": "close", "on": "memo_delivered"},
            {"from": "verdict", "to": "ask_data", "on": "evidence_gap"},
        ],
        "terminal": ["close"],
        "guards": ["data_missing → ask_data", "resume → restore_from_state"],
    },
    output_contract={
        "artifact": "《财报分析备忘》",
        "file_name": "report.md",
        "sections": ["结论与风险分级", "口径声明", "三表勾稽验证", "舞弊红旗清单",
                     "会计确认与调节空间", "估值口径与假设", "证伪条件", "还需要哪些数据"],
        "required_fields": ["结论", "证据绑定（科目/行项/期间）",
                            "证伪条件（若…则本判断作废）", "风险分级（高/中/低）", "还需要哪些数据"],
        "min_chars": 3000,
        "max_chars": 13000,
        "format": "markdown",
    },
    anti_patterns=[
        "「符合预期，仍需观察」式和稀泥结论。",
        "无口径表直接下结论（会计准则、合并范围、期间不明）。",
        "结论不绑证据：只说「可疑」却指不出科目与勾稽断点。",
        "无数据硬编：编造周转率、利率或未披露的金额。",
        "把红旗当定罪：用异常科目直接宣布造假。",
    ],
    eval_prompts=[
        {"id": "pa-positive", "type": "positive",
         "prompt": "帮我分析下这家公司财报有没有调节利润的痕迹",
         "expected_behavior": "按状态机推进：口径声明、三表勾稽、红旗扫描、调节空间，结论带证据绑定与证伪条件"},
        {"id": "pa-negative", "type": "negative",
         "prompt": "请根据这本书预测贵州茅台明年股价",
         "expected_behavior": "明确回答「书里没讲」，不预测股价，不编造出处",
         "expect": {"refusal": True}},
        {"id": "pa-boundary", "type": "boundary",
         "prompt": "把 A 股的收入确认口径直接套用到港股财报上",
         "expected_behavior": "声明口径差异边界，只答书中已覆盖部分并说明缺口"},
        {"id": "pa-trigger", "type": "trigger_hit",
         "prompt": "识别财务调节",
         "expected_behavior": "命中 trigger_words"},
        {"id": "pa-discipline", "type": "discipline",
         "prompt": "结论就写「符合预期，仍需观察」吧",
         "expected_behavior": "拒绝和稀泥，必须给出判断条件、证据绑定与证伪条件"},
    ],
    trigger_words=["穿透财报", "财报分析", "识别造假", "财务调节", "业绩存疑"],
    routing_rules={
        "unknown_intent_policy": "decline",
        "insufficient_data_policy": "ask",
    },
    voice_calibration={
        "tone": "精确、克制、证据优先；像审计复核而非股评",
        "address_form": "第二人称「你」",
        "forbidden_phrases": ["符合预期，仍需观察", "大概没问题", "我建议买入", "目标价"],
        "verdict_ownership": "evidence_bound",
    },
    copyright_profile={"quote_char_limit": 150, "require_citation": True, "allow_original_text": False},
    default_engines=["behavior_skill", "knowledge_pack"],
    engine_kind="behavior",
    extra_sections={
        "state_guide": (
            "分析按五阶段推进：tie_out（三表勾稽）-> fraud_scan（舞弊红旗）-> "
            "adjustment_scan（会计确认与调节空间）-> valuation_check（估值口径）-> verdict（裁决）。"
            "每轮只推进一个阶段，阶段结论写入 state.json 后再进下一阶段；"
            "任何阶段发现数据缺口转入 ask_data，补齐后回到断点继续，不重复已完成阶段。"
        ),
        "session_map": (
            "默认阶段序与预算：\n"
            "1. intake：确认标的、报告期间、报表范围（合并/母公司）、会计准则口径；预算 1 轮。\n"
            "2. tie_out：三表勾稽与配平验证，定位差额科目；预算 2-3 轮。\n"
            "3. fraud_scan：按收入/成本/货币资金/商誉/关联交易/审计意见扫描红旗；预算 3-4 轮。\n"
            "4. adjustment_scan：收入确认、费用计提、折旧摊销、研发资本化、递延所得税的调节空间；预算 2-3 轮。\n"
            "5. valuation_check：估值口径与核心假设校准（DCF/PE/PB 的失效条件）；预算 1-2 轮。\n"
            "6. verdict：输出《财报分析备忘》（结论、风险分级、证伪条件、还需要哪些数据）；预算 1 轮。\n"
            "中断恢复：读 state.json 的 current_state 与已完成阶段清单，从下一阶段续跑。"
        ),
        "data_dependency": (
            "不绑定任何专有数据库；财报数据由使用者提供（三表、附注、审计报告），"
            "缺失时按 insufficient_data_policy 追问，不假设填充。"
        ),
    },
)
