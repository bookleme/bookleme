# ADR-002：双引擎自动路由与「一套两出口」的 IR 分流点

- **状态**：Accepted（M0 设计冻结，2026-11-08）
- **决策者**：BookLeme 主代理（用户拍板方向 A/B，见计划第 0 节）/ general-purpose-1（起草本 ADR）
- **相关**：计划第 0、2、3、4、5、6、10 节；ADR-001（上游证据）；`docs/UPSTREAM_AUDIT.md`
- **依赖**：ADR-001 的采信结论（上游产出是「可查阅知识包」、无行为字段、无忠实度回验）
- **约束**：本 ADR 只冻结「为什么双引擎、在哪分流、如何路由」，不写核心源码；不导入任何上游代码。

---

## 1. 决策（Decision）

BookLeme 采用**双引擎自动路由**：

1. 一本书按体裁自动判断，可同时产出 **`knowledge_pack`（知识包）** 与 **`behavior_skill`（行为 Skill）**，也可由 `--engine` / `--genre` 人工指定（计划第 0 节方向 A）。
2. 两引擎**共享同一核心引擎与同一套中间产物（IR）**：`S0 Intake → S1 Extract → S2 Segment` 串行后，`S3 Router ‖ S4 Capabilities` 并行，二者共同汇入 `S5 Fidelity`，**只有 `S6 Render` 按引擎分流**；`S7 Validate → S8 Install → S9 Eval` 再合流（计划第 3 节 DAG）。
3. 既产出「本机可安装的 WorkBuddy Skill（写真源）」，又产出「可独立开源的 GitHub 项目（CLI/插件/评测/README/LICENSE/examples）」，共用同一核心引擎（方向 B「一套两出口」）。
4. 体裁插件是可插拔单文件；新增体裁只写一个插件文件，零改核心（方向 D）。

**分流点唯一性**：`S6` 是唯一按 `engine_targets` 分叉的 stage；`S1/S2/S4/S5` 的全部中间产物对所有引擎可见且只计算一次。这是「双引擎不重复读书」的**结构性保证**，而非约定。

---

## 2. 为什么做双引擎（问题背景）

### 2.1 上游只产出「可查阅的知识包」，不是「会运行的行为」

上游产物固定为 5 文件：`SKILL.md` + `chapters/` + `glossary.md` + `patterns.md` + `cheatsheet.md`（`SKILL.md:50`），其运行方式是「宿主按 Topic Index 路由到章文件、读后回答」（`SKILL.md:613`、`:880`）。这是**检索/查阅型知识包**：输入是「问题」，输出是「答案/引述」。

而计划第 1 节两个案例的本质是**行为型 Skill**：

| 案例 | 最值钱的东西 | 需要的结构 | 上游是否具备 |
|---|---|---|---|
| 《人生设计课》式 | **提问顺序**：角色 / 硬约束 / 4 阶段状态机 / 每轮只问一题 / 结论归用户 / 具名蓝图 / 情绪护栏 | `state_machine`、`hard_constraints`、`voice_calibration`、`output_contract`、可中断续聊的会话状态 | **否**。`SKILL.md:30-35` 把 Voice calibration 只写成散文概念；无状态机字段、无运行期状态落盘契约 |
| 《穿透财报》式 | **判断条件 + 证据规则 + 证伪条件**：叙事先行倒算 L/E3 → 三表验证「存在>事实>意见」+ 8 主题红旗 + A/港/美口径 → 观点裁决必须溯源到发言人并给「若…判断作废」；且绑定专有研报数据库 | 每条结论硬必填 `falsification_condition`、`data_adapters/`、`insufficient_data_policy`、`output_contract` 定量输出 | **否**。上游无输出契约、无数据适配器、无「无数据先追问」策略、无证伪字段 |

**本地一手证据**：
- `SKILL.md:871-881` Quality Rules 8 条全是**散文写作准则**（「Extract structure, not summaries」「Practitioner voice」「Never copy raw book text」），无一个可机器校验的硬字段。
- `SKILL.md:30-35` 把 frameworks / principles / techniques / anti-patterns / Voice calibration 列为「toolkit」概念，但没有 schema、没有 `plugin validate` 逐项硬校验。
- `AGENTS.md:7-12` 明确生成器是「`SKILL.md` 这份规格由 agent 执行」——即所有「行为」都靠宿主 LLM 读散文现场发挥，**不可单测、不可 diff、换模型漂移**（计划第 2 节差异化清单第 2 条）。
- 上游 `tools/validate_skill.py:213-291` 只校验 frontmatter/宿主规则，`tools/scan_generated_skill.py:2` 只是 advisory 安全扫描；**没有产物结构契约校验**（`docs/UPSTREAM_AUDIT.md §3`）。

