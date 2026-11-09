# BookLeme 体裁插件规范（M1 设计冻结）

> **M2 实现口径（以代码为准，2026-11-08）**：本文件描述设计目标；实际实现在 `$ROOT/bookleme/`。共享中间 IR 在 `cache/<book_sha256前12>/`，`out/<run_id>/` 只放本次产物与报告；`router_result.json`、`provenance_manifest.json` 按 run 隔离。完整差异见 `docs/ARCHITECTURE.md` 的「M2 实现口径校正」表。文中凡提「可插拔 LLM 接口」，一律按统一口径理解：**设计上预留为可插拔接口，本批代码未实现该接口文件，留待后续批次接入**（`bookleme/llm/client.py` 与 `CapabilityExtractor` Protocol 本批均不存在，只有 `bookleme/llm/__init__.py` 的 `LLM_AVAILABLE = False` 占位）。

> 状态：M1 设计冻结。插件是「可插拔体裁」的唯一扩展点：**新增体裁只写一个 Python 文件，零改核心**。
> 前缀 `$ROOT = $ROOT`。
> 本机零第三方依赖：插件模板用**标准库字符串模板**（`string.Template` / `str.format` 风格），**不使用 Jinja2**；插件加载用标准库 `importlib`；`bookleme plugin validate` 由标准库 `unittest` 驱动的确定性检查构成。

---

## 1. 文件位置与 Protocol

| 层级 | 路径（绝对路径） |
|---|---|
| 内置 | `$ROOT/bookleme/plugins/builtin/<genre_id>.py` |
| 用户 | `$ROOT/bookleme/plugins/user/<genre_id>.py` |
| 外部 | `--plugin-dir <dir>` / `BOOKLEME_PLUGIN_DIR` 指向目录下的 `<genre_id>.py` |

每个文件定义 `PLUGIN = GenrePlugin(...)`（实际为 `bookleme/plugins/base.py` 的 dataclass；文档沿用 Protocol 一词指契约）：**16 个必填字段**（对象属性）+ **2 个方法** `render(ctx)` / `validate(ctx)`。`ctx` 为渲染上下文（capabilities / claim_ledger / book 元数据 / slug / `output_contract` 解析结果）。

---

## 2. 16 个必填字段完整表

`bookleme plugin validate` 逐项硬校验，**缺一即失败**（退出码非 0，不进入 S6）。

