# ADR-003：忠实度指标、可测性边界与「未验证假设」纪律

- **状态**：Accepted（M0 设计冻结，2026-11-08）
- **决策者**：BookLeme 主代理 / general-purpose-1（起草本 ADR）
- **相关**：计划第 2、6、8、11 节；ADR-001（尤其 C2 / C5 / C7 与 §6 实现约束）；ADR-002；`docs/UPSTREAM_AUDIT.md`；`evals/baseline.json`
- **约束**：本 ADR 冻结「把 no hallucination 拆成可测指标」的口径；**明确禁止**把上游自测/估算数字转写为本项目结论。不导入任何上游代码。

---

## 1. 决策背景

上游 README 与 FAQ 宣称 **"no hallucination" / "grounded in the text you provided"**（`README.md:53`、`:70`、`docs/faq.md:50-52`），但本地审计确认（ADR-001 #11、`docs/UPSTREAM_AUDIT.md §3`）：

- `tools/evals/score.py:2/26-76` 只给**合成轨迹**做路由分类与 usage 记账，且 `:27` 明言「不加载文件、不推导缺失观测」；
- `tools/validate_skill.py:213-291` 只校验 frontmatter/宿主规则；
- `tools/scan_generated_skill.py:2` 只是 advisory 安全扫描（`:350` 建议人工复核，`:355` 不改文件）；
- 全仓**无** groundedness、逐字引文校验、claim ledger、shingle 重叠、覆盖率、负例拒答的自动门；
- `docs/research/progressive-disclosure-evals.md:40` 自承论文未验证当前语义表示，`:577` 把「结构化框架优于摘要」列入 Claims guardrail。

因此 BookLeme 不复用「零幻觉」话术，而是把它拆成 **7 个带 `metric_type` 的可测指标**（计划第 6 节），并**强制区分 `measured` / `heuristic`**：前者可作硬门与 CI 回归，后者只报告、不作硬门、不得写成既成事实。

---

## 2. 七个指标逐一裁定（计划第 6 节 `fidelity_report.json`）

> 每条在 `fidelity_report.json` 中必须带 `metric_type`；`measured` 才可作 hard gate 与 CI 回归基线比对，`heuristic` 只报告。
> 「目标值」为硬验收目标，不是已测结果；当前全部处于 `BLOCKED`（见 `evals/baseline.json`）。

| # | 指标 | `metric_type` | 目标值 | 定义与测量方式 | 硬门 | 上游是否有对应能力 |
|---|---|---|---|---|---|---|
| 1 | `citation_resolution_rate` | **measured** | `1.00` | `claim_ledger.json` 中 `quote_verified=true` 且 `R_quote` 能经 `char_map.json` 反查为 `full_text.txt` **精确子串**、并带 `source_id/chapter/section/page` 出处的断言占比。纯字符串/substring 计算，确定性、可复现。 | 是 | 无（README 只口头宣称 grounded） |
| 2 | `verbatim_violation_rate` | **measured** | `0.00` | 违规断言占比：单条 `R_quote > 150` 字、或 `R_quote` 非 `full_text.txt` 精确子串、或 `max_contiguous_copy_chars > 150`、或产物内出现 `full_text.txt` / `slices/` / 原书文件拷贝。与计划第 8 节 6 条硬检查一致，全确定性。 | 是 | 无（仅 `SKILL.md:879` 散文「Never copy raw book text」） |
| 3 | `coverage_score` | **measured** | `≥ 0.85` | `capabilities.json` 覆盖的 `segments.json` 段落比例（按 `span.char_start/char_end` 与段 `char_range` 求并集）；单段重试 2 次仍失败记 `uncovered` 并扣分（计划第 3 节 S4）。确定性集合运算。 | 是 | 无（上游无覆盖率概念） |
| 4 | `negative_refusal_rate` | **measured** | `1.00` | `evals/negative_cases.json` 中 `negative_unanswered` 用例「必须答『书里没讲』且不得编造出处」的通过率；`boundary` 用例「只答已覆盖并声明缺口」亦计入。二值判定，可脚本化。任一失败 → `S7 abort`（计划第 6 节）。 | 是 | 无（上游无负例集） |
| 5 | `unsupported_claim_rate` | **measured + heuristic** | `≤ 0.05` | 混合指标：`quote_verified=false` / V1 跨域佐证失败 / `claim_ledger.status != validated` 的占比是 **measured**；「断言是否被书中证据支撑」的 judge 判定是 **heuristic**。CI 回归以 measured 部分为准，heuristic 部分只报告。 | 是（measured 部分） | 无 |
| 6 | `groundedness` | **heuristic** | **只报告，不作硬门** | 由 3 个独立 judge 多数投票对「生成内容是否忠于原书」打分。**主观、 model-dependent、不可复现**，因此：不设目标阈值、不进 hard gate、不进 CI 退化判定、不得写成「零幻觉」。基线里 `target=null`。 | 否 | 无（且上游把它当卖点） |
| 7 | `shingle_overlap_max` | **measured** | `≤ 0.10` | `I_rephrase` 与原文 13 字 shingle 的 Jaccard 相似度上限；同时约束总引文比 `≤ 0.03`（计划第 6/8 节）。确定性字符串集合运算。 | 是 | 无 |

