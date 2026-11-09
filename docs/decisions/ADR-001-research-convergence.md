# ADR-001：上游结论四方收敛性比较（M0 研究对齐）

- **状态**：Accepted（M0 研究对齐交付，2026-11-08）
- **决策者**：BookLeme 主代理（批准）/ general-purpose-1（本地源码审计与收敛性分析）
- **相关**：`radiant-pulse-turing-MzfzgW8-.md` 第 1、2、6、11、12 节；`docs/UPSTREAM_AUDIT.md`（本次本地审计笔记）；ADR-002、ADR-003
- **约束**：本 ADR 只做**研究结论采信裁定**，不导入任何上游代码。上游只读参考目录 `$UPSTREAM_REF/` 全程未被修改。

---

## 1. 背景与「四方」定义

计划模式阶段已完成：三份独立研究报告 + GitHub API 实时复核 + 主代理对 raw 源码与两篇微信原文的在线逐字取证，并在计划第 1 节记录了裁定。M0 阶段把上游 clone 到隔离目录后，对当时「仅列出路径、未逐字阅读」的源码做了**本地逐字审计**（见 `docs/UPSTREAM_AUDIT.md`），现在做显式四方收敛性比较。

本文「**四方**」指四个证据来源族：

| 方 | 来源 | 说明 |
|---|---|---|
| ① 报告族 | 三份独立研究报告（计划模式在线取证） | 三份报告结论已由计划第 1 节记录裁定（「核心原理三项报告完全一致」）；**原始报告文本未落入本工作区**，故本文以计划第 1 节记录的裁定为准，在关键分歧处再分 A/B/C 标注。 |
| ② GitHub API 复核 | 计划模式 GitHub API 实时查询 | 负责 star / fork 等仓库元数据；本地 clone 内不含这些元数据。 |
| ③ 计划模式逐字复核 | 主代理对 GitHub raw 源码 + 两篇微信原文的在线逐字取证 | 计划第 1 节「已逐字核验」的来源，也是「术语澄清 / ¥1500」裁定的依据。 |
| ④ 本次本地源码审计 | 本 ADR 新增：对隔离 clone 的 `Read`/`Grep` 逐字阅读 | 证据全部带本地 `路径:行号`，汇总于 `docs/UPSTREAM_AUDIT.md`。 |

**采信原则**：① 本地源码（方④）是**可复核的一手证据**，与任何二手摘要冲突时以本地源码为准；② GitHub 元数据以 API 实时原值（方②）为准；③ 微信原文的措辞以方③逐字取证为准，本地仓库只提供「不含该字样」的反证；④ 未被任何一手证据支撑的表述一律不写入项目结论；⑤ 上游自测/估算数据不得转写为 BookLeme 结论。

---

## 2. 四方收敛性比较表

> 「本地证据」列全部指向 `$UPSTREAM_REF/` 下的文件，行号为本次 clone 实际行号。
> 分类：**一致**（四方无冲突）/ **分歧**（存在冲突，已裁定）/ **新发现**（前三方未逐字覆盖、本次本地审计新增）。