### 2.2 两类产物的输出契约根本不同，无法用一套模板兼顾

| 维度 | `knowledge_pack` | `behavior_skill` |
|---|---|---|
| 运行方式 | 按需检索章节 → 回答 | 进入状态机 → 逐轮交互 → 产出具名文档 |
| 核心文件 | `SKILL.md` + `references/{topic-index,chNN-*,glossary,patterns,cheatsheet,provenance}.md` | `SKILL.md` + `references/framework-*.md` + `assets/blueprint-template.md` + `scripts/state_io.py` + `state/schema.json` + `evals/smoke.md`（计划第 7 节） |
| 状态 | 无（只读） | 运行期状态写工作区 `out/sessions/<slug>/<session_id>/state.json`（写前读 + 文件锁 + resume），技能包保持只读干净（计划第 7/13 节） |
| 硬必填字段 | Topic Index 路由表、`SKILL.md <4000 token`、每片「何时读」、书中未回答答「书里没讲」 | `state_machine`（可达性检查）、`output_contract`、`hard_constraints ≥4`、`voice_calibration`、`anti_patterns`、`eval_prompts ≥1 negative`、`falsification_condition` |
| 反模式 | 无出处断言 / 把 `full_text` 打进产物 | 一次多问 / 说教 / 低谷仍做反向推演（coach）；「符合预期，仍需观察」和稀泥 / 无口径表 / 无数据硬编（analysis） |

两者是**不同的编译目标**，强行合并会迫使模板里塞满 `if engine == ...` 条件分支，插件契约的「硬必填字段」也就无法作为硬门校验。

### 2.3 「一套两出口」要求共用核心

用户方向 B 要求：同一个核心引擎既服务本机 Skill 安装，又作为独立开源项目。若为每个引擎各建一条完整流水线，就会出现两套提取、两套分段、两套忠实度实现——既违反「共用同一核心引擎」，也使 `book_sha256` 为键的 IR / 幂等 / 反馈闭环（计划第 2 节第 7 条）无从谈起。

**结论**：双引擎是**编译目标层的分叉**，不是**数据层的分叉**。分叉必须尽可能晚、且必须唯一。

---

## 3. 为什么 `S3 ‖ S4` 且共享 `S1/S2/S4/S5` IR、只在 `S6` 分流

### 3.1 DAG（计划第 3 节）

```text
S0 Intake ─► S1 Extract ─► S2 Segment ─┬─► S3 Router ──────────┐
 (det)       (det,内并行)  (det+LLM消歧) │   (det+LLM 只读取证)    │
                                        └─► S4 Capabilities ─────┼─► S5 Fidelity ─► S6 Render ─► S7 Validate ─► S8 Install ─► S9 Eval
                                            (LLM, agent-swarm 并行) ┘   (det+judge)    (det+插件)      (det)         (det)      (det+LLM)
```

### 3.2 为什么 `S3` 与 `S4` 并行

- **两者都只消费 `S2` 的输出**（`segments.json` + `slices/`），互不依赖：S3 是「给这本书打体裁标签并选引擎」，S4 是「逐段抽取原子能力」。计划第 3 节原文：「**S3 与 S4 并行（都以 S2 为输入，S4 抽取是体裁无关的）**」。
- **S4 是体裁无关的**：`capabilities.json` 的 `capability_id / ria{R_quote,I_rephrase,A1,A2,A3,B} / span / claims / checks / confidence / status`（计划第 6 节）描述的是「书里有什么框架」，不是「这本书该做成知识包还是行为 Skill」。体裁信息只在 `engine_targets[]` / `genre_tags[]` 上作为标签，不参与抽取逻辑。
- **S4 是主力加速点**（agent-swarm 按段并行）；让它等 S3 完成只会串行化最贵的一段，无任何收益。

### 3.3 为什么共享 `S1/S2/S4/S5` 全部 IR

