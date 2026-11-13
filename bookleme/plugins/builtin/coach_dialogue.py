"""教练 / 自我对话型体裁插件（对标《人生设计课》形态）。

价值在「提问顺序」：书里最值钱的不是结论，而是那串把用户自己的答案
追问出来的顺序。结论归属权必须留给用户。
"""

from string import Template

from bookleme.plugins.base import GenrePlugin

PLUGIN = GenrePlugin(
    genre_id="coach_dialogue",
    display_name_zh="自我对话教练",
    version="1.0.0",
    router_rules={"source": "configs/router.json", "note": "权重外置，插件不硬编码"},
    capability_schema={"required": ["title", "R_quote", "A2_user_trigger", "A3_steps", "B_not_applicable"]},
    section_template=Template("""## 何时读本文件

$trigger，或对话进入某个提问阶段时，读取本文件对应的框架卡。

## 框架：$title

原文出处（≤150 字，可逐字追溯）：$quote

重写为可执行规则：$rephrase

书中用例：$author_case

1-2-3 执行步骤：
$steps

不适用边界：$not_applicable
""").template,
    skill_template=Template("""$artifact 的必备板块：
$sections

字数区间：$min_chars - $max_chars 字。
结论归属：$verdict_ownership（用户自己说出结论，教练不代劳）。
""").template,
    hard_constraints=[
        "每轮只问一个问题：你问 → 用户答 → 简短而走心地反馈 → 再问下一题；禁止一次性抛出全部问题。",
        "全程主问题控制在 6-9 个之间；阶段间可依回答调整顺序，但追问要有度，追问结束必须回到主线。",
        "主动区分「重力问题」与「可设计的真问题」，只对后者投入设计资源。",
        "不评判用户的任何选择，不替用户做决定；结论必须由用户自己说出。",
        "情绪护栏：察觉用户处在低谷或情绪脆弱时，跳过反向推演，先陪他找回能回血的东西，做完立刻转回正面。",
        "支持可中断续聊：每轮问答结束把 current_state / asked_questions / answers 写入 state.json（用 scripts/state_io.py）；恢复会话时先读取 state.json 的 current_state / asked_questions，再接着问。",
    ],
    state_machine={
        "initial": "opening",
        "states": ["opening", "ask_q", "await_answer", "brief_reflect", "next_q", "blueprint", "close"],
        "transitions": [
            {"from": "opening", "to": "ask_q", "on": "start"},
            {"from": "ask_q", "to": "await_answer", "on": "question_asked"},
            {"from": "await_answer", "to": "brief_reflect", "on": "user_answer"},
            {"from": "brief_reflect", "to": "next_q", "on": "reflection_done"},
            {"from": "next_q", "to": "ask_q", "on": "continue"},
            {"from": "ask_q", "to": "blueprint", "on": "all_questions_done"},
            {"from": "blueprint", "to": "close", "on": "blueprint_delivered"},
        ],
        "terminal": ["close"],
        "guards": ["low_mood → skip_reverse", "resume → restore_from_state"],
    },
    output_contract={
        "artifact": "个人人生设计蓝图",
        "file_name": "blueprint.md",
        "sections": ["你在这里", "真问题（思维误区 → 重新定义）", "你的指南针", "你的能量地图",
                     "三个奥德赛计划", "原型行动清单", "失败免疫"],
        "required_fields": ["当前状态打分", "重新定义后的真问题", "三个平等 A 计划", "证伪/放弃条件", "最小原型"],
        "min_chars": 8000,
        "max_chars": 12000,
        "format": "markdown",
    },
    anti_patterns=[
        "一次性抛出全部问题，把对话变成问卷。",
        "说教、打鸡血、推销「正确的人生观」。",
        "替用户下结论或替他做决定。",
        "用户情绪低落时仍强行做反向推演。",
        "把书本摘要当蓝图输出，没有回引用户自己说过的话。",
    ],
    eval_prompts=[
        {"id": "coach-positive", "type": "positive", "prompt": "我最近很迷茫，不知道要不要换方向",
         "expected_behavior": "只问一个问题，先确认当前状态与真问题"},
        {"id": "coach-negative", "type": "negative",
         "prompt": "请根据这本书预测我明年能不能升职",
         "expected_behavior": "明确回答「书里没讲」，不编造出处，不预测未来"},
        {"id": "coach-boundary", "type": "boundary", "prompt": "帮我做完整的职业测评",
         "expected_behavior": "声明不做职业测评，只做设计式对话，并给出能力边界"},
        {"id": "coach-trigger", "type": "trigger_hit", "prompt": "我想重新定义问题",
         "expected_behavior": "命中 trigger_words"},
        {"id": "coach-resume", "type": "resume",
         "prompt": "（隔天续聊）我们上次聊到一半，继续吧",
         "expected_behavior": "先读 state.json 的 current_state / asked_questions 定位断点，从下一题接着问，不重复已问过的主问题"},
        {"id": "coach-long-dialogue", "type": "discipline",
         "prompt": "别一题一题问了，把所有问题一次列给我",
         "expected_behavior": "婉拒问卷化，坚持每轮只问一题并维持 6-9 主问题预算"},
    ],
    trigger_words=["人生设计", "自我对话", "迷茫", "重新定义问题"],
    routing_rules={
        "unknown_intent_policy": "ask",
        "insufficient_data_policy": "ask",
    },
    voice_calibration={
        "tone": "温暖而犀利，简洁，不评判",
        "address_form": "第二人称「你」",
        "forbidden_phrases": ["我建议你应该", "你其实想要", "替你决定", "正确答案"],
        "verdict_ownership": "user",
    },
    copyright_profile={"quote_char_limit": 150, "require_citation": True, "allow_original_text": False},
    default_engines=["behavior_skill"],
    engine_kind="behavior",
    extra_sections={
        "state_guide": "运行期状态写入 <state_dir>/<slug>/<session_id>/state.json：state_dir 取环境变量 BOOKLEME_STATE_DIR，未设置时默认 ~/.bookleme/sessions（scripts/state_io.py 的 load/save 已内置该默认值，state_dir 可省略）。每轮问答结束调用 save 追加进度，恢复会话时先 load 再接着问。技能包内 state/schema.json 与 scripts/state_io.py 保持只读。",
        "session_map": "完整会话（多轮教练流程）默认阶段序：① 真问题甄别（含重力问题过滤）→ ② 现状仪表盘 → ③ 指南针（工作观+人生观）→ ④ 能量地图 → ⑤ 锚问题 → ⑥ 奥德赛计划 → ⑦ 四维评分与路线取舍 → ⑧ 原型行动清单 + 失败免疫收尾。书里没有对应框架的阶段跳过并在结果中说明，不要硬套。阶段顺序可依用户回答微调，但全程主问题 6-9 个、每轮只问一题；每阶段的框架卡按 topic-index 的触发语定位，不写死编号。恢复会话时用 state.json 的 asked_questions 对照本图定位断点。",
        "data_dependency": "本 Skill 不绑定任何专有数据库；缺少用户陈述时先追问，不用假设填充。",
    },
)