| # | 命题 / 结论 | ① 报告族 (A/B/C) | ② GitHub API | ③ 计划模式逐字复核 | ④ 本次本地源码审计 | 分类 | 采信与否及理由 | 本地证据（路径:行号） |
|---|---|---|---|---|---|---|---|---|
| 1 | 仓库 MIT / Python / master；**37,244 stars、3,942 forks** | A/B/C 有 1.2k / 1.7k / 2.7w 等过时摘要 | **原值 37,244 / 3,942** | 采信 API 原值 | 本地目录内无 star/fork 数据（GitHub 元数据不入库），无从反证 | **分歧（已裁定）** | **采信 API 原值 37,244 stars / 3,942 forks**；WebSearch 的 1.2k / 1.7k / 2.7w 判为过时摘要，不采信 | `docs/UPSTREAM_AUDIT.md §4`；`LICENSE.md`（MIT） |
| 2 | 本质 =「**确定性 ETL + 一份写给宿主 LLM 的巨型操作规程 SKILL.md + 质量工具**」 | A/B/C 完全一致 | — | 已逐字核验 | **权威确认** | **一致** | **采信**。这是全项目最重要的架构判断，本地有一手明文 | `AGENTS.md:7-12`（「two distinct halves: a deterministic Python extractor ... and a spec-driven generator (SKILL.md) executed by an agent」）；`cli.py:17-30`；`SKILL.md:92-814`（Step 0–11 巨型规程） |
| 3 | **Python 代码零 LLM API 调用**，智能在宿主 Agent 推理里 | A/B/C 一致 | — | 「已逐字核验」 | **确认，但需加限定语** | **一致（精确化）** | **采信并精确化**：当前已提交的生产抽取器 + `tools/` 全部零 LLM；但评测规划允许 live 模型（见 #23）。准确表述见「被推翻或需要修正的结论」C1 | 全仓 `*.py` Grep 无 `openai/anthropic/requests./httpx/urllib.request/genai/litellm`；`config.py:47-57`（依赖全是本地解析库）；`epub.py:9`（`urllib.parse` 仅路径解析）；`subprocess` 仅 `pdftotext/pdfinfo/ebook-convert/pip/git`；`AGENTS.md:7-12` |
| 4 | 提取产物 `full_text.txt` + `metadata.json`（sha256、20+ 语言章节检测、扫描版早停、Unicode 消毒） | A/B/C 一致 | — | 已核验 | **确认并细化** | **一致** | **采信**，细节以本地为准（见 #17/#18/#19） | `utils.py:1403-1660`（`extract_single_file`）、`:1319-1325`（`_sha256_file`）、`:1615-1626`（消毒）、`:1628-1635`（tokens/structure/outline）；`config.py:28-29` |
| 5 | 宿主按 **Step 0–11** 走、**5 处强制停人**、`grep/sed` 切片、逐章提炼 | A/B/C 一致 | — | 已核验 | **确认，逐处定位** | **一致** | **采信**。5 处强制停人是上游设计特性，BookLeme 前移为启动参数（差异化清单第 5 条） | `SKILL.md:118`（Step1.5）、`:294`（Step2.5）、`:364`（Step4）、`:636`（Step9.5）、`:778`（Step11 可见性）；切片 `SKILL.md:309-315` |
| 6 | 产出固定 5 文件 + `SKILL.md <4K` + Topic Index 路由 + 渐进式披露三级 | A/B/C 一致 | — | 已核验 | **确认** | **一致** | **采信**。`Voice calibration` 是散文概念无字段，印证差异化清单第 4 条 | `SKILL.md:50`（SKILL.md + chapters/ + glossary + patterns + cheatsheet）、`:877`（first 5,000 tokens）、`:878`（on-demand 章文件）、`:880`（Topic index）、`:613`（full_text 本地不随包）、`:30-35`（Voice calibration 仅概念） |
| 7 | 编译期 vs 运行期分离；渐进式披露三级（常驻 SKILL.md → 按需 chapters → 本地全文） | A/B/C「核心原理三项完全一致」 | — | 已核验 | **确认** | **一致** | **采信**，作为 BookLeme 保留原理① ② | `docs/architecture.md:71`；`SKILL.md:877-880`、`:613` |
| 8 | 提炼**结构而非摘要**、保留作者精确命名、`cheatsheet` 装作者判断力（When X, do Y, because Z） | A/B/C 一致 | — | 已核验 | **确认为「设计立场」，非验证结论** | **一致（附定性）** | **采信为设计原理，但不得当作已验证事实**（见 #12、C5） | `SKILL.md:25`、`:30-37`、`:873-874`、`:539`；`README.md:52` |
| 9 | 确定性提取与概率性生成解耦、sha256 幂等续跑 | A/B/C 一致 | — | 已核验 | **确认，但幂等粒度更粗** | **一致（精确化）** | **采信并精确化**：上游是**整运行级复用**，非按 stage 跳过（见 #22、C6） | `utils.py:1328-1400`（`reuse_is_safe`）、`:1319-1325`；`config.py:5-27`（PID 命名 per-run workdir） |
| 10 | 版权作为设计约束（仓库不含书内容、不抄原文、第三方书默认私有） | A/B/C 一致 | — | 已核验 | **确认** | **一致** | **采信** | `SKILL.md:879`（Never copy raw book text）、`:788`（「synthesized summaries, not the book text」）、`:778`（可见性单独确认）；`AGENTS.md:35`（Never commit raw copyrighted book text） |
| 11 | **「no hallucination」是宣称、无自动回验**（上游缺口） | A/B/C 指出缺口 | — | 计划第 2 节列为缺口 | **本地铁证：全仓无任何 groundedness / 引文 / claim ledger / 覆盖率门** | **一致** | **采信缺口成立**。这是 BookLeme fidelity 层（第 6 节 7 指标）的立足点 | 宣称：`README.md:53`、`:70`、`docs/faq.md:50-52`；无回验：`tools/evals/score.py:2/27`、`tools/validate_skill.py:213-291`、`tools/scan_generated_skill.py:2`；`docs/UPSTREAM_AUDIT.md §3` |
| 12 | **「结构化框架优于摘要」无验证**（PD-05 = UNVERIFIED） | A/B/C 未涉及 | — | 计划第 2/6 节已标 | **本地明确禁止当成事实** | **一致** | **采信并强化**：上游自己把它列入 Claims guardrail | `docs/research/progressive-disclosure-evals.md:40`（论文未验证当前语义表示）、`:54`（开放问题）、`:365-395`（PD-05 实验，`:394` 零结果有效）、`:577`（guardrail 点名）、`:556`（PD-05 状态） |
| 13 | **PD-04~PD-12 全部 BLOCKED** | A/B/C 未涉及 | — | 计划第 2/6/12 节已标 | **逐条确认** | **一致** | **采信**。PD-00~03 = DONE，PD-04~12 = BLOCKED，共 9 条 | `docs/research/progressive-disclosure-evals.md:210-222`（任务台账）、`:551-563`（证据台账） |
| 14 | 上游 **24×–51× 自测数据** 与 **2.4×–15.6× 模型估算** 的性质 | A/B/C 提及 | — | 计划第 6 节已定性 | **本地确认，并发现第三个数字（论文 ~2×）** | **一致（补充）** | **采信定性，禁止转写成本项目结论**（见 C7） | `docs/performance.md:2`、`:44-46`、`:52-55`（24–51× self-reported / 2.4–15.6×「a model」）、`:59-70`（~$1/book 估算）；`docs/research/progressive-disclosure-evals.md:42`、`:573`（K=20 En.QA ~2× 条件特定，不得通用化） |
| 15 | **star 分歧裁定**（1.2k / 1.7k / 2.7w 过时） | A/B/C 分歧 | **37,244** | 已裁定 | 本地无反证 | **分歧（已裁定）** | **采信 API 原值**；见 #1 | `docs/UPSTREAM_AUDIT.md §4` |
| 16 | **Harness 术语澄清**；**¥1,500 未见于原文** | 报告曾误引「Harness 平台」 | — | 两篇微信原文逐字取证：载体是 **AlphaEngine / AlphaClaw 的 Skill 市场**；「Harness Engineering」是另一套方法论；¥1500、积分、Token 无限量、仅限机构投资者等表述的定位裁定 | **本地反证：仓库内 `harness` 全是通用名词（评测/代理运行器），无任何「Harness 平台 / Skill 市场 / 积分」字样；全仓无 ¥1500** | **分歧（已裁定）** | **采信方③裁定**，并由方④本地反证加固。以上不写入项目结论 | `tools/evals/manifest.py:158`/`:168`（`harness_id`）、`tests/evals/test_manifest.py:25`（`"fixture-harness"`）、`docs/research/progressive-disclosure-evals.md:37`/`:100`/`:348`/`:356`；`docs/UPSTREAM_AUDIT.md §4` |
| 17 | **【新发现】章节检测算法具体规则** | 前三方仅概括「20+ 语言章节检测」 | — | 未逐字 | 20+ 语言/文字正则族；中文 `第X[章回卷节篇讲]`；**康熙归一化两套并存**；**PDF outline 优先**；散文/列表/代码围栏反误判；`chapters_method` 上报 | **新发现** | **采信**，作为 BookLeme 分段多策略的设计输入（不照搬代码） | `utils.py:117-120`、`:149-151`、`:167-191`、`:193-463`、`:488-502`、`:606-725`、`:791-949`、`:1106-1195`、`:1198-1219`；`parsers/pdf.py:187-242`；`tests/test_chapter_numeric_false_positives.py:40-158`、`tests/test_pdf_outline_chapters.py:67-83` |
| 18 | **【新发现】sanitize Unicode 规则成体系** | 前三方仅概括「Unicode 消毒」 | — | 未逐字 | 9 组不可见/格式码点（零宽、Bidi/Trojan Source、Tag Block、变体选择符、乐谱格式…）；**刻意不做整篇 NFKC**；`is_invisible_codepoint` 被扫描器复用为单点真源 | **新发现** | **采信**，并据此修正计划第 6 节表述（见 C2） | `sanitize.py:11-155`、`:158-204`、`:207-248`；`tools/scan_generated_skill.py:28-33`；`tests/test_sanitize_bidi_controls.py`（存在）、`tests/test_sanitize_extracted_text.py:24-97` |
| 19 | **【新发现】降级链细节 / 扫描版是硬中止且无 OCR / 全仓无 pdfplumber** | 前三方概括为「扫描版早停」 | — | 未逐字 | PDF `pdftotext→pypdf→pdfminer`（technical 先 docling）；EPUB `ebooklib→stdlib zipfile`；HTML `trafilatura→bs4→stdlib`；TXT BOM+编码链；扫描版 `looks_image_only` 命中即 `raise ExtractionError`，只提示外部 `ocrmypdf` | **新发现** | **采信**，并据此澄清计划第 8 节（见 C3） | `utils.py:1469-1613`、`:1507-1513`、`:1543-1573`；`parsers/{pdf,epub,html,text}.py`；`dependencies.py:16-77`/`:215-264`/`:340-342` |
| 20 | **【新发现】质量工具与评测工具的真实职责边界** | 前三方概括为「质量工具」 | — | 未逐字 | `validate_skill.py` = 多宿主 **frontmatter 合规**；`scan_generated_skill.py` = **advisory 安全扫描**（退出码 1 仅建议人工复核）；`score.py/replay.py` = 合成轨迹离线打分；`manifest.py` = 可复现清单+密钥守卫；`paper_flat.py` = PD-03 实验基线包；`discovery_tax.py` 自述 *model*。**无一个校验内容忠实度** | **新发现** | **采信**。明确 BookLeme 的 quick_validate/lint/copyright_gate 分工与之不同 | `tools/validate_skill.py:213-291`；`tools/scan_generated_skill.py:2`/`:316-363`；`tools/evals/score.py:26-105`、`replay.py:31-34`、`manifest.py:122-174`、`paper_flat.py:53-91`；`tools/discovery_tax.py:16-24` |
| 21 | **【新发现】上游刻意禁止整篇 NFKC；`utils.py:177` 注释与事实不符** | 未涉及 | — | 未逐字 | `sanitize.py:168-171` 明列整篇 NFKC 会改写全角/连字/带圈数字；两测试断言普通文本逐字节保留；`utils.py:177` 称「NFKC does not map these」，实测 NFKC 确实把 `U+2F00→一` | **新发现** | **采信事实**，作为对计划第 6 节的修正依据（C2）。不采信该注释的说法 | `sanitize.py:158-178`；`tests/test_cjk_radical_normalization.py:54-56`/`:59-75`；`tests/test_sanitize_extracted_text.py:33-40`；`utils.py:174-185`/`:803-805`（本机 `python3 -c` 实测） |
| 22 | **【新发现】幂等粒度是「整运行复用」而非「按 stage 跳过」** | 概括为「sha256 幂等续跑」 | — | 未逐字 | `reuse_is_safe` 判据 = workdir + mode + 全部源「文件名+sha256」一一匹配；`config.py:5-27` 用 PID 隔离并发 | **新发现** | **采信**。确认 BookLeme 第 3 节的 stage 级幂等是更细粒度的自主设计，非上游已有能力 | `utils.py:1328-1400`、`:1319-1325`；`config.py:5-27` |
| 23 | **【新发现】「零 LLM」应加 live-eval 限定语** | 绝对表述 | — | 绝对表述 | 当前代码零 LLM；但 `manifest.py` 有 `models` 字段、PD-03/04 明确允许 live model（离线夹具保证 CI 确定性）、`AGENTS.md:97` 承认 live 实验存在 | **新发现（精确化）** | **采信精确化表述**：「生产期抽取器与当前评测工具零 LLM；规划中的 live 评测在预算内用模型，且仅评测、绝不进运行时」 | `tools/evals/manifest.py:24`/`:146`；`docs/research/progressive-disclosure-evals.md:232`（zero-API baseline）、`:328`、`:352`、`:340-361`；`AGENTS.md:95-104`；`docs/research/progressive-disclosure-evals.md:150`（评测代码不得成运行时依赖） |