**分类纪律（计划第 11 节硬验收第 18 条）**：任何指标不得把 heuristic 写成既成事实；`groundedness` 在任何文档/README 中只能以「启发式、只报告」出现；`unsupported_claim_rate` 必须标注混合性质。

**C2 修正（来自 ADR-001）落地到指标 1/2/7**：上游 `sanitize.py:158-178` **刻意不做整篇 NFKC**（`tests/test_cjk_radical_normalization.py:59-75`、`tests/test_sanitize_extracted_text.py:33-40` 断言普通文本逐字节保留）。因此 `R_quote` 的「精确子串」校验**不得**对 `full_text.txt` 整篇归一；必须：① 引文与全文两侧用**同一套**归一化规则（仅去零宽/控制字符 + 康熙部首折叠），或 ② 依赖 `char_map.json` 反查到归一前偏移。否则全角/连字/带圈数字形会破坏精确匹配，指标 1 与 2 会同时失真。**不得采信 `utils.py:177` 的「NFKC does not map these」注释**（实测不成立）。

---

## 3. V1 / V2 / V3 的可测性边界（计划第 6 节）

`capabilities.json` 每条 `checks{v1[], v2_predictive_q, v2_pass, v3_uniqueness, v3_pass}`。三者**可测性不同，必须分别标注**，不可混称「验证通过」。

| 校验 | 内容 | 可测性 | 边界与失效条件 |
|---|---|---|---|
| **V1 跨域佐证** | 一条框架/断言须在 **≥2 个不同 `segment`** 有证据支撑（`v1_cross_domain[]` 记录段号与切片路径） | **measured（实测）** | 只证明「书中多处出现」，**不证明**「生成表述忠于原书语义」；`figure_text_lost` 段自动降一级且不得单独支撑 V1（计划第 6 节）。段号依赖 S2 唯一 `segments.json`（ADR-002 §3.3）。 |
| **V2 预测力** | fresh-context judge 回答「书里没明说的新问题」，看生成的能力能否外推 | **heuristic（启发式）** | judge 主观、模型依赖、不可复现；**不得**作为 hard gate 或 CI 退化依据；「回答正确」不等于「忠于原书」。`progressive-disclosure-evals.md:194` 上游自承「Do not infer hidden reasoning from an answer string」。 |
| **V3 独特性** | 先过 `common_sense_denylist.txt` 淘汰「要耐心」类常识，再由 judge 打独特性分 | **heuristic（启发式，含一个确定性前置）** | 去常识表的**过滤**是确定性的，但「是否独特」的 judge 打分是启发式；整体按 heuristic 处理。不得据此宣称「非幻觉」。 |
| **逐字引文校验** | NFKC 范围修正后的 `R_quote` 精确子串反查（见 §2 C2） | **measured** | 只能校验「逐字可追溯」，**不能**校验「转述/提炼是否失真」——那是 V2/V3/groundedness 的启发式范畴。缺段 → capability `rejected`。 |

**可信度分级（计划第 6 节 `claim_ledger.json`）**：`S`=本地有权正文 / `A`=作者访谈或官方讲义 / `B`=权威书评 / `C`=推算；**公开来源最高只能 A/B/C，任何 S 级断言必须有 local 支撑**；`figure_text_lost` 段自动降一级。

**收敛与重生成**：`invalidated` 入 `regen_queue.json`，Generator→Evaluator→Re-generator **≤3 轮**；仍不过 → capability `rejected`；收敛门 = hard gate 全过 + 无 P0；reviewer **必须读 `slices/` 原始切片**（计划第 6 节）。

---

## 4. 负例冒烟设计（计划第 6 节 / 第 11 节硬验收第 16 条）

`evals/negative_cases.json` **必含**以下用例族，且负例任一失败 → `S7 abort`：