| # | 字段名 | 类型 | 约束 | 缺失 / 违规后果 |
|---|---|---|---|---|
| 1 | `genre_id` | str | **最终裁决**：`^[a-z0-9][a-z0-9_-]*$`（允许下划线），且**与插件文件名严格同名**（`coach_dialogue` ↔ `coach_dialogue.py`）。原因：`configs/router.json` 的体裁键使用下划线，插件 id 必须与之匹配才能被 S3 评分命中。生成的 `SKILL.md` frontmatter `name` 仍严格 `^[a-z0-9-]+$`（如 `book-a4add8d6-bs`），由渲染层保证，二者职责不同 | 校验失败：无法定位 / 去重，`validate` 直接 reject |
| 2 | `display_name_zh` | str | 非空中文显示名；用于真源目录「中文显示名（english-kebab）」全角括号 | 校验失败：S8 无法生成目标目录名 |
| 3 | `version` | str | 语义化版本（如 `1.0.0`）；**仅存插件对象，绝不写进 SKILL.md frontmatter**（`quick_validate.py` 白名单不含 `version`，出现即 `Unexpected key(s)`） | 缺失：无法版本化 diff、`baseline.json` 无法绑定 `plugin_hash`；误写进 frontmatter：S7 `quick_validate` 失败 |
| 4 | `router_rules` | object | 引用 `$ROOT/configs/router.json` 中本体裁的权重 / 阈值 / prior / hard_gate_bonus；键须存在于 `router.json`（无专属节时回退 `default`） | 缺失：S3 无该体裁评分规则 |
| 5 | `capability_schema` | object | 声明本插件对 `capabilities.json` 每条 capability 的**额外必填字段**（见第 3 节各插件） | 缺失：S4 产出无法按体裁校验，S5 无法判定 `rejected` |
| 6 | `section_template` | str | **标准库字符串模板**（非 Jinja2），段级 / 章节级渲染 | 缺失：S6 无段模板，渲染异常 → abort |
| 7 | `skill_template` | str | 标准库字符串模板，`SKILL.md` 五段式：`## 核心定位 / ## 触发场景 / ## 工作流(3–8 步) / ## 输出格式 / ## Gotchas(≥4)`，章节间 `---`，≤500 行 | 缺失 / 不合规：`validate/lint.py` 失败 |
| 8 | `hard_constraints` | list[str] | **≥4 条**；每条为可断言的硬约束 | 缺失或 <4：`validate` 失败 |
| 9 | `state_machine` | object | 含 `states[] / transitions[] / initial / terminal[]`；**behavior 引擎插件必填**，须通过**可达性检查**（见 2.1）；纯 knowledge 插件字段须存在、可置 `null` | 缺失：`validate` 失败；不可达：`validate` 失败 |
| 10 | `output_contract` | object | 决定产物目录结构与文件清单（**不是固定 5 文件**）；须声明 `files[]`（相对路径 + 生成规则） | 缺失：S6 无产物清单；硬验收清单第 8 条失败 |
| 11 | `anti_patterns` | list[str] | 反模式清单，≥1 条；首条须对应本插件最典型失败模式 | 缺失：`validate` 失败 |
| 12 | `eval_prompts` | list[object] | **必须含 ≥1 个 `type: "negative"`** 的条目（书中未回答 / 应拒答 / 边界）；结构 `{id, type: positive\|negative\|boundary, prompt, expect}` | 无 negative：`validate` 失败；S7 负例冒烟无法覆盖 |
| 13 | `trigger_words` | list[str] | **3–5 个中文词，硬断言**（`len()` 实测命中数 `3 ≤ n ≤ 5`）；用于 description 生成与 `quick_validate` 的 description 断言 | 越界或含非中文词：`validate` 失败 / description 硬断言失败 |
| 14 | `routing_rules` | object | 必须含 `unknown_intent_policy` 与 `insufficient_data_policy: "ask"`（先追问、不假设填充） | 缺失或 `insufficient_data_policy != "ask"`：`validate` 失败 |
| 15 | `voice_calibration` | object | 补齐上游「有概念无字段」缺口，子字段：`tone` / `address_form` / `forbidden_phrases[]` / `verdict_ownership`（`user` \| `evidence_bound`） | 缺失任一子字段：`validate` 失败 |
| 16 | `copyright_profile` | object | `quote_char_limit ≤ 150`（int）、`allow_original_text: false`（bool **严格 false**） | `quote_char_limit > 150` 或 `allow_original_text !== false`：`validate` 失败，S5 / S7 版权门拒绝 |

### 2.1 关键硬断言细则

- **`trigger_words` 3–5 中文词**：用 `len()` 实测命中数，模板「当<t1>、<t2>、<t3>时使用……」由 `$ROOT/bookleme/render/description.py` 确定性生成；触发词取自 `A2_user_trigger` 聚类 + 插件 `trigger_words`；同时约束 `len(description) ≤ 1024`、无 `<` / `>`、不以 `[TODO:` 开头。
- **`state_machine` 可达性检查**：从 `initial` 出发做图遍历，要求 ① 所有 `states[]` 中非终态节点**均可达**；② 存在至少一条从 `initial` 到某个 `terminal` 的路径；③ 每条 `transitions[]` 的 `from` / `to` 均在 `states[]` 内；④ 无孤立状态。任一条不满足 → `validate` 失败。
- **`eval_prompts` ≥1 negative**：negative 条目须声明 `expect.refusal == true`（必须答「书里没讲」且不得编造出处），S7 冒烟负例 100% 拒答是硬门。
- **`voice_calibration.verdict_ownership`**：`user` = 结论归用户（教练型）；`evidence_bound` = 结论必须绑定证据并给出证伪条件（分析型）。

---

## 3. 4 个内置插件骨架要点

### 3.1 `coach_dialogue`（教练型 → `[behavior_skill]`）