**收敛统计**：一致 12 条（#2–#14 中除 #15/#16 外，含 3 条「一致（精确化/补充/附定性）」）、分歧 3 条（#1/#15 同一 star 分歧、#16 术语分歧，均已裁定）、新发现 8 条（#17–#23 及 #14 的补充）。**无一条核心原理被推翻**；需要修正/精确化的是 7 处表述（见下节）。

---

## 3. 被推翻或需要修正的结论（专节）

> 本节是四方比较的**裁决输出**。C1–C4 为「需精确化/澄清」（不是推翻核心结论，而是防止 downstream 文档写错）；C5–C7 为「需修正计划表述」；无一条上游核心原理被推翻。

**C1（精确化，非推翻）「Python 零 LLM API 调用」需加限定语。**
方④确认：现存生产代码与 `tools/` 全零 LLM（全仓 Grep + import 审计 + `AGENTS.md:7-12` 两半架构）。但方④同时发现评测规划明确允许 live 模型：`tools/evals/manifest.py:24/146` 的 `models` 字段、`docs/research/progressive-disclosure-evals.md:328`（PD-03「may require a model in live mode」）、`:352`（`--dry-run ... no model calls`，反证 live 有）、`:340-361`（PD-04 first live harness adapter）、`AGENTS.md:97`（「Live model experiments are expensive」）。
→ **裁定**：计划第 1 节的绝对表述对「当前已提交代码」成立；README/文档宜写成「**生产期抽取器与当前评测工具零 LLM；规划中的 live 评测在预算内使用模型，且仅评测、不进运行时**」。`progressive-disclosure-evals.md:150` 明令评测代码不得成为运行时依赖，可引为佐证。

