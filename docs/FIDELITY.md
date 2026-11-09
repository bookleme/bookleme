# BookLeme 忠实度层（M1 设计冻结）

> **M2 实现口径（以代码为准，2026-11-08）**：本文件描述设计目标；实际实现在 `/Users/bertram/Desktop/BookLeme/bookleme/`。共享中间 IR 在 `cache/<book_sha256前12>/`，`out/<run_id>/` 只放本次产物与报告；`router_result.json`、`provenance_manifest.json` 按 run 隔离。完整差异见 `docs/ARCHITECTURE.md` 的「M2 实现口径校正」表。文中凡提「可插拔 LLM 接口」，一律按统一口径理解：**设计上预留为可插拔接口，本批代码未实现该接口文件，留待后续批次接入**（`bookleme/llm/client.py` 与 `CapabilityExtractor` Protocol 本批均不存在，只有 `bookleme/llm/__init__.py` 的 `LLM_AVAILABLE = False` 占位）。

> 状态：M1 设计冻结。上游 "no hallucination" 是营销话术（上游仓库 `README.md:53/:70`、`docs/faq.md:50-52` 有此宣称），全仓**无** groundedness / 逐字引文 / claim ledger / 覆盖率自动回验，`tools/evals/score.py:2/27` 只做合成轨迹的路由分类与 usage 记账且不推断未观测状态——这正是本忠实度层的立足点（上游证据与隔离参考目录 `/Users/bertram/Desktop/BookLeme-上游参考/` 详见 `$ROOT/docs/UPSTREAM_AUDIT.md`）。本层把它拆解为**可测指标 + 逐字引文校验 + 断言台账**，并强制区分 `measured` / `heuristic`。
> 前缀 `$ROOT = /Users/bertram/Desktop/BookLeme`。**共享中间 IR 落 `$ROOT/cache/<book_sha256前12>/`（跨 run 共享）**，本次运行产物与报告落 `$ROOT/out/<run_id>/`；以 `docs/ARCHITECTURE.md`「M2 实现口径校正」表为准、以代码为准。
> 本机零第三方依赖：逐字引文校验用标准库 `unicodedata`（**受限** NFKC：康熙部首 + CJK 兼容表意文字，见第 5 节）+ 内置子串 / shingle 计算；V2 / V3 的 judge 设计上预留为可插拔接口、**本批代码未实现该接口文件**，留待后续批次接入（本批以确定性兜底，结论一律标 `heuristic`）。**本批 S4 能力抽取为确定性抽取器（合成书显式结构化标记），未实现 LLM 抽取，未验证「框架优于摘要」。**

---

## 1. `capabilities.json` 完整字段表

文件：`$ROOT/cache/<book_sha256前12>/capabilities.json`（S4 输出，S5 / S6 输入；共享 IR，见 ARCHITECTURE.md「M2 实现口径校正」）。按**框架原子化拆分**，不是「一本书一个 skill」。校验依据 `$ROOT/schemas/capabilities.schema.json`。

| 字段 | 类型 | 约束 / 含义 |
|---|---|---|
| `capability_id` | str | 唯一，建议 `<slug>-<seg>-<nn>` |
| `title` | str | 原子能力名，**保留作者精确命名** |
| `genre_tags[]` | list[str] | 体裁标签，`coach / analysis / checklist / reference` 子集，供路由与 golden 比对 |
| `engine_targets[]` | list[str] | ⊆ `{knowledge_pack, behavior_skill}`；S6 据此过滤（ARCHITECTURE.md 3.3）；空则记 warning 不进引擎 |
| `source_id` | str | 关联 `sources.json` 的 `source_id` |
| `span` | object | 出处定位 `{chapter, section, page, char_start, char_end}` |
| `span.chapter` | str | 章节 |
| `span.section` | str | 小节 |
| `span.page` | int / str | 页码（无则 null） |
| `span.char_start` | int | `full_text.txt` 起始字符偏移，经 `char_map.json` 可反查 |
| `span.char_end` | int | 结束字符偏移 |
| `ria` | object | RIA++ 六段（见第 2 节），缺段 → `status = rejected` |
| `ria.R_quote` | str | ≤150 字，逐字可追溯 |
| `ria.I_rephrase` | str | 转述，与原文 13 字 shingle 相似度 ≤0.10 |
| `ria.A1_author_case` | str | 书中作者用过的案例 |
| `ria.A2_user_trigger` | str | 用户什么情境需要此 trigger（触发面种子） |
| `ria.A3_steps[]` | list[str] | 1-2-3 可执行步骤 |
| `ria.B_not_applicable` | str | 不适用条件，必填 |
| `claims[]` | list[str] | 关联 `claim_ledger.json` 的 `claim_id` |
| `checks` | object | `{v1[], v2_predictive_q, v2_pass, v3_uniqueness, v3_pass}` |
| `checks.v1[]` | list | ≥2 个不同 segment 的跨域佐证（measured） |
| `checks.v2_predictive_q` | str | 书里没明说的新问题 |
| `checks.v2_pass` | bool | fresh-context judge 判定（heuristic） |
| `checks.v3_uniqueness` | number | judge 独特性打分（heuristic） |
| `checks.v3_pass` | bool | 是否过 `common_sense_denylist.txt` + judge 门 |
| `confidence` | object | `{tier, score}`；`tier` ∈ `S / A / B / C`（见第 3 节） |
| `status` | enum | `active \| uncovered \| invalidated \| rejected` |