| 用例族 | 预期行为 | 判定 | 关联指标 |
|---|---|---|---|
| `positive` | 书中有答案 → 必须给出答案且**带出处**（`chapter/section/page/source_id`） | 确定性脚本比对 | `citation_resolution_rate` |
| `negative_unanswered` | **一个书中未回答的问题** → 必须答「书里没讲」，且**不得编造出处** | 二值 + 出处空校验 | `negative_refusal_rate`（目标 1.00） |
| `boundary` | 部分覆盖 → 只答已覆盖部分并**声明缺口**，不补全、不推测 | 确定性 | `negative_refusal_rate` / `coverage_score` |
| `trigger_hit` | 命中 3–5 个中文触发词时应激活 | 确定性 | `trigger_hit_rate`（≥0.90 / 误触发 ≤0.05，§11） |
| `trigger_miss` | 不相关 query 不应误触发 | 确定性 | `trigger_hit_rate` |

**约束**：
- 冒烟用例只用合成书 / 公版书（`evals/cases/synthetic/`、`evals/cases/public_domain/`），**不下载受版权书籍、不提交任何原文**（计划第 11 节）。
- reviewer 读原始 `slices/`，不读摘要；与 ADR-002 §5 歧义路由的 reviewer 约束一致。
- 冒烟结果进 `metrics.json` / `fidelity_report.json`，逐条带 `metric_type`。

---

## 5. 「未验证假设」表（强制口径）

> **口径区分（ADR-001 C4）**：`BLOCKED` 是**上游研究任务状态**（`progressive-disclosure-evals.md:210-222`、`:551-563`）；`UNVERIFIED` 是 BookLeme 对**某条假设的认知状态**。二者不是同一维度，不矛盾。
> 本地证据：`docs/research/progressive-disclosure-evals.md:210-222` 台账 PD-00/01/02/03 = `DONE`，**PD-04 ~ PD-12 = `BLOCKED`**（共 9 条）；`:556` 明确 PD-05 = `BLOCKED`。

### 5.1 上游 PD 系列在 BookLeme 的登记

| ID | 上游任务 | 上游状态 | **BookLeme 登记** | 理由 |
|---|---|---|---|---|
| PD-04 | dry-run/live runner 契约 + 首个 harness adapter | BLOCKED | **BLOCKED** | 依赖 PD-02/03，未跑 live |
| **PD-05** | **表示实验：raw payload vs structured B2S payload** | **BLOCKED** | **UNVERIFIED** | 「结构化框架优于摘要」是 BookLeme 借鉴的设计原理，但**上游明确未验证**：`progressive-disclosure-evals.md:40`（论文未把当前语义表示作为自变量）、`:54`（开放问题）、`:365-395`（实验未做，`:394`「A null result is a valid outcome」）、`:577`（Claims guardrail 点名）。标 `UNVERIFIED` 而非 `BLOCKED`，是因为这是**一条假设的认知状态**，不是我们的任务排期。 |
| PD-06 | 自动 vs 显式激活 | BLOCKED | **BLOCKED** | 依赖宿主能力 |
| PD-07 | 路由元数据消融（KEY_ELEMENTS 未独立消融，`:39`/`:434`） | BLOCKED | **BLOCKED** | 不得在证据前改生产路由元数据 |
| PD-08 | 技术/非叙事语料复现 | BLOCKED | **BLOCKED** | 论文 `:41` 明确不验证向技术书/代码迁移 |
| PD-09 | 库级缩放实验 | BLOCKED | **BLOCKED** | 依赖 PD-04/08 |
| PD-10 | 可选 Hybrid RAG 参考基线 | BLOCKED | **BLOCKED** | `:498` 不得宣称「Skills beat RAG」 |
| PD-11 | 分块消融 | BLOCKED | **BLOCKED** | 依赖 PD-08 |
| PD-12 | 证据评审与生产决策 | BLOCKED | **BLOCKED** | `:519-541` 是决策门，非编码任务；`:539`「RAG superiority claims — Never universal」 |

**结论**：**PD-05 = UNVERIFIED；PD-04、PD-06、PD-07、PD-08、PD-09、PD-10、PD-11、PD-12 = BLOCKED**（即 PD-04~PD-12 整体 BLOCKED，仅 PD-05 另标假设认知状态 UNVERIFIED）。这与计划第 6/11/12 节、硬验收第 17 条一致。

### 5.2 BookLeme 自身的未验证假设（同样不得写成事实）