**C2（需修正计划第 6 节）「NFKC 归一 + 精确子串」不能理解为整篇 NFKC；Kangxi 机制是「两套 + 范围限定」。**
- 上游 `sanitize.py:158-178` **刻意只对 U+2F00–U+2FDF 康熙部首做 NFKC 折叠**，`:168-171` 明列整篇 NFKC 会改写全角、连字、带圈数字、CJK 兼容表意文字；`tests/test_cjk_radical_normalization.py:59-75` 与 `tests/test_sanitize_extracted_text.py:33-40` 断言普通文本**逐字节保留**。
- 另有**第二套**独立机制 `utils.py:174-185` 的硬编码 4 数字映射 `_KANGXI_NUMERAL_TRANS`，在 `:803-805` 用于章节号解析；其 `:177` 注释「NFKC does not map these」经本机 `python3` 实测为**不实**（NFKC 确实把 `U+2F00` 映射为 `一`）。
→ **裁定**：① 计划第 6 节「NFKC 归一」若被实现为对 `full_text.txt` 整篇归一，会与「`R_quote` 是 `full_text.txt` 的**精确子串**」冲突（全角/连字形会失配）。FIDELITY/实现必须**两侧用同一规则归一或依赖 `char_map.json` 反查**（计划已提 `char_map.json`，是正确缓解，但需显式写清「不整篇 NFKC」）。② 描述上游时不得写成「单一 NFKC 机制」。③ 不采信 `utils.py:177` 的注释说法。