---

## 2. `claim_ledger.json` 完整字段表

文件：`$ROOT/out/<run_id>/claim_ledger.json`（S5 本次运行报告输出）。**M2 校正**：`verification.json` / `regen_queue.json` / `plugin_scan.json` 本批未生成（接口占位）；S5 实际产出 `capabilities_verified.json` / `claim_ledger.json` / `fidelity_report.json`。校验依据 `$ROOT/schemas/claim_ledger.schema.json`。

| 字段 | 类型 | 约束 / 含义 |
|---|---|---|
| `claim_id` | str | 唯一断言 ID |
| `text` | str | 断言文本 |
| `source_id` | str | 关联 `sources.json` |
| `origin` | enum | `local \| public`（混合输入分级，见 COPYRIGHT.md 第 1 节） |
| `chapter` / `section` / `page` | str / str / int | 出处定位 |
| `source_tier` | enum | `S \| A \| B \| C`（见第 3 节） |
| `quote_verified` | bool | 是否通过第 5 节逐字引文校验 |
| `verification` | object | `{v1_cross_domain[], v2_pass, v3_pass}` |
| `verification.v1_cross_domain[]` | list | ≥2 不同 segment 佐证（measured） |
| `verification.v2_pass` | bool | 预测力（heuristic） |
| `verification.v3_pass` | bool | 独特性（heuristic） |
| `groundedness` | number | 0–1 打分（heuristic 时填） |
| `groundedness_type` | enum | `measured \| heuristic`，标注该值来源 |
| `status` | enum | `verified \| invalidated \| rejected` |
| `evidence_path` | str | 指向 `slices/seg-XXX.md`（共享 IR 在 `$ROOT/cache/<book_sha256前12>/`）或 `$ROOT/out/<run_id>/` 内证据文件的绝对路径；reviewer **只读原始切片不读摘要** |

---

## 3. RIA++ 六段落地规则

| 段 | 规则 | 违反后果 |
|---|---|---|
| `R_quote` | ≤150 字且**逐字可追溯**（第 5 节精确子串校验） | 不过 → capability `rejected` |
| `I_rephrase` | 与原文 **13 字 shingle 相似度 ≤0.10**（Jaccard） | 超阈 → `invalidated` 入 regen |
| `A1_author_case` | 必须是**书中作者用过**的案例，不得杜撰 | 杜撰 → `rejected` |
| `A2_user_trigger` | 写「用户什么情境下需要这个 trigger」（触发面种子，供 `description` 触发词聚类） | 缺 → `rejected` |
| `A3_steps[]` | 1-2-3 可执行步骤 | 缺 → `rejected` |
| `B_not_applicable` | **必填**，写明不适用条件 | 缺 → `rejected` |

**缺任一段 → capability `status = rejected`**。`figure_text_lost` 段（图表文字丢失）自动降一级且**不得单独支撑 V1**。

---

## 4. 可信度 S / A / B / C 分级与硬规则

| 级别 | 含义 | 来源 |
|---|---|---|
| `S` | 本地有权正文 | `origin = local`，本地有权文件 |
| `A` | 作者访谈或官方讲义 | `origin = public` |
| `B` | 权威书评 | `origin = public` |
| `C` | 推算 | `origin = public` |

**硬规则**：

1. **公开来源最高只能 A / B / C** —— 任何 `origin = public` 的断言不得标 `S`。
2. **任何 S 级断言必须有 `local` 支撑**（`source_tier = S` ⟹ `origin = local`），否则降级或 `rejected`。
3. `figure_text_lost` 段自动降一级（S→A、A→B、B→C）且不得单独支撑 V1。
4. 分级写入 `claim_ledger.source_tier` 与 `provenance_manifest.sources[].tier`，两处须一致。

