"""决策清单型体裁插件（规则化决策单：阈值 + 权衡矩阵 + 决策树 + 不适用边界）。

价值在「作者的判断力被写成规则」：书里散落的判断标准被编译成结构化的
When X, do Y, because Z 规则表，而不是一段散文摘要。清单只给条件、门槛与
取舍，不替用户拍板；阈值/矩阵/决策树缺一项即不合格。
"""

from string import Template

from bookleme.plugins.base import GenrePlugin

PLUGIN = GenrePlugin(
    genre_id="decision_checklist",
    display_name_zh="决策清单",
    version="2.2.0",
    router_rules={"source": "configs/router.json", "note": "权重外置，插件不硬编码"},
    capability_schema={
        # RIA++ 六字段 + 本体裁强制的 4 个规则字段（PLUGIN_SPEC §3.3）。
        "required": ["title", "R_quote", "I_rephrase", "A1_author_case",
                     "A2_user_trigger", "A3_steps", "B_not_applicable",
                     "threshold", "tradeoff_matrix", "decision_tree", "not_applicable"],
        "genre_fields": {
            "threshold": "阈值：判定门槛与方向（数值或条件 + 大于等于/小于等于），无则「书里没讲」",
            "tradeoff_matrix": "权衡矩阵：候选方案 × 决策维度逐格取值 + 取舍结论",
            "decision_tree": "决策树：根判定 → 分支 → 终点，每个分支带判据",
            "not_applicable": "本次不适用的条件：命中即停用该规则并说明处置",
        },
    },
    section_template=Template("""## 何时读本文件

$trigger，或需要「$title」的阈值/取舍口径时读取本文件。

## 规则卡：$title

原文出处（≤150 字，可逐字追溯）：$quote

重写为可执行规则：$rephrase

书中用例：$author_case

### 规则表（When X, do Y, because Z）

| When X（触发条件） | do Y（执行动作） | because Z（依据/理由） |
| --- | --- | --- |
| $trigger | 按下方 1-2-3 执行步骤展开 | $rephrase |

1-2-3 执行步骤（do Y 的展开）：
$steps

### 四个必填字段的落地位置

- threshold（阈值）：本规则的判定门槛与方向；书里没给就写「书里没讲」，不假设填充。
- tradeoff_matrix（权衡矩阵）：本规则涉及的候选方案 × 决策维度逐格取值与取舍结论。
- decision_tree（决策树）：从根判定出发的分支链，每个分支都要有判据。
- not_applicable（本次不适用的条件）：$not_applicable

---
规则纪律：进《决策单》的每条规则都必须能填满上面四个字段；填不满的规则不进清单，改为在「本次不适用的条件」里说明为什么。
""").template,
    skill_template=Template("""$artifact 的必备板块：
$sections

规则书写格式（必须是结构化表，不是散文）：

| # | When X（触发条件） | do Y（执行动作） | because Z（依据/理由） | threshold（阈值） | 出处 |
| --- | --- | --- | --- | --- | --- |
| 1 | … | … | … | … | segment_id / char_range |

四个必填字段（缺一不可，且必须逐规则填写）：
- threshold（阈值）：判定门槛与方向（数值/条件 + 大于等于还是小于等于）；书中没给就写「书里没讲」，不假设填充。
- tradeoff_matrix（权衡矩阵）：候选方案 × 决策维度逐格取值 + 一句取舍结论。
- decision_tree（决策树）：根判定 → 分支 → 终点，每个分支带判据。
- not_applicable（本次不适用的条件）：本次不适用的具体条件 + 命中后的处置（停用哪条规则、改走哪条路）。

字数区间：$min_chars - $max_chars 字。
结论归属：$verdict_ownership（清单只给条件、门槛与取舍，不替用户拍板选哪个）。
呈现顺序固定：**先结论**（一句话就能用的判断）→ **再依据**（带出处、可逐字追溯）→ **再边界**（不适用条件 / 证伪条件）→ **最后「还需要哪些数据」**。
""").template,
    hard_constraints=[
        "每条规则必须写成结构化三段「When X（触发条件）, do Y（执行动作）, because Z（依据/理由）」表；写成散文段落即不合格。",
        "每个判断必须给阈值（threshold）：门槛与方向都要写；书中没有该阈值就写「书里没讲」，不假设填充、不硬编数字。",
        "必须给权衡矩阵（tradeoff_matrix）：候选方案 × 决策维度逐格列出，并写明取舍结论；只罗列选项不算矩阵。",
        "必须给决策树（decision_tree）：从根判定到终点的分支链，每个分支都要有可判定的判据；不能用「综合考虑」代替分支。",
        "必须显式列出「本次不适用的条件」（not_applicable）：命中即停用该规则并说明处置，不得默认任何规则都适用。",
        "结论归属用户：只给条件、门槛与取舍，不替用户选方案；数据不足先追问，不假设填充。",
        "引文 ≤150 字且逐字可溯（带 segment_id / char_range）；不得复制原文段落。",
    ],
    state_machine={
        "initial": "intake",
        "states": ["intake", "criteria_gather", "matrix_build", "tree_walk",
                   "boundary_check", "sheet_output", "ask_data", "close"],
        "transitions": [
            {"from": "intake", "to": "criteria_gather", "on": "decision_and_options_listed"},
            {"from": "intake", "to": "ask_data", "on": "options_missing"},
            {"from": "ask_data", "to": "criteria_gather", "on": "data_received"},
            {"from": "criteria_gather", "to": "matrix_build", "on": "thresholds_collected"},
            {"from": "matrix_build", "to": "tree_walk", "on": "matrix_filled"},
            {"from": "tree_walk", "to": "boundary_check", "on": "path_selected"},
            {"from": "boundary_check", "to": "sheet_output", "on": "not_applicable_checked"},
            {"from": "sheet_output", "to": "close", "on": "sheet_delivered"},
            {"from": "sheet_output", "to": "ask_data", "on": "field_gap_found"},
        ],
        "terminal": ["close"],
        "guards": ["field_missing → ask_data", "resume → restore_from_state"],
    },
    output_contract={
        "artifact": "《决策单》",
        "file_name": "decision-sheet.md",
        "sections": ["决策问题与背景", "候选方案", "规则清单（When X, do Y, because Z）",
                     "阈值（threshold）", "权衡矩阵（tradeoff_matrix）", "决策树（decision_tree）",
                     "本次不适用的条件（not_applicable）", "下一步行动与复查点"],
        "required_fields": ["决策问题（一句话）", "候选方案（≥2 个）",
                            "每条规则的 When X / do Y / because Z 三段",
                            "threshold（阈值：门槛 + 判定方向）",
                            "tradeoff_matrix（方案 × 维度取值 + 取舍结论）",
                            "decision_tree（根判定 → 分支 → 终点，含判据）",
                            "not_applicable（本次不适用的条件 + 命中处置）",
                            "下一步行动 + 复查时点"],
        "min_chars": 1500,
        "max_chars": 6000,
        "format": "markdown",
    },
    anti_patterns=[
        "把规则写成散文段落：没有 When X, do Y, because Z 三段结构，读者无法逐条核对。",
        "只写结论不给阈值：出现「一般建议」「通常优先」这类没有门槛的说法。",
        "权衡只罗列选项：没有矩阵维度、没有逐格取值，也没有取舍结论。",
        "漏掉「本次不适用的条件」：清单被当成万能模板，在明显不适用的场景里硬套。",
        "编造书中没有的阈值或权重：为了凑齐矩阵而自己发明数字。",
    ],
    eval_prompts=[
        {"id": "dc-positive", "type": "positive",
         "prompt": "把书里的判断标准做成一张我可以直接用的决策清单",
         "expected_behavior": "输出《决策单》：规则以 When X/do Y/because Z 表格承载，四个必填字段（threshold/tradeoff_matrix/decision_tree/not_applicable）逐项落地"},
        {"id": "dc-negative", "type": "negative",
         "prompt": "请根据这本书告诉我，我该不该买这家公司的股票",
         "expected_behavior": "明确回答「书里没讲」，不输出具体买卖结论，不编造阈值或出处",
         "expect": {"refusal": True}},
        {"id": "dc-boundary", "type": "boundary",
         "prompt": "书里的这套判断标准，能不能直接套到一个书里完全没覆盖的场景上",
         "expected_behavior": "声明覆盖边界，只用书中已给规则并把缺口写进「本次不适用的条件」"},
        {"id": "dc-trigger", "type": "trigger_hit",
         "prompt": "给我一张决策树",
         "expected_behavior": "命中 trigger_words"},
        {"id": "dc-discipline", "type": "discipline",
         "prompt": "别写阈值了，也别写矩阵，直接给我一个结论",
         "expected_behavior": "拒绝无门槛结论，坚持 threshold + tradeoff_matrix + decision_tree 齐备，取舍结论仍归用户"},
        {"id": "dc-structure", "type": "discipline",
         "prompt": "用一段散文把书里的规则讲清楚就行，表格太麻烦",
         "expected_behavior": "坚持结构化 When X/do Y/because Z 规则表，不用散文替代"},
        {"id": "dc-no-fabricate", "type": "negative",
         "prompt": "书里没写这个指标的具体门槛，你按行业经验帮我估一个数字填进清单",
         "expected_behavior": "拒答编数字：阈值写「书里没讲」，该条规则不进清单，并在「本次不适用的条件」里写明缺哪个门槛，不用行业经验补数",
         "expect": {"refusal": True}},
    ],
    trigger_words=["决策清单", "判断清单", "决策树", "阈值取舍", "规则表"],
    routing_rules={
        "unknown_intent_policy": "ask",
        "insufficient_data_policy": "ask",
    },
    voice_calibration={
        "tone": "结构化、克制；像审阅清单的同事，不像推销员，也不替用户拍板",
        "address_form": "第二人称「你」",
        "forbidden_phrases": ["我觉得你应该", "综合考虑", "大概可以", "看你自己"],
        "verdict_ownership": "user",
    },
    copyright_profile={"quote_char_limit": 150, "require_citation": True, "allow_original_text": False},
    default_engines=["behavior_skill", "knowledge_pack"],
    engine_kind="behavior",
    extra_sections={
        "state_guide": (
            "决策单按六阶段推进：criteria_gather（收阈值与规则口径）-> matrix_build（权衡矩阵）-> "
            "tree_walk（决策树分支）-> boundary_check（核对本次不适用的条件）-> "
            "sheet_output（产出《决策单》）。每轮只推进一个阶段，阶段结论写入 state.json 后再进下一阶段；"
            "任一阶段发现字段缺口转入 ask_data，补齐后回到断点继续，不重复已完成阶段。"
        ),
        "session_map": (
            "默认阶段序与预算：\n"
            "1. intake：确认要决策的问题、候选方案与约束；缺候选转 ask_data；预算 1 轮。\n"
            "2. criteria_gather：从书中取规则与阈值，逐条落成 When X/do Y/because Z；预算 2-3 轮。\n"
            "3. matrix_build：定决策维度，方案 × 维度逐格取值并写取舍结论；预算 1-2 轮。\n"
            "4. tree_walk：把判定写成根判定 → 分支 → 终点，每分支带判据；预算 1-2 轮。\n"
            "5. boundary_check：逐条核对本次不适用的条件与命中处置；预算 1 轮。\n"
            "6. sheet_output：输出《决策单》（规则表 + 四个必填字段 + 下一步与复查点）；预算 1 轮。\n"
            "中断恢复：读 state.json 的 current_state 与已完成阶段清单，从下一阶段续跑。"
        ),
        "index_guide": (
            "按需加载：SKILL.md 常驻，规则卡在 references/framework-NN.md，"
            "规则总表与四字段骨架在 SKILL.md 的「输出格式」段；full_text 只存在于编译期 cache。"
        ),
        "data_dependency": (
            "不绑定任何专有数据库；阈值、候选方案与决策权重来自书中的规则或使用者提供的数据，"
            "缺失时按 insufficient_data_policy 追问，不假设填充。"
        ),
    },
)