**C3（需澄清，防止张冠李戴）计划第 8 节「PDF `pypdf→pdfplumber`」是 BookLeme 自己的链，不是上游的。**
上游实为 `pdftotext(poppler) → pypdf → pdfminer`（`utils.py:1543-1573`），technical 模式先 `docling`（`:1514-1541`、`parsers/pdf.py:257-277`）；**全仓无 `pdfplumber`**。上游扫描版判据是 `looks_image_only`（前 5 页无文本，`utils.py:1507-1513`），命中即 `raise ExtractionError` **硬中止该源**、无内置 OCR（只提示外部 `ocrmypdf`）；计划的 `chars_per_page<50` 是 BookLeme 自定规则。
→ **裁定**：差异化清单「扫描版标 `partial` 不中止 / 无 OCR / 图表文字丢失」本地证据充分且更强（上游是 abort 而非 warn）；但 ARCHITECTURE/文档描述提取链时须区分「上游现状」与「BookLeme 设计」，勿把 `pdfplumber` 写进上游结论。

**C4（需澄清，非矛盾）PD-05 状态口径。**
上游把 PD-05 标 `BLOCKED`（`progressive-disclosure-evals.md:215`、`:556`），BookLeme 计划把「结构化框架优于摘要」这一**假设**在自家未验证假设表标 `UNVERIFIED`、PD-04~PD-12 保持 `BLOCKED`。
→ **裁定**：两者是「研究任务状态」与「假设认知状态」两种口径，不矛盾；ADR-003 与 FIDELITY/EVALS 文档须写明这一区分，避免读者误以为自相矛盾。

**C5（需修正「原理」与「验证」的混淆）「提炼结构而非摘要」是设计立场，不是被验证的结论。**
`SKILL.md:25/30/873`、`README.md:52` 是散文立场；`progressive-disclosure-evals.md:40`（论文未把当前语义表示作为自变量）、`:54`（开放问题）、`:577`（Claims guardrail 点名）、`:365-395`（PD-05 BLOCKED，`:394`「A null result is a valid outcome」）证明**零实验验证**。
→ **裁定**：BookLeme 可把它作为**借鉴的设计原理**吸收，但所有文档/README **不得**表述为「已验证结构化框架优于摘要」。