- **一问一答状态机**：`opening → ask_q → await_answer → brief_reflect → next_q → … → blueprint → close`；含 `low_mood → skip_reverse`（低谷跳过反向推演）与 `resume → restore`（可中断续聊）分支。`initial = opening`，`terminal = [close]`。
- **结论归用户**：`voice_calibration.verdict_ownership = "user"`；`hard_constraints` 含「每轮只问一题、主问题 6–9 个、结论归用户、不评判不替他决定、可中断续聊」。
- `output_contract`：《个人人生设计蓝图》7 板块 8000–12000 字；`anti_patterns` 首条「一次多问 / 说教 / 低谷仍做反向推演」。
- 运行期状态由 `scripts/state_io.py` 写调用方传入的会话目录下 `state.json`（写前读 + session 级文件锁 + `resume`），技能包内只放 `state/schema.json`；**本批未产生会话数据**，`$ROOT/out/sessions/<slug>/<session_id>/` 为 M1 设计占位（见 ARCHITECTURE.md「M2 实现口径校正」）。

### 3.2 `professional_analysis`（分析型 → `[behavior_skill, knowledge_pack]`）

- **三阶段流水线**：① 叙事先行倒算 L/E3 → ② 三表验证「存在 > 事实 > 意见」+ 8 主题红旗 + A / 港 / 美口径 → ③ 观点裁决。
- **证伪条件 + 证据绑定**：`capability_schema` 强制**每条结论硬必填 `falsification_condition`**（「若……则本判断作废」）与 `evidence_binding`（溯源到发言人 / 报表科目）；`voice_calibration.verdict_ownership = "evidence_bound"`。
- `anti_patterns` 首条即「符合预期，仍需观察」和稀泥，另含「无口径表」「结论不绑证据」「无数据硬编」。
- `output_contract`：约 1.3 万字 + 风险分级 + 尾部强制「还需要哪些数据」；`routing_rules.insufficient_data_policy = "ask"`（无专有数据时先追问，不假设填充）；`data_adapters/` 可插拔。

### 3.3 `decision_checklist`（清单型 → `[behavior_skill, knowledge_pack]`）

- `capability_schema` 强制 4 字段：`threshold` / `tradeoff_matrix` / `decision_tree` / `not_applicable`。
- 规则写成 `When X, do Y, because Z` **结构化表**（不是散文），装作者判断力。
- `output_contract`：《决策单》含「本次不适用的条件」（`not_applicable` 落地）。

### 3.4 `knowledge_reference`（参考型 → `[knowledge_pack]`）

- Topic Index 路由表；`SKILL.md < 4000 token`；`references/chNN-*.md` 每片 800–3000 token，**文件头写「何时读本文件」**；`references/` 用相对路径。
- `hard_constraints` 含「书中未回答必须答『书里没讲』」；`anti_patterns` 含「无出处断言」「把 `full_text.txt` 打进产物」。
- 产物：`SKILL.md` + `references/{topic-index.md, chNN-*.md, glossary.md, patterns.md, cheatsheet.md, provenance.md}`。

---

## 4. 加载、安全与校验

### 4.1 加载优先级

```
--plugin-dir / BOOKLEME_PLUGIN_DIR   >   $ROOT/bookleme/plugins/user/   >   $ROOT/bookleme/plugins/builtin/
```

- 同 `genre_id` **高层覆盖低层**，被屏蔽的低层路径记入 `$ROOT/out/<run_id>/plugin_resolution.json` 的 `diagnostics`（`plugin_scan.json` 为 M4 规划，本批未生成）。
- 用标准库 `importlib.util.spec_from_file_location` 加载；**禁止** `eval` / `exec` 加载未扫描文件。

### 4.2 6 类安全正则（skill-vetter，加载前扫描）

加载前对插件源文件跑 6 类正则扫描，`Critical` / `High` 命中即**拒绝加载**并留痕：

| 类别 | 检测目标 |
|---|---|
| 1 外部 URL | 硬编码 `http(s)://` 外联地址 |
| 2 敏感路径 | `~/.ssh`、`/etc/passwd`、凭证目录等绝对路径访问 |
| 3 凭证 | API key / token / 私钥字面量模式 |
| 4 动态执行 | `eval(` / `exec(` / `os.system` / `subprocess` 未声明调用 |
| 5 混淆 | base64 大块 / 十六进制串 / 动态属性拼接绕过 |
| 6 数据外传 | 网络发送 / 写工作区外路径 / 遥测上报 |