| 共享 stage | 产物 | 为什么不能按引擎各算一次 |
|---|---|---|
| S1 | `normalized/full_text.txt`、`char_map.json`、`toc.json`、`extraction_report.json` | 「不重复读书」的字面保证；逐字引文校验（S5）必须以**同一份** `full_text.txt` 为基准，`char_map.json` 是反查依据（计划第 6 节） |
| S2 | `segments.json` + `slices/seg-XXX.md` | S3 抽特征、S4 抽能力、S5 reviewer「必须读原始切片」都基于同一切片；两套切片会使 `router_evidence.json` 与 `claim_ledger.json` 的段号失去对应 |
| S4 | `capabilities.json` | 原子能力按框架拆分（计划第 6 节），是两引擎共同的知识源；`knowledge_pack` 把它渲染成 Topic Index + 章片，`behavior_skill` 把它渲染成状态机/硬约束/输出契约 |
| S5 | `claim_ledger.json`、`verification.json`、`fidelity_report.json`、`regen_queue.json` | 忠实度是**引擎无关**的硬门；若两引擎各跑一次 S5，会出现「同一条断言在 A 引擎通过、在 B 引擎被拒」的荒谬结果，且 `≤3 轮` 重生成（计划第 6 节）无法收敛 |

**结构性保证**：`state.json` 必须能证明 **S4 只跑一次**（计划第 11 节硬验收清单第 10 条「双引擎共享 S1/S2/S4/S5，state.json 证明 S4 只跑一次」）。

### 3.4 为什么只在 `S6` 分流

- `S6 Render` 是**唯一**把「抽象的原子能力」变成「具体文件树」的环节，天然依赖 `plugin.render()` 与 `plugin.output_contract`——这正是引擎差异所在。
- 分流前所有校验、引用、覆盖率、忠实度已经完成且通过；分流后再无跨引擎共享计算，`S7/S8/S9` 按产物目录分别跑即可（合流在报告层）。
- **晚分流的额外收益**：`--engine both` 时两引擎的产物来自同一份 `capabilities.json` / `claim_ledger.json`，天然一致、可 diff；不会出现「两本书」式的语义漂移。

### 3.5 与上游「五文件模板」的对照

| 上游 | BookLeme |
|---|---|
| 产物由 `SKILL.md` 散文模板固定为 5 文件（`SKILL.md:50`、`:431-553`） | 产物由 `plugin.output_contract` 决定，不是固定 5 文件（计划第 2 节第 4 条） |
| 生成器是巨型 prompt，不可单测/不可 diff/换模型漂移（`AGENTS.md:7-12`） | prompt 版本化 `llm/prompts/*.md`、路由权重外置、全部中间产物有 JSON Schema、`state.json` 记 `model_fingerprint`、CI 跑测试（计划第 2 节第 2 条） |
| 5 处强制停人（`SKILL.md:118/294/364/636/778`） | 全部交互前移为启动参数，流水线内零停顿；唯一人工闸门（发布）做成启动前 flag（计划第 2 节第 5 条） |
| 无忠实度回验，`no hallucination` 是营销话术（`README.md:53/70`） | 7 指标 + 逐字引文 + `claim_ledger` + V1/V2/V3 + 负例冒烟（ADR-003） |

---

## 4. 体裁 → 引擎映射（计划第 4 节）

| `genre_id` | 内置插件 | `default_engines` | 理由 |
|---|---|---|---|
| `coach` | `coach_dialogue` | `[behavior_skill]` | 价值在提问顺序/状态机/每轮只问一题/结论归用户，是**过程**而非可查阅条目 |
| `analysis` | `professional_analysis` | `[behavior_skill, knowledge_pack]` | 既要可运行的三阶段裁决流水线（含 `falsification_condition`），又要可查的口径表/红旗清单/术语表 |
| `checklist` | `decision_checklist` | `[behavior_skill, knowledge_pack]` | 既要 `When X, do Y, because Z` 的决策单输出，又要 `threshold/tradeoff_matrix/decision_tree/not_applicable` 的可查规则库 |
| `reference` | `knowledge_reference` | `[knowledge_pack]` | 价值在 Topic Index 路由与按需加载；「书中未回答必须答『书里没讲』」是检索型契约 |

**路由判定**（12 个确定性特征，权重/阈值外置在 `configs/router.json`——见 ADR-001 §6 的 JSON 约束）：

- `score[g] = Σ w[g][f]·norm(f) + prior[g] + Σ hard_gate_bonus`，`norm(f)=min(1,raw/cap)`。
- 硬门示例：`question_density≥0.18 ∧ second_person_ratio≥0.012 → coach +0.25`；`numeric_threshold_density≥0.010 ∧ evidence_marker_density≥0.008 → analysis +0.25`。
- `margin = top1-top2 ≥ 0.15` → 取 top1，引擎 = 插件 `default_engines`。
- `margin < 0.15` → 走歧义兜底（下节）。
- **人工覆盖优先级**：`CLI > run.json > 插件 default > router`，一律记入 `override_source ∈ {cli, run_yaml→run_json, plugin_default, auto, ambiguity}`（计划第 4 节；文件名按 ADR-001 §6 改为 JSON）。