**C6（需精确化差异化清单）「sha256 幂等续跑」上游是整运行级复用。**
`utils.py:1328-1400` `reuse_is_safe` 只在「workdir 存在 + mode 未变 + 全部源文件 sha256 匹配」时复用整个 workdir；`config.py:5-27` 用 PID 隔离并发。BookLeme 第 3 节的**按 stage 跳过**（`state.json` + `input_sha256`）是更细粒度的自主设计。
→ **裁定**：差异化清单第 4 条「sha256 幂等续跑」应注明「借鉴其确定性/指纹思想，但粒度从整运行提升到 stage 级」。

**C7（需补充，防止数字被误用）上游存在三个不同性质的性能数字，不止两个。**
`docs/performance.md:2/44-46/52-55`：`24×–51×` = context-dump 优势（上游基于实测 token 数的**自测/自报**）；`2.4×–15.6×` = discovery-loop 优势，原文 `:54-55` 自述「a **model** using the book's real ToC/chapter sizes」；此外 `progressive-disclosure-evals.md:42`、`:573` 还点名论文的 `~2×`（K=20 En.QA `68.3M` vs `32.5M`）是**条件特定的未缓存测量，不得通用化**，guardrail 明令不得发布「book-to-skill uses 2x fewer tokens」。
→ **裁定**：按计划第 6 节禁令，**上述任何数字都不得转写为 BookLeme 结论**；BookLeme 只报告 `evals/baseline.json` 中自己实测的数字（本阶段为 BLOCKED 占位）。引用时必须原样标注来源与性质（自测 / 模型估算 / 条件特定论文结果）。

---

## 4. 术语与元数据的最终裁定

1. **star 数**：以 **GitHub API 实时原值 37,244 stars / 3,942 forks** 为准（方②）。WebSearch 返回的 `1.2k / 1.7k / 2.7w` 判为过时摘要，**不采信**（方①分歧，已裁定）。本地 clone 不含 star/fork 元数据，方④无法也无需反证。
2. **Harness 术语澄清**（采信方③逐字取证 + 方④本地反证）：两篇微信原文**均无「Harness 平台」字样**；载体是 **AlphaEngine / AlphaClaw 的 Skill 市场**（发布过审 +2000 积分、每被调用 +100 积分、受欢迎可 Top 模型 Token 无限量、仅限机构投资者）；检索到的「Harness Engineering」是另一套「让 AI 长时无人值守执行」的工程方法论。本地仓库内 `harness` 全部是通用名词（`tools/evals/manifest.py:158/168` 的 `harness_id`、`tests/evals/test_manifest.py:25` 的 `fixture-harness`、`progressive-disclosure-evals.md:37/100/348/356` 的「评测/代理运行器」），**无任何「Harness 平台 / Skill 市场 / 积分」字样**，本地证据支持该澄清。**以上不写入项目结论**。
3. **¥1,500/小时心理咨询**：方③逐字取证确认微信原文与转载均**未出现**，属用户的定位概括；方④全仓 Grep 亦无此字样。**不采信、不写入项目结论**。

---

## 5. 采信汇总（写入 BookLeme 设计输入的上游原理）

| 原理 | 裁定 | 本地一手证据 |
|---|---|---|
| ① 编译期 vs 运行期分离（查询只加载 ~5K token） | 采信 | `docs/architecture.md:71`、`SKILL.md:877-880` |
| ② 渐进式披露三级（SKILL.md → chapters → 本地全文） | 采信 | `SKILL.md:613`、`:878`、`:880` |
| ③ 提炼结构而非摘要、保留精确命名、cheatsheet 装判断力 | 采信为**设计原理**（非验证结论，见 C5） | `SKILL.md:873-874`、`:539` |
| ④ 确定性提取与概率性生成解耦、sha256 幂等 | 采信（粒度精确化，见 C6） | `AGENTS.md:7-12`、`utils.py:1319-1400` |
| ⑤ 版权作为设计约束 | 采信 | `SKILL.md:879`、`:788`、`AGENTS.md:35` |

**不采信 / 不转写**：`24×–51×`、`2.4×–15.6×`、论文 `~2×`、`~$1/book`、「no hallucination」、「结构化框架优于摘要（已验证）」、「Harness 平台」、¥1500、过时 star 数。

