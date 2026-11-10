"""知识查阅型体裁插件（对标上游可查阅知识包，但产物由本插件契约决定）。"""

from string import Template

from bookleme.plugins.base import GenrePlugin

PLUGIN = GenrePlugin(
    genre_id="knowledge_reference",
    display_name_zh="框架速查",
    version="0.1.0",
    router_rules={"source": "configs/router.json", "note": "权重外置，插件不硬编码"},
    capability_schema={"required": ["title", "R_quote", "I_rephrase", "B_not_applicable"]},
    section_template=Template("""## 何时读本文件

当用户的问题命中「$trigger」或需要「$title」的原始出处时读取本文件；否则只读 SKILL.md 的路由表。

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

输出必须带出处；书中未涉及的问题必须写「书里没讲」。
""").template,
    hard_constraints=[
        "遇到书中未回答的问题，必须明确回答「书里没讲」并说明边界，不得编造出处。",
        "不得把整书文本塞进 SKILL.md；只在需要时按相对路径读取 references/ 下的分片。",
        "每条框架与断言必须带出处（segment_id + char_range），保留作者的精确命名。",
        "不得复制原文段落；单条引文 ≤150 字且可逐字追溯。",
        "回答要写「何时用 / 怎么用 / 什么时候不适用」，不写读书报告式摘要。",
    ],
    state_machine=None,
    output_contract={
        "artifact": "框架速查答复",
        "file_name": "answer.md",
        "sections": ["命中的框架", "带出处的规则", "执行步骤", "不适用边界", "出处清单"],
        "required_fields": ["框架名", "出处", "可执行步骤", "边界"],
        "min_chars": 300,
        "max_chars": 2000,
        "format": "markdown",
    },
    anti_patterns=[
        "无出处的断言。",
        "没有 Topic Index 路由表，导致每次都全量加载。",
        "把 full_text.txt 或 slices/ 打进产物包。",
        "把「书里没讲」的问题硬编一个答案。",
    ],
    eval_prompts=[
        {"id": "ref-positive", "type": "positive", "prompt": "这本书里 X 框架怎么用",
         "expected_behavior": "按 topic-index 路由到对应分片并给出带出处规则"},
        {"id": "ref-negative", "type": "negative", "prompt": "请讲讲这本书第 99 章的量子计算结论",
         "expected_behavior": "回答「书里没讲」，不编造章节与出处"},
        {"id": "ref-boundary", "type": "boundary", "prompt": "框架 A 在不适用场景里能用吗",
         "expected_behavior": "只答已覆盖部分并声明缺口"},
        {"id": "ref-trigger", "type": "trigger_hit", "prompt": "帮我查一下术语出处",
         "expected_behavior": "命中 trigger_words"},
    ],
    trigger_words=["查阅框架", "书中怎么讲", "术语出处", "章节速查"],
    routing_rules={
        "unknown_intent_policy": "decline",
        "insufficient_data_policy": "ask",
    },
    voice_calibration={
        "tone": "精确、克制、 practitioner voice",
        "address_form": "第二人称「你」",
        "forbidden_phrases": ["这本书解释了", "一般而言", "大概"],
        "verdict_ownership": "citation_bound",
    },
    copyright_profile={"quote_char_limit": 150, "require_citation": True, "allow_original_text": False},
    default_engines=["knowledge_pack"],
    engine_kind="knowledge",
    extra_sections={
        "index_guide": "Topic Index 是路由表：SKILL.md 常驻，references/ 按需加载，full_text 只存在于编译期 cache。",
        "data_dependency": "不绑定任何专有数据库；出处来自本地有权文件与标注可信度的公开资料。",
    },
)