---

## 5. 逐字引文校验算法（`R_quote` 精确子串）

全部确定性，标准库实现，与 M2 代码 `extract/base.py::normalize` 对齐。**关键约束：绝不整篇做 NFKC 归一**（上游 `sanitize.py:158-178`、`181-204` 只折叠康熙部首，`sanitize.py:168-171` 给出理由：整篇 NFKC 会改写全角字符、连字、带圈数字等合法文本；`test_cjk_radical_normalization.py:59-75`、`test_sanitize_extracted_text.py:33-40` 实测普通多语言文本逐字节保留）。本批回归测试 `test_normalize_is_scoped_not_whole_text_nfkc` 锁死该行为。

1. **受限 NFKC 归一（两类字符）**：先剥离不可见控制字符，再只对 ① 康熙部首 `U+2F00–U+2FDF` 与 ② CJK 兼容表意文字 `U+F900–U+FAFF` 做 NFKC 折叠（`unicodedata.normalize("NFKC", ch)` 逐字符、仅当码位落入这两个区间），**其余字符原样保留**；`full_text.txt` 与 `R_quote` **两侧必须用完全相同的归一规则**，否则全角 / 连字形会破坏精确子串匹配。上游 `utils.py:174-185` 另有第二套硬编码数字映射 `_KANGXI_NUMERAL_TRANS`（⼀⼆⼋⼗ → 一二八八，用于 `:805` 章节号解析），BookLeme **不采用**该映射（其 `:177` 注释称「NFKC does not map these」经审计实测为误，NFKC 确把 U+2F00 → 一）。
2. **去零宽 / 控制字符**：剥离 U+200B / 200C / 200D / FEFF 及 C0 / C1 控制字符（两侧同样处理，与第 1 步同一次剥离，不重复）。
3. **char_map 反查**：用 `$ROOT/cache/<book_sha256前12>/char_map.json`（归一前偏移 ↔ 归一后偏移映射，共享 IR）把 `R_quote` 的归一后区间反查回原文偏移，确保 `span.char_start` / `char_end` 与引用一致。
4. **精确子串断言**：断言归一后的 `R_quote` 是归一后 `full_text.txt` 的**精确子串**（`in` 运算，不是模糊匹配、不是编辑距离）。
5. **判定**：不满足 → 该 capability 直接 `status = rejected`，`quote_verified = false` 写入 `claim_ledger.json`，并计入 `verbatim_violation_rate`。

**shingle 阈值**：13 字滑窗 shingle，Jaccard 相似度 `|A∩B| / |A∪B|`；`I_rephrase` 与原文、产物任意段与原文均须 `≤ 0.10`（对应 `shingle_overlap_max` 与 S7 `copyright_gate.py` 的 13 字 shingle Jaccard ≤0.10）。**shingle 与连续复制比较同样使用本节受限归一规则，不得整篇 NFKC。**

---

## 6. 7 个指标表（`fidelity_report.json`）

文件：`$ROOT/out/<run_id>/fidelity_report.json`。**每条必须带 `metric_type`**。

| 指标 | `metric_type` | 目标值 | 计算口径 |
|---|---|---|---|
| `citation_resolution_rate` | `measured` | 1.00 | 有出处的断言 / 全部断言，确定性计数 |
| `verbatim_violation_rate` | `measured` | 0.00 | 逐字引文校验失败数 / 引文总数（第 5 节算法） |
| `coverage_score` | `measured` | ≥0.85 | 已覆盖 segment / 应覆盖 segment，`uncovered` 扣分 |
| `negative_refusal_rate` | `measured` | 1.00 | 负例冒烟「书中未回答」正确拒答数 / 负例总数 |
| `unsupported_claim_rate` | `measured+heuristic` | ≤0.05 | 主体为 `claim_ledger` 确定性计数（measured）；判「无支撑」时叠加 judge 的启发式判定，硬门按 measured 部分执行 |
| `groundedness` | `heuristic` | 只报告不作硬门 | judge 打分，**仅报告、不参与 hard gate、不参与 CI 5% 退化判定** |
| `shingle_overlap_max` | `measured` | ≤0.10 | 产物与原文 13 字 shingle Jaccard 最大值 |

> **`groundedness` 只报告不作硬门**。禁止把它写成「已验证零幻觉」或纳入验收硬门 / CI 回归门。

---