扫描结果本批直接决定加载 / 拒绝，并记入 `$ROOT/out/<run_id>/plugin_resolution.json`；`plugin_scan.json` 为 M4 规划，本批未生成。

### 4.3 `bookleme plugin validate` 检查项

1. 16 个必填字段**全部存在**（缺一即失败）；
2. 各字段类型与 2.1 约束逐项校验（`genre_id` 正则 `^[a-z0-9][a-z0-9_-]*$` + 与文件名严格同名、`hard_constraints ≥ 4`、`quote_char_limit ≤ 150`、`allow_original_text === false` 等）；
3. `state_machine` 可达性（2.1 四条）；
4. `eval_prompts` 含 ≥1 negative；
5. `trigger_words` 3–5 中文词；
6. `routing_rules.insufficient_data_policy == "ask"`、`unknown_intent_policy` 存在；
7. `voice_calibration` 四子字段齐、`verdict_ownership` 合法；
8. `render(ctx)` 产出能过 `quick_validate.py`（frontmatter 顶层键 ⊆ `{name, description, license, allowed-tools, metadata}`，无 `version` / `tags` / `author` / `homepage` / `argument-hint`；`name` 匹配 `^[a-z0-9-]+$`、≤64、无首尾连字符、无 `--`；`description` ≤1024、无 `<` / `>`、不以 `[TODO:` 开头；正文无 `[TODO: ...]` 残留）；
9. `validate(ctx)` 可调用且返回结构化结果；
10. 6 类安全正则无 Critical / High 命中。

---

## 5. 新增体裁只需写一个文件（最小示例，字段清单层面，非 Python 代码）

以新增体裁 `socratic_seminar`（苏格拉底研讨型）为例：只需在 `$ROOT/bookleme/plugins/user/socratic_seminar.py`（或 `--plugin-dir` 指定目录）**写一个文件**，零改核心。按下列字段清单填齐即可：

| 字段 | 本例填法（清单，非代码） |
|---|---|
| `genre_id` | `"socratic_seminar"`（与 `router.json` 体裁键一致，且与文件名 `socratic_seminar.py` 严格同名） |
| `display_name_zh` | `"苏格拉底研讨"` |
| `version` | `"1.0.0"`（仅对象内，不进 frontmatter） |
| `router_rules` | 引用 `$ROOT/configs/router.json` 的 `default` 权重节即可运行；如需专属权重，可增一个配置节（配置数据，非核心代码） |
| `capability_schema` | 额外必填 `seed_question` / `counterexample` / `followup_ladder[]` |
| `section_template` | 标准库字符串模板：研讨段 = 引子问题 + 反例 + 追问阶梯 |
| `skill_template` | SKILL.md 五段式模板 |
| `hard_constraints` | ≥4：每轮只追一问 / 不替用户下结论 / 反例必须来自书中 / 可中断续聊 |
| `state_machine` | `pose → await → probe → reframe → … → synthesis → close`，含可达性 |
| `output_contract` | `files[]`：`SKILL.md`、`references/framework-*.md`、`assets/session-template.md` |
| `anti_patterns` | 首条「一次给结论」/「无书中反例」 |
| `eval_prompts` | ≥1 positive + **≥1 negative**（书中未回答须答「书里没讲」） |
| `trigger_words` | `["把书变研讨", "追问式读书", "苏格拉底提问"]`（3 个中文词） |
| `routing_rules` | `unknown_intent_policy`、`insufficient_data_policy: "ask"` |
| `voice_calibration` | `tone` / `address_form` / `forbidden_phrases` / `verdict_ownership: "user"` |
| `copyright_profile` | `quote_char_limit: 150`、`allow_original_text: false` |
| `render(ctx)` / `validate(ctx)` | 两个 Protocol 方法 |

> 说明：唯一必须新增的**代码文件**就是这个插件文件；路由权重属外置配置数据，可选增补，不新增配置节时回退 `default` 权重仍能跑通。不新增、不修改任何核心模块文件——这就是「新增体裁 = 新增一个插件文件」的边界。