| 假设 | 状态 | 为什么未验证 / 何时可解除 |
|---|---|---|
| 「结构化框架优于摘要」 | **UNVERIFIED**（= PD-05 的认知登记） | 上游零实验验证；BookLeme 亦未做对照实验。只能作为**设计原理**吸收，不得表述为已验证结论（ADR-001 C5）。 |
| 「12 个确定性路由特征能判别 4 体裁」 | **UNVERIFIED** | 需 `router_accuracy ≥0.90` 在合成集实测（§11）；在此之前 `evals/router_labels.json` 的 golden 只是标注。 |
| 「3 个独立 judge 多数投票可靠」 | **UNVERIFIED** | 属 heuristic，model-dependent，不可复现；`groundedness` 因此只报告。 |
| 「`R_quote ≤150` 字 + 13 字 shingle ≤0.10 足以保证不抄原文」 | **UNVERIFIED** | 是工程阈值，非版权法结论；由 `copyright_gate.py` 确定性执行，但阈值本身未经法律/实证验证。 |
| 「V2 预测力 / V3 独特性反映忠实度」 | **UNVERIFIED** | 二者为 heuristic，只报告，不作硬门。 |
| 「`coverage_score ≥0.85` 等价于无遗漏」 | **UNVERIFIED** | 覆盖率是段落并集比例，不覆盖语义遗漏。 |
| 「换模型不漂移」 | **UNVERIFIED** | 依赖 `model_fingerprint` + prompts 版本化 + CI golden 才能观测；当前无基线。 |

### 5.3 文档纪律

- `docs/FIDELITY.md`、`docs/EVALS.md`、README **不得**出现「零幻觉」「24×–51× 实测」等表述（计划第 6 节、硬验收第 17 条）。
- 所有 `heuristic` 指标必须以「启发式、只报告」措辞出现（硬验收第 18 条）。
- 任何「优于 / 提升 / 更准」类表述必须附 `measured` 证据与条件，否则标 UNVERIFIED。

---

## 6. 明确禁令：不得转写上游性能数字（计划第 6 节 / ADR-001 C7）

本地审计确认上游存在**三类**性质不同的性能数字（`docs/performance.md:2/44-46/52-55/59-70`、`docs/research/progressive-disclosure-evals.md:42/573`）：

| 数字 | 性质（上游原文自述） | 本地证据 |
|---|---|---|
| `24×–51×` | **上游自测/自报比值**：context-dump 优势，基于实测 token 数（`119,264 / 175,253 / 256,287` vs `~5,000`），原文 `:52-53` 称「strongest claim」 | `docs/performance.md:44-46`、`:52-53` |
| `2.4×–15.6×` | **模型估算**：discovery-loop 优势，原文 `:54-55` 自述「a one-time cost and **a model** using the book's real ToC/chapter sizes」 | `docs/performance.md:54-55`；`tools/discovery_tax.py:16-24`（自述 *model*, not measurement） |
| `~2×` / `68.3M vs 32.5M` | **条件特定的论文结果**：K=20 En.QA 未缓存测量，`:573` 明令不得发布「book-to-skill uses 2x fewer tokens」 | `docs/research/progressive-disclosure-evals.md:42`、`:573` |
| `~$1/book` | **估算**：按 Claude Sonnet 4.5 价目从实测 token 推算，`:292`/`:278` 要求「价格常变，不硬编码，标注估算并注明日期」 | `docs/performance.md:59-70`；`SKILL.md:278/292` |

**禁令（不可协商）**：

1. **禁止**把上游 `24×–51×` 自测数据与 `2.4×–15.6×` 模型估算（以及 `~2×`、`~$1/book`）**转写成 BookLeme 的项目结论**、README 卖点、评测指标或基线值。
2. 若确需引用，必须**原样标注来源与性质**（「上游自测」「上游模型估算」「论文条件特定结果」「上游估算」），且**明确声明不代表 BookLeme 性能**。
3. BookLeme **只报告 `evals/baseline.json` 中自己实测的数字**；M0 阶段该文件全部为 `BLOCKED` 占位（`value: null`），因此**当前不存在任何可报告的 BookLeme 性能数字**。
4. `evals/baseline.json` 按 `bookleme_version + model_fingerprint + plugin_hash` 版本化（计划第 11 节）；三者任一为 `null` 时不得把 `BLOCKED` 占位值当作基线参与 CI 比对。

---

## 7. `evals/baseline.json` 的 9 个指标（与本节 7 指标的关系）

`evals/baseline.json` 是 **CI 回归基线**，采用计划第 11 节 `metrics.json` 的 **9 指标集**（而非第 6 节 `fidelity_report.json` 的 7 指标集），因为 CI 比对的是 `metrics.json`。两者关系如下，避免下游混淆：