---

## 5. 歧义兜底（不停人）

当 `margin < 0.15`：

1. **固定种子抽 8 段**，由 **3 个独立 LLM judge** 打体裁标签，每票 `+0.10`；全部证据（段号、`slices/` 切片路径、各 judge 输出、种子）落 `router_evidence.json`；**reviewer 只读原始切片、不读摘要**（与 ADR-003 负例/reviewer 约束一致）。
2. 若仍不足 → `engines=["knowledge_pack","behavior_skill"]`、`genres=[top1,top2]`、`reason="ambiguous_dual_output"`，即**自动双引擎双产物**。
3. **全程不停人**：这是与上游 5 处强制停人（`SKILL.md:118/294/364/636/778`）的关键差异——BookLeme 把交互全部前移为启动参数，歧义用「双输出 + 完整证据留痕」兜底，而不是打断流水线问用户（计划第 2 节第 5 条、第 4 节）。

**动机**：批处理场景下「停人」不可接受；而「两件都做」的成本只是多一次 `S6 Render`（`S1/S2/S4/S5` 已共享），是歧义时最稳妥的选择。用户事后可用 `--engine` 单独关闭其一（计划第 13 节风险缓解「双引擎复杂度 → `--engine` 可单独关闭」）。

---

## 6. 被否决的替代方案及理由

| # | 替代方案 | 否决理由 |
|---|---|---|
| A | **单引擎 + 模式开关**（一套模板里用 `if engine == ...` 分支同时产出两种产物） | 两类产物的 `output_contract` 根本不同（检索型文件树 vs 状态机 + 会话状态 + `state_io.py` + 具名输出模板）。单模板会退化成条件分支泥潭，插件的 `state_machine / hard_constraints / output_contract / voice_calibration` 无法作为「硬必填字段」被 `plugin validate` 逐项校验（计划第 5 节），正是上游「有概念无字段」的病根（`SKILL.md:30-35`、`:871-881`）。 |
| B | **两条独立流水线，各读各的书**（`knowledge pipeline` 与 `behavior pipeline` 完全分开） | ① 违反方向 B「共用同一核心引擎」；② S1 提取、S2 分段、S4 能力抽取（最贵的 agent-swarm）全部翻倍；③ 两套 `full_text.txt` / 两套 `segments.json` 会使 `claim_ledger.json` 的 `span` 与 `router_evidence.json` 的段号无法互证，逐字引文校验失去唯一基准；④ `book_sha256` 为键的 IR、幂等缓存、反馈闭环全部要写两遍（计划第 2 节第 7 条）。 |
| C | **先生成知识包，再二次翻译为行为 Skill**（两阶段串行，第二阶段读第一阶段的产物） | ① 多一次 LLM 生成 pass，引入不可 diff、不可单测的模型漂移（计划第 2 节第 2 条）；② 「翻译」会丢失作者精确命名与 `R_quote` 的逐字可追溯链，与 ADR-003 的 `verbatim_violation_rate=0.00` 冲突；③ 第二阶段无法访问 `slices/` 原始切片与 `full_text.txt`，V1 跨域佐证与 reviewer 约束失效；④ 把确定性提取与概率性生成重新耦合，违背采信原理④。 |
| D | **运行时按 query 动态决定引擎**（懒分流：装一个「元 Skill」，每次查询时再决定走知识包还是行为） | ① WorkBuddy/兼容宿主的技能是**构建期静态产物**，靠 `SKILL.md` frontmatter + 相对 `references/` 加载，没有「运行时按 query 切换引擎」的机制（`SKILL.md:88`、`:613`、`:878` 展示的正是静态发现/按需加载）；② 无法在 `S7` 用 `quick_validate.py` 对「尚未确定的产物」做构建期硬门；③ 状态机 / `state_io.py` / 会话状态必须提前落盘，运行时才决定来不及；④ 与「产物可独立开源、可 diff、可 CI 回归」冲突。 |
| E | **照搬上游单 `SKILL.md` + 宿主推理**（不做双引擎，只复刻上游做法） | ① 产出仍是可查阅知识包，覆盖不了两个案例的行为需求（§2.1）；② 生成器是巨型 prompt，不可单测/不可 diff/换模型漂移；③ 「no hallucination」无回验（ADR-001 #11、`README.md:53/70`）；④ 无体裁插件、无忠实度层、无负例冒烟，直接违反计划第 2 节全部 8 条差异化。 |
| F | **总是双引擎双产物**（不做路由，每本书都产两份） | ① 多数书只适合一种引擎，强制双产物浪费 `S6 Render` 且给用户噪音；② 无法提供 `router_accuracy`（计划第 11 节指标）这一可测能力；③ 使「体裁→默认引擎映射」和插件 `default_engines` 失去意义；④ 与 v1 最小闭环「单引擎先跑通」（计划第 10 节）冲突。路由 + 歧义兜底已覆盖「不确定」的情况，无需默认全开。 |
| G | **按文件格式/来源而非体裁路由**（PDF→知识包、EPUB→行为等） | 体裁是**内容属性**，格式是**容器属性**，二者无因果关系；同一本 PDF 可能是教练书也可能是参考手册。上游 `utils.py:1106-1195` 的 `detect_structure` 已证明结构信息（`chapters_method` / `has_toc`）是内容派生的，不能替代体裁特征。计划第 4 节的 12 个确定性特征全部基于文本内容，是正确的路由依据。 |