---

## 6. 实现约束记录（本机环境，必读）

> 本节记录**已核实的本机环境事实**，它直接决定 BookLeme 的实现选型，并已同步给负责 M1 设计文档的代理。

**核实命令与结果**（2026-11-08，本机）：

```
$ python3 --version
Python 3.13.12
$ python3 -c "import yaml, jsonschema, pytest, jinja2"
yaml MISSING / jsonschema MISSING / pytest MISSING / jinja2 MISSING
```

本机所有 Python 解释器均**缺** `yaml` / `jsonschema` / `pytest` / `jinja2`。据此冻结以下实现约束：

1. **核心引擎零第三方依赖**：`bookleme/` 核心库只用 Python 标准库，不 import 任何第三方包、不 import 任何宿主 SDK（与计划第 9 节「依赖方向单向」一致，并由上游 `AGENTS.md:36`「评测工作避免新增运行时依赖」、`:7-12` 两半架构佐证）。
2. **配置文件采用 JSON，等效于计划的 `router.yaml` 语义**：计划中的 `configs/router.yaml`、`configs/default.run.yaml` 在本机改为 `configs/router.json`、`configs/default.run.json`（键、权重表、阈值、优先级语义完全等价，仅序列化格式不同）。理由：无 `yaml`，JSON 由标准库 `json` 原生支持、可 diff、可哈希、可被 `state.json` 的 `input_sha256` 直接纳入。所有提及 `router.yaml` 的文档/代码需按此替换。
3. **测试用标准库 `unittest`**：不依赖 `pytest`；CI 里以 `python3 -m unittest discover` 为默认测试命令。
4. **渲染用标准库字符串模板**：`render/` 用 `string.Template` / `str.format` 风格的确定性模板，不依赖 `jinja2`；插件 `render(ctx)` 契约不变。
5. **schema 文件仍是标准 JSON Schema**：`schemas/*.schema.json` 保持标准 JSON Schema 语法（`type/properties/required/...`），不因本机缺 `jsonschema` 而降级成私有格式。
6. **可选依赖已装在 `.vendor/` 做双保险**：`$ROOT/.vendor/` 已备妥 `yaml (PyYAML 6.0.3)` / `jsonschema (4.26.0)` / `pytest (9.2.0)` / `jinja2 (3.1.6)` 及依赖（`markupsafe / attrs / referencing / rpds / pluggy / iniconfig / packaging / pygments`）。用途**仅限**：① 调用本机官方 `quick_validate.py`（需 `yaml`）校验产物 frontmatter；② 用 `jsonschema` 加载并校验 7 个 schema 与样例；③ 用 `pytest` 做第二套测试跑法（双保险）。通过 `PYTHONPATH=.vendor` 或显式 `sys.path` 注入使用，**核心运行时绝不依赖 `.vendor/`**。
7. **分工不变**：本机官方 `quick_validate.py` 只管 frontmatter 白名单/name/description（计划第 7 节），五段式/Gotchas/触发词/≤500 行由自有 `validate/lint.py` 承担；`copyright_gate.py` 全确定性。

**影响面提醒**：M1 的 `configs/*.yaml` → `*.json`、M2 的 `tests/` 用 `unittest`、M3 的 `render/` 用标准库模板，均需按本约束落地；负责设计文档的代理已在本次协作中同步。

---

## 7. 结论

- 三份独立报告 + GitHub API 复核 + 计划模式逐字复核 + 本次本地源码审计，**四方在全部核心原理上收敛**，无核心结论被推翻。
- 三项分歧（star 数、Harness 术语、¥1500）按计划第 1 节原裁定采信，并由本地证据加固；八项新发现补强了章节检测、Unicode 消毒、降级链、质量门、评测边界的实现细节。
- 七处需精确化/修正的表述（C1–C7）已列出，供主代理修订计划措辞与 downstream 文档：其中 **C2（NFKC 范围）** 与 **C3（pdfplumber 张冠李戴）** 是必须修正的实现相关项，**C7（三类性能数字）** 是必须严守的禁令。
- 本 ADR 与 `docs/UPSTREAM_AUDIT.md` 共同构成 M0 研究对齐的全部证据；**未导入任何上游代码、未修改参考目录、未把书籍原文写入仓库**。

---

## 8. M2/M3 落地后的最终裁决（主代理定稿，以代码为准）

以下口径覆盖计划与早期设计文档中的歧义表述，后续实现与维护以此为准：