| 指标 | §6 七指标集（`fidelity_report.json`） | §11 九指标集（`metrics.json` / `baseline.json`） | `metric_type`（baseline） | `target`（baseline） |
|---|---|---|---|---|
| `citation_resolution_rate` | ✓ | ✓ | measured | `1.00` |
| `verbatim_violation_rate` | ✓ | ✓ | measured | `0.00` |
| `coverage_score` | ✓ | ✓ | measured | `>=0.85` |
| `negative_refusal_rate` | ✓ | ✓ | measured | `1.00` |
| `unsupported_claim_rate` | ✓（measured+heuristic） | ✓ | measured（混合性质见 §2 #5，heuristic 部分只报告） | `<=0.05` |
| `groundedness` | ✓（heuristic，只报告） | ✓ | heuristic | `null`（无硬门） |
| `shingle_overlap_max` | ✓（measured） | — | （不在 baseline 9 项内） | 由 `copyright_gate.py` 作为确定性硬门执行，目标 `<=0.10`（计划第 8 节 6 条硬检查） |
| `router_accuracy` | — | ✓ | measured | `>=0.90`（合成集） |
| `trigger_hit_rate` | — | ✓ | measured | `>=0.90`（误触发 `<=0.05`） |
| `artifact_compliance_rate` | — | ✓ | measured | `1.00` |

即：9 = 6（与 §6 重叠）+ 3（router / trigger / artifact）；`shingle_overlap_max` 不在 CI 基线里，但仍是 `S5 + S7` 双门中的确定性硬检查（ADR-001 §2 #19 之外的独立门）。

**占位基线字段**：`schema_version`、`bookleme_version`、`model_fingerprint: null`、`plugin_hash: null`、`status: "BLOCKED"`，9 个指标对象每个形如 `{"value": null, "metric_type": "measured|heuristic", "status": "BLOCKED", "target": ...}`。所有 `value` 为 `null`；**在 M4 实测出数前，任何 `BLOCKED` 占位值不得被当作已测结果引用**。

---

## 8. 证据索引（全部为上游本地只读路径）

| 主题 | 路径:行号 |
|---|---|
| 「no hallucination」营销话术 | `README.md:53`、`:70`；`docs/faq.md:50-52` |
| 无忠实度回验 | `tools/evals/score.py:2`/`:26-76`/`:79-98`；`tools/validate_skill.py:213-291`；`tools/scan_generated_skill.py:2`/`:316-363`；`docs/UPSTREAM_AUDIT.md §3` |
| 上游性能数字定性 | `docs/performance.md:2`/`:44-46`/`:52-55`/`:59-70`；`tools/discovery_tax.py:16-24`；`docs/research/progressive-disclosure-evals.md:42`/`:573` |
| PD 系列状态 | `docs/research/progressive-disclosure-evals.md:210-222`/`:551-563`/`:365-395`/`:577` |
| 论文未验证当前语义表示 | `docs/research/progressive-disclosure-evals.md:40`/`:54`/`:577` |
| Claims guardrail | `docs/research/progressive-disclosure-evals.md:567-579` |
| 成本/预算纪律 | `docs/research/progressive-disclosure-evals.md:93-123`；`AGENTS.md:95-104` |
| 上游「Measure, do not assert」 | `AGENTS.md:32`、`:39`、`:93` |
| NFKC 范围修正（C2） | `sanitize.py:158-178`/`:168-171`；`tests/test_cjk_radical_normalization.py:59-75`；`tests/test_sanitize_extracted_text.py:33-40`；`utils.py:174-185`/`:803-805` |

---

## 9. 结论

- 「零幻觉」被拆为 **7 个带 `metric_type` 的指标**：5 个纯 `measured`（硬门/CI 可回归）、1 个混合（`unsupported_claim_rate`）、1 个纯 `heuristic`（`groundedness` 只报告）。
- V1 = measured、V2/V3 = heuristic，可测性边界明确；负例冒烟含 `negative_unanswered` 且任一失败即 `S7 abort`。
- **PD-05 = UNVERIFIED；PD-04 ~ PD-12 = BLOCKED**，并登记 7 条 BookLeme 自身未验证假设。
- **硬禁令**：上游 `24×–51×` 自测、`2.4×–15.6×` 模型估算、论文 `~2×`、`~$1/book` 一律不得转写为 BookLeme 结论；本项目当前**没有任何可报告的性能数字**（`evals/baseline.json` 全 `BLOCKED` 占位）。
- 本 ADR 与 `evals/baseline.json` 共同保证：M4 出数之前，所有性能/忠实度表述只能是「目标值 / 未验证 / BLOCKED」，不能是「实测结果」。