---

## 7. 与实现约束的衔接（ADR-001 §6）

- `configs/router.yaml` → **`configs/router.json`**（键/权重/阈值语义等价）；`run.yaml` → **`run.json`**；`override_source` 中 `run_yaml` 相应改为 `run_json`。
- `S6 Render` 用**标准库字符串模板**（无 `jinja2`）；插件 `render(ctx)` 契约不变。
- `S3` 的 12 特征与权重全部确定性、可复现，由标准库 `unittest` 测试（计划第 11 节硬验收第 12 条）。
- `state.json` 的 `input_sha256` 纳入 `router.json` 与 prompts 版本，保证「删掉任一 stage 输出重跑只补该 stage 及下游」（计划第 3 节）。

---

## 8. v1 边界与验收锚点

- **v1 最小闭环**：合成中文书 → `--genre <指定>` → **单引擎** → 1 个产物目录 → `quick_validate.py` 退出码 0 → 装到真源（计划第 10 节）。双引擎在 v1 以「歧义路径自动双输出」和 `--engine both` 体现，但先把单引擎跑通。
- **硬验收锚点**（计划第 11 节）：第 10 条「双引擎共享 S1/S2/S4/S5，`state.json` 证明 S4 只跑一次」、第 11 条「删 S5 输出重跑只补 S5」、第 12 条「12 个路由特征确定性可复现；歧义路径产出 `router_evidence.json` 且不停人」、第 8 条「产物由 `plugin.output_contract` 决定，未把上游五文件模板当唯一产物」。

> **M2/M3 实测补记（主代理，2026-11-08）**：以上锚点**不是待办，已全部实测通过**。其中第 11 条在 `run_id=smoke-002` 上执行：删除 `cache/<sha12>/` 下 `claim_ledger.json` / `capabilities_verified.json` / `fidelity_report.json` 后重跑，日志显示 **S0–S4 全 SKIP、仅 S5 重算、S6/S7/S9 因 `input_sha256` 未变而 SKIP**；完整幂等重跑（不删任何产物）则 **S0–S9 全 SKIP**（`run_id=single-001` 第二次运行，10 条 SKIP）。第 10 条由 `build_manifest.json.shared_ir` 与 `state.json` 证明；第 12 条由 `test_features_deterministic_and_normalised` 与 `router_evidence.json`（`llm_judge_invoked: false`）证明；第 8 条由 behavior 14 文件 / knowledge 11 文件的不同目录结构证明。逐条证据见 `docs/ACCEPTANCE-M0-M3.md`，日志在 `logs/M0-M2/`。

---

## 9. 结论

双引擎是**编译目标层**的分叉，不是**数据层**的分叉。`S3 ‖ S4` 并行、共享 `S1/S2/S4/S5` 全量 IR、只在 `S6` 分流，是同时满足「不重复读书」「可单测可 diff」「忠实度唯一基准」「不停人批处理」四个约束的最小结构。体裁→引擎映射、歧义双输出兜底、人工覆盖优先级均已冻结；七个替代方案逐一否决并记录理由。**任何把分叉提前到 S4 之前、或让两引擎各读一次书的设计，都违反本 ADR。**