| 议题 | 最终裁决 | 代码 / 文档落点 |
|---|---|---|
| `genre_id` 正则 | `^[a-z0-9][a-z0-9_-]*$`（**允许下划线**），与插件文件名严格同名；原因是 `configs/router.json` 的体裁键为 `coach_dialogue` 等下划线写法 | `plugins/validator.py`、`docs/PLUGIN_SPEC.md` |
| SKILL.md frontmatter `name` | 仍严格 `^[a-z0-9-]+$`（如 `book-a4add8d6-bs`），由渲染层保证，与插件 id 职责分离 | `render/skill.py` |
| PD 系列状态 | **PD-05 单列 `UNVERIFIED`**；PD-04 与 PD-06~PD-12 为 `BLOCKED` | `fidelity/report.py`、`docs/FIDELITY.md`、ADR-003 |
| `state_machine` | 字段对全部插件必填；behavior 插件必须填内容并通过可达性检查，纯 knowledge 插件可置 `null` | `plugins/validator.py` |
| **C2（NFKC 范围）已落地** | `extract/base.py::normalize` **不整篇 NFKC**，只剥离不可见控制字符，并仅折叠康熙部首 `U+2F00–U+2FDF` 与 CJK 兼容表意文字 `U+F900–U+FAFF`；据此失效缓存重跑全部批次 | `extract/base.py`、`tests/test_bookleme.py::test_normalize_is_scoped_not_whole_text_nfkc` |
| 中间 IR 落点 | 共享 IR 在 `cache/<book_sha256 前 12 位>/`；`out/<run_id>/` 只放本次产物与报告 | `pipeline.py`、`docs/ARCHITECTURE.md`「M2 实现口径校正」 |
| 断点续跑实测 | 删 S5 输出重跑：S0–S4 全 SKIP、仅 S5 重算、S6/S7/S9 因 `input_sha256` 未变而 SKIP | `logs/M0-M2/run-smoke-002.log`、`docs/ACCEPTANCE-M0-M3.md` |
| 本批评测数字 | **仅合成书样本**，不得外推；`coverage_score = 0.6667` 低于 0.85 目标，如实记录不调参掩盖；`groundedness` / V2 / V3 为 `null` | `out/smoke-001/metrics.json`、`docs/ACCEPTANCE-M0-M3.md` |
| **C1「零 LLM 调用」口径** | 上游**生产期抽取器与当前评测工具**的 Python 代码零 LLM API 调用，生成靠宿主 Agent 推理；但规划中的 live 评测 harness 允许模型，故不得笼统写成「全仓任何地方无模型调用」。本项目本批同理，LLM judge 是后续接口 | `README.md`、`docs/UPSTREAM_AUDIT.md` |
| **C3 提取链归属** | `pypdf→pdfplumber` 是**计划对 BookLeme 自身链的描述且描述有误**（实际只有 `pypdf`）；上游实为 `pdftotext→pypdf→pdfminer`、technical 模式 `docling`，全仓无 `pdfplumber`，扫描版 `raise ExtractionError` 硬中止。已分别写清「上游现状」与「我方实现」 | `docs/ARCHITECTURE.md` S1 行、`README.md` 差异表、`docs/UPSTREAM_AUDIT.md` |
| **C5 不得宣称已验证** | 「提炼结构而非摘要」只是设计选择；上游 PD-05 任务状态 `BLOCKED`，我方认知状态 `UNVERIFIED`。README 原「三条已被验证的原理」已改为「工程上采纳、但未经本项目验证」 | `README.md`、`docs/FIDELITY.md`、ADR-003 |
| **C6 幂等粒度** | 上游 `reuse_is_safe()` 是**整运行级**复用（每源 filename+sha256 全匹配）；BookLeme 是 **stage 级** `input_sha256` + `should_skip`，删某 stage 输出只补该 stage，粒度不同不可混称 | `README.md` 差异表、`state.py`、`pipeline.py` |
| **C7 三类性能数字禁令** | ① 上游 `24×–51×` 自测 ② `2.4×–15.6×` 模型估算 ③ 论文 `~2×` 仍 `BLOCKED`；另加其约 `$1/书` 成本估算，**四类一律不得转写为本项目结论** | `README.md`、`fidelity/report.py` 的 `unverified_assumptions`、ADR-003 §9 |

**本机实现基线补充**：14 项 `unittest` 全过；官方 `quick_validate.py` 经 `PYTHONPATH=.vendor` 调用返回 `Skill is valid!`；两个产物 `quick_validate` / `lint` / 6 条版权硬门全过；`python3 -m bookleme schema --state` 通过。