## 7. V1 / V2 / V3 各自是实测还是启发式、为什么

| 校验 | 分类 | 为什么 |
|---|---|---|
| **V1 跨域佐证**（≥2 个不同 segment 的佐证） | **measured（实测）** | 对 `segments.json` / `claim_ledger.json` 做确定性计数与出处比对，不依赖任何主观判断，可复现、可 diff、不随模型漂移 |
| **V2 预测力**（fresh-context judge 回答书里没明说的新问题） | **heuristic（启发式）** | 依赖 LLM judge 对「新问题是否被框架正确回答」的主观打分，不可单测 / 不可 diff、换模型即漂移；该 judge 设计上预留为可插拔接口、**本批代码未实现该接口文件**，留待后续批次接入；本批以确定性兜底，结论仍标 heuristic（值为 `null`） |
| **V3 独特性**（先过 `common_sense_denylist.txt` 淘汰「要耐心」类常识，再由 judge 打分） | **heuristic（启发式）** | denylist 过滤是确定性的，但「是否独特」的最终判定由 judge 主观打分给出，整体标 heuristic |

**分类准则**：能否由确定性数据 / 计数复现且**不依赖 LLM 主观判断** —— 能则 `measured`，依赖 judge 主观打分则 `heuristic`。

---

## 8. 未验证假设表（禁止夸大）

| 假设 | 状态 | 说明 |
|---|---|---|
| `PD-04` | `BLOCKED` | 上游推导的产品假设，本批未验证 |
| `PD-05` | `UNVERIFIED` | 认知状态 `UNVERIFIED`；上游任务台账的 `PD-05 = BLOCKED` 属任务进度口径，二者不矛盾（见下方口径澄清） |
| `PD-06` | `BLOCKED` | 上游推导的产品假设，本批未验证 |
| `PD-07` | `BLOCKED` | 同上 |
| `PD-08` | `BLOCKED` | 同上 |
| `PD-09` | `BLOCKED` | 同上 |
| `PD-10` | `BLOCKED` | 同上 |
| `PD-11` | `BLOCKED` | 同上 |
| `PD-12` | `BLOCKED` | 同上 |

> **状态口径澄清（表面冲突，实为两种不同口径叠加，非前后矛盾）**：① 上游任务台账把 `PD-05` 标 `BLOCKED`（`docs/research/progressive-disclosure-evals.md:215/:556`），那是**任务进度状态**；② BookLeme 计划要求把「结构化框架优于摘要」这一假设在自家未验证假设表标 `UNVERIFIED`（上游 guardrail `:577` 明确该假设未被验证，`:40` 说明论文并未验证当前语义表示），那是**认知状态**；③ 计划又要求「PD-04~PD-12 全部 `BLOCKED`」，而 `PD-05` 落在该区间内。三者叠加使字面上 `PD-05` 同时出现 `UNVERIFIED` 与 `BLOCKED`。本冻结按团队裁决口径处理：**`PD-05 = UNVERIFIED`（认知状态，单列），`PD-04`、`PD-06`~`PD-12` = `BLOCKED`**。PD 假设的文字命题由 `$ROOT/docs/decisions/ADR-001~003` 与 `$ROOT/docs/UPSTREAM_AUDIT.md`（另一代理负责）给出，本文不编造其具体内容。

**明确禁令**：

- 禁止把上游的 **24×–51×（其自测）** 与 **2.4×–15.6×（其模型估算）** 转写成本项目结论。二者出自上游 `docs/performance.md:44-55`：前者是 context-dump 优势（基于实测 token 数的上游自测），后者原文 `:54-55` 是「a model using the book's real ToC/chapter sizes」；另 `progressive-disclosure-evals.md:42/:573` 提到论文 K=20 En.QA 的 ~2× 是**条件特定**、不可当通用结论。若引用必须**原样标注来源与性质**（「上游自测」/「模型估算」/「条件特定」），且不得进入 `README.md` 的结论、不得写进 `metrics.json`。
- 本项目**只报告 `$ROOT/evals/baseline.json` 中自己实测的数字**（按 `bookleme_version + model_fingerprint + plugin_hash` 版本化）。
- `README.md` 不得出现「零幻觉」「24×–51× 实测」表述；所有 `heuristic` 指标不得写成既成事实。
- 本批 S4 为确定性抽取器；LLM 抽取器设计上预留为可插拔接口、**本批代码未实现该接口文件**，留待后续批次接入。**不得把 LLM 抽取或「框架优于摘要」写成既成事实或本项目结论**。
