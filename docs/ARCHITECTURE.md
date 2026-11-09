# BookLeme 架构说明（M1 设计冻结）

> 状态：M1 设计冻结。本文定义 BookLeme 的 stage DAG、幂等模型、共享 IR、可观测性纪律与 v1 范围锚定。
> 前缀约定：`$ROOT = /Users/bertram/Desktop/BookLeme`。本文所有相对路径均以 `$ROOT` 为基准；真源安装路径为唯一例外，单独以绝对路径列出。

---

## 0. 本机硬约束与实现基线（M1 冻结，必须遵守）

本机所有 Python 解释器均**缺少** `yaml` / `jsonschema` / `pytest` / `jinja2`。M1 冻结据此把核心引擎定为**零第三方依赖**，并作出以下与早期草稿等价的替换：

| 早期草稿 | M1 冻结实现 | 语义等价性 |
|---|---|---|
| `configs/router.yaml`、`configs/default.run.yaml` | `$ROOT/configs/router.json`、`$ROOT/configs/default.run.json` | 配置结构、字段、权重、阈值一一对应，仅序列化格式由 YAML 改为 JSON |
| 运行时 `jsonschema` 校验 | 内置子集校验器（支持 `required` / `type` / `enum` / `minimum` / `maximum` / `minLength` / `maxLength` / `pattern` 子集） | `$ROOT/schemas/*.schema.json` 仍是**标准 JSON Schema** 文件；安装了 `jsonschema` 的环境可直接加载同一份文件，无依赖环境走内置子集，覆盖本项目 schema 用到的全部关键字 |
| `pytest` | 标准库 `unittest`（`$ROOT/tests/test_*.py`，`python -m unittest discover`） | 测试用例与断言一一对应 |
| Jinja2 模板 | 标准库字符串模板（`string.Template` / `str.format` 风格），由插件 `section_template` / `skill_template` 承载 | 占位符替换语义等价，不引入模板引擎依赖 |
| 可选第三方依赖 | 统一装在 `$ROOT/.vendor/`，经 `PYTHONPATH` 按需注入，核心路径不 import | 本机 `.vendor/` 已备 PyYAML 6.0.3 / jsonschema 4.26.0 / pytest 9.2.0 / jinja2 3.1.6，**仅**供官方 `quick_validate.py`、`jsonschema` 校验样例、`pytest` 双保险使用；核心运行时零依赖，纯净解释器下可完整跑通 `bookleme run --input <合成书> --dry-run` |

**S4 能力抽取的本批实现口径（如实声明，禁止夸大）**：本批 M2 的 S4 采用**确定性抽取器**——合成书用 `[CAP]` 块加 `R: / I: / A1: / A2: / A3: / B:` 六字段标记（`bookleme/capabilities/extract.py::_parse_markup`），无标记时回退为按标题的启发式卡片（`_heuristic`）。**LLM 抽取器尚未实现**：`bookleme/llm/__init__.py` 只有 `LLM_AVAILABLE = False` 占位，`bookleme/llm/client.py` 与 `CapabilityExtractor` Protocol 在本批均不存在。S2 消歧、S3 歧义取证、S5 V2/V3 judge、S9 judge 全为确定性兜底（`router/ambiguity.py` 显式记录 `llm_judge_invoked: false`），相关结论标 `heuristic` 且值为 `null`。**未验证「框架优于摘要」**。

**归一规则（M2 修正，来自上游源码证据）**：`extract/base.py::normalize` **不整篇 NFKC**；只剥离不可见控制字符，仅对康熙部首 `U+2F00–U+2FDF` 与 CJK 兼容表意文字 `U+F900–U+FAFF` 做折叠。依据是 `_reference/book-to-skill/book_to_skill/sanitize.py:168-176` 与其 `tests/test_cjk_radical_normalization.py:59-75`：整篇 NFKC 会改写全角形式、连字、带圈数字，破坏逐字引文的精确子串校验。回归测试 `test_normalize_is_scoped_not_whole_text_nfkc` 锁死该行为。

### M2 实现口径校正（文档与代码的最终对齐，以代码为准）

| 计划 / 本文早期表述 | M2 实际实现 |
|---|---|
| `out/<run_id>/normalized/full_text.txt`、`sources.json`、`segments.json`、`capabilities.json` 等中间 IR | **`cache/<book_sha256 前 12 位>/`**（跨 run 共享 IR）；`out/<run_id>/` 只放本次渲染产物与报告 |
| `cache/<sha12>/provenance_manifest.json` | **移到 `out/<run_id>/provenance_manifest.json`**：该 manifest 含 `run_id` / `generated_at`，写在共享缓存会被不同 run 覆盖导致追溯串味；`sources.json` 则用稳定 `run_id`（`shared-<sha12>`）+ 文件 mtime，保证跨 run 内容不变；`state.json` 阶段记录仍是 **per-run**（新 `run_id` 会重走各 stage，属设计行为），同一 `run_id` 重跑才全量跳过 |
| `out/<run_id>/verification.json`、`regen_queue.json`、`plugin_scan.json` | 本批未生成（接口占位）；S5 实际产出 `capabilities_verified.json` / `claim_ledger.json` / `fidelity_report.json` |
| `out/sessions/<slug>/<session_id>/state.json` | 技能包提供 `scripts/state_io.py` 与 `state/schema.json`，运行期目录由调用方传入；本批未产生会话数据 |
| 根目录 `round-tracker.md` / `claim-ledger.md` / `feedback.jsonl` | 本批根目录只有 `state.json` / `tasks.json` / `progress.md` / `ITERATION_LOG.md`；其余留 M4 |
| 八格式全部可用 | 已实现 txt/md/html/pdf/epub/docx/rtf（7 种）；MOBI/AZW3 依赖 Calibre，缺失时标 `deferred` 且不中止 |
| `bookleme fetch` 子命令 | 本批 CLI 未实现；公开源经 `sources/public/*.json` 落盘后由 S0/S1 读取 |
| 合成书 `[[R_quote]]` 等块标记 | 实际为 `[CAP]` + `R:` 六字段格式，见 `evals/cases/synthetic/coach_book.md` |

### 落盘路径约定（M1 冻结）

- 全局状态/进度（跨运行、位于根目录）：`$ROOT/state.json`、`$ROOT/tasks.json`、`$ROOT/progress.md`、`$ROOT/ITERATION_LOG.md`、`$ROOT/ITERATION_LOG.md`；`round-tracker.md` / `claim-ledger.md` 为 M4 规划，本批未生成。
- 单次运行产物与报告：`$ROOT/out/<run_id>/`；**共享中间 IR 在 `$ROOT/cache/<book_sha256 前 12 位>/`**（见上方「M2 实现口径校正」）。
- 渲染产物：`$ROOT/out/<run_id>/build/knowledge/<slug>/`、`$ROOT/out/<run_id>/build/behavior/<slug>/`。
- 缓存：`$ROOT/cache/<input_sha256前12>/`；LLM 响应缓存键 `sha256(prompt+model+slice)`，同样落在 `$ROOT/cache/`。
- 日志：`$ROOT/logs/<M>/run-<run_id>.log`（`<M>` ∈ `M0..M5`）。
- 公开源落盘：`$ROOT/sources/public/<sha256(url)>.json`（`bookleme fetch` 为 M4 规划，本批由调用方落盘；S1 起核心只读本地文件）。
- 运行期会话状态：`$ROOT/out/sessions/<slug>/<session_id>/state.json`（写前读 + session 级文件锁 + `resume` 续聊），技能包保持只读干净。
- 安装真源（唯一写到工作区之外的例外）：knowledge_pack → `/Users/bertram/Desktop/skills/06-知识与学习/<中文显示名（english-kebab）>/`；behavior_skill → `/Users/bertram/Desktop/skills/01-AI增强/<中文显示名（english-kebab）>/`。`~/.workbuddy/skills`、`~/.codex/skills` 为整目录软链接，写真源后自动可见、绝不改动；`~/.claude/skills` 为真实目录，逐条补绝对路径软链接，写前检查、不覆盖。

---

## 1. Stage DAG（S0–S9）

### 1.1 拓扑

```
S0 Intake ─► S1 Extract ─► S2 Segment ─┬─► S3 Router ──────────┐
 (det)       (det,内并行)  (det+LLM消歧) │   (det+LLM 只读取证)    │
                                        └─► S4 Capabilities ─────┼─► S5 Fidelity ─► S6 Render ─► S7 Validate ─► S8 Install ─► S9 Eval
                                            (确定性抽取器/LLM未实现) ┘   (det+judge)    (det+插件)      (det)         (det)      (det+LLM)
```

S0→S1→S2 串行；**S3 ‖ S4 并行**（都以 S2 为输入）；S5 等二者汇合；S6→S7→S8 串行；S9 最后。可并行维度：S1 按源、S2 按段、S4 按段（主力加速点）、S5 按 claim、S6 两引擎、S9 按 case。

### 1.2 执行者标注约定

- **确定性 Python（det）**：本批已实现，零第三方依赖，输出可复现、可 diff。
- **可插拔 LLM 接口**：**设计上预留为可插拔接口，本批代码未实现该接口文件，留待后续批次接入**；本批 M2 以确定性兜底运行（`bookleme/llm/client.py`、`CapabilityExtractor` Protocol 均不存在，只有 `LLM_AVAILABLE = False` 占位）。文档中凡标此者不代表已实现 LLM 推理。

### 1.3 各阶段输入 / 输出 / 执行者 / 失败降级（完整表）

| Stage | 输入（绝对路径） | 输出（绝对路径 + 关键字段） | 执行者 | 失败 / 降级 |
|---|---|---|---|---|
| **S0 Intake** | CLI `--input <本地有权文件路径...>`；`$ROOT/configs/default.run.json`；已落盘公开源 `$ROOT/sources/public/*.json` | `$ROOT/out/<run_id>/sources.json`（`[{source_id, origin, kind, path, url, sha256, tier, license_note, retrieved_at}]`）；`$ROOT/out/<run_id>/provenance_manifest.json` 骨架；`$ROOT/state.json`（初始化）；`$ROOT/out/<run_id>/degradation_log.json`（有降级时） | 确定性 Python | 无读权限 → abort 该源，记 `degradation_log.json`，其余源继续；`user_rights=unknown` 不在 S0 中止，留到可分发性判定（COPYRIGHT.md 第 4 节） |
| **S1 Extract** | `$ROOT/out/<run_id>/sources.json` 中各 `path`（本地文件）与 `$ROOT/sources/public/*.json`（公开源） | `$ROOT/out/<run_id>/normalized/full_text.txt`；`$ROOT/out/<run_id>/char_map.json`；`$ROOT/out/<run_id>/toc.json`；`$ROOT/out/<run_id>/extraction_report.json`（`extract_status`、`figure_text_lost[]`、`ocr_used`） | 确定性 Python（OCR 可选子进程，默认 `--ocr none`） | 扫描版 → `extract_status=partial` + tier 降 1，**不中止**；八格式降级链（**均为 BookLeme 标准库 / 可选依赖的自有实现，与上游提取链无关**）：PDF `pypdf`（可选依赖，缺失标 `deferred`；`chars_per_page<50` 判扫描版并标 `partial`，不中止）、EPUB `zipfile` + 标准库 XML 解析 `toc.ncx`、DOCX `zipfile` + `xml.etree` 取 `w:t` 与标题样式、HTML `html.parser`、MD/TXT 编码逐编码重试、RTF 手写正则去控制字、MOBI/AZW3 依赖 `ebook-convert`（缺失标 `deferred`）；图表文字本批不抽取，统一记 `figure_text_lost`。**该降级链为 BookLeme 自有实现，非上游**：上游为 `pdftotext(poppler)→pypdf→pdfminer`（`utils.py:1543-1573`）、technical 模式用 docling（`utils.py:1514-1541`、`pdf.py:257-277`），全仓无 pdfplumber；上游扫描版判据 `looks_image_only`（前 5 页无文本，`utils.py:1507-1513`）直接 raise `ExtractionError` 中止该源、无内置 OCR——本项目的「`partial` 不中止 + 可选 OCR 子进程」正是差异化点（上游证据详见 `docs/UPSTREAM_AUDIT.md`） |
| **S2 Segment** | `$ROOT/out/<run_id>/normalized/full_text.txt`、`char_map.json`、`toc.json` | `$ROOT/out/<run_id>/segments.json`（`[{segment_id, heading, level, char_range, token_est, confidence, method}]`）；`$ROOT/out/<run_id>/slices/seg-XXX.md` | 确定性 Python 为主；`confidence<0.6` 时预留「有界消歧接口」调用点（设计上预留为可插拔接口，**本批代码未实现该接口文件**，留待后续批次接入；本批确定性兜底） | 多策略（ToC + `第X章/第X节/Part/一、/##` + 字号缩进 + 中文标题，**不依赖 "Chapter N"**）全失败 → `window_fallback`（1500 token 窗口 / 200 overlap）标低置信 |
| **S3 Router** | `$ROOT/out/<run_id>/segments.json`、`$ROOT/out/<run_id>/slices/`；`$ROOT/configs/router.json`（12 特征 cap / 4 体裁权重 / prior / hard_gate_bonus / margin 阈值 0.15）；`$ROOT/configs/default.run.json`（`--engine` / `--genre` / `--no-router` 覆盖） | `$ROOT/out/<run_id>/router_result.json`（`engines[]`、`genres[]`、`reason`、`override_source`）；`$ROOT/out/<run_id>/router_evidence.json`（歧义时：段号、切片路径、3 judge 输出） | 确定性 Python 加权（`score[g]=Σ w[g][f]·norm(f)+prior[g]+Σ hard_gate_bonus`，`norm(f)=min(1,raw/cap)`）；歧义（`margin=top1-top2<0.15`）时预留「只读取证接口」调用点（设计上预留为可插拔接口，**本批代码未实现该接口文件**，留待后续批次接入；本批确定性兜底） | 歧义 → ① 固定种子抽 8 段、3 个独立 judge 打体裁标签、每票 `+0.10`、全部证据落 `router_evidence.json`，reviewer **只读原始切片不读摘要**；② 仍不足 → `engines=["knowledge_pack","behavior_skill"]`、`genres=[top1,top2]`、`reason="ambiguous_dual_output"`，**自动双引擎，不停人** |
| **S4 Capabilities** | `$ROOT/out/<run_id>/segments.json`、`$ROOT/out/<run_id>/slices/`；插件 `capability_schema`（`$ROOT/bookleme/plugins/builtin/<genre_id>.py` 或 `--plugin-dir`）；`$ROOT/bookleme/llm/prompts/*.md`（版本化，供后续 LLM 接入） | `$ROOT/out/<run_id>/capabilities.json`（`[{capability_id, title, genre_tags[], engine_targets[], source_id, span, ria, claims[], checks, confidence, status}]`）；`$ROOT/schemas/capabilities.schema.json` 校验通过记录 | **本批 = 确定性抽取器**（合成书 `[CAP]` + `R:/I:/A1:/A2:/A3:/B:` 六字段标记切分，见 §0）；LLM 抽取器设计上预留为可插拔接口，**本批代码未实现该接口文件**，留待后续批次接入；未验证「框架优于摘要」 | 单段重试 2 次 → `uncovered`，计入 `coverage_score` 扣分，**不阻塞** |
| **S5 Fidelity** | `$ROOT/out/<run_id>/capabilities.json`、`normalized/full_text.txt`、`char_map.json`、`segments.json` | `$ROOT/out/<run_id>/claim_ledger.json`；`$ROOT/out/<run_id>/verification.json`；`$ROOT/out/<run_id>/fidelity_report.json`（7 指标，每条带 `metric_type`）；`$ROOT/out/<run_id>/regen_queue.json` | 确定性 Python 检查（逐字引文**受限归一，不整篇 NFKC** / 去不可见字符 / char_map 反查 / 精确子串、shingle、6 条不抄原文硬检查）为主；V1/V2/V3 的 judge 部分设计上预留为可插拔接口、**本批代码未实现该接口文件**，留待后续批次接入（本批确定性兜底，judge 结论标 `heuristic` 且值为 `null`） | `invalidated` 入 `regen_queue.json`，Generator→Evaluator→Re-generator ≤3 轮；仍不过 → capability `status=rejected` |
| **S6 Render** | `$ROOT/out/<run_id>/capabilities.json`（按 `engine_targets` 过滤）、`claim_ledger.json`；插件 `section_template` / `skill_template`（标准库字符串模板）/ `output_contract` / `render(ctx)`；`$ROOT/configs/router.json`（slug 规则） | `$ROOT/out/<run_id>/build/knowledge/<slug>/`（`SKILL.md` + `references/{topic-index.md, chNN-*.md, glossary.md, patterns.md, cheatsheet.md, provenance.md}`）；`$ROOT/out/<run_id>/build/behavior/<slug>/`（`SKILL.md` + `references/framework-*.md` + `assets/blueprint-template.md` + `scripts/state_io.py` + `state/schema.json` + `evals/smoke.md`） | 确定性 Python + 插件 `render(ctx)`（**标准库字符串模板，非 Jinja2**）；两引擎并行渲染 | 插件渲染异常 → **abort（硬门）** |
| **S7 Validate** | S6 两引擎产物目录；`$ROOT/out/<run_id>/provenance_manifest.json`；只读复用 `/Users/bertram/Desktop/skills/.system/skill-creator/scripts/quick_validate.py` | `$ROOT/out/<run_id>/validation_report.json`（`{quick_validate, lint, security, copyright, all_passed}`）；`$ROOT/out/<run_id>/plugin_scan.json`（插件 6 类正则留痕） | 确定性 Python（官方 `quick_validate.py` + 自有 `validate/lint.py` + `validate/security.py` + `validate/copyright_gate.py` 全确定性） | 任一 hard gate 失败 → **abort，不安装不发布**；冒烟负例任一失败 → S7 abort |
| **S8 Install** | S7 `validation_report.json`（`all_passed=true`）；S6 产物目录；`$ROOT/out/<run_id>/provenance_manifest.json`（`distribution` 决策） | `$ROOT/out/<run_id>/install_receipt.json`（`target_abs / symlink_abs / frontmatter_name / validate_passed / distribution`）；真源目录（见 0 节） | 确定性 Python（写前 `os.path.lexists`；内容 hash 相同跳过、不同报错不覆盖；`~/.claude/skills` 逐条绝对路径软链接） | 软链接已存在且指向不同 → **报错不覆盖**；`distribution=blocked` → 不安装 |
| **S9 Eval** | `$ROOT/evals/`（cases / golden / `baseline.json` / `negative_cases.json` / `router_labels.json` / `capability_gold.jsonl`）；S8 产物；`$ROOT/out/<run_id>/` 全量中间产物 | `$ROOT/out/<run_id>/metrics.json`（9 指标，逐条带 `metric_type`）；`$ROOT/ITERATION_LOG.md`；`$ROOT/out/<run_id>/feedback.jsonl`；`$ROOT/round-tracker.md` | 确定性 Python 指标计算为主；`groundedness` / V2 / V3 的 judge 设计上预留为可插拔接口、**本批代码未实现该接口文件**，留待后续批次接入（标 `heuristic` 且值为 `null`） | 任一 measured 指标退化超 `$ROOT/evals/baseline.json` 基线 **5%** → CI fail |

**`override_source` 取值**（S3 写入 `$ROOT/out/<run_id>/router_result.json`，记录路由决策来源）：`cli | run_json | plugin_default | auto | ambiguity`。其中 `run_json` 对应计划草稿的 `run_yaml` —— 本项目配置为 `$ROOT/configs/default.run.json`，故取值改用 `run_json`，语义完全等价。优先级 `CLI > run_json（default.run.json）> 插件 default > router`，一律记入该字段，全程不停人。

### 1.4 配置与 schema 文件清单（本批冻结）

| 文件（绝对路径） | 作用 |
|---|---|
| `$ROOT/configs/router.json` | 12 特征 cap、4 体裁权重表、prior、hard_gate_bonus、margin 阈值 0.15、`default_engines` 映射 |
| `$ROOT/configs/default.run.json` | 默认 `engine` / `genre` / `no_router` / `public` / `confirm_public` / `plugin_dir` / `ocr` |
| `$ROOT/schemas/sources.schema.json` 等 7 份 | sources / segments / capabilities / claim_ledger / provenance / state / router_result 的标准 JSON Schema；由内置子集校验器或 `jsonschema`（若已安装）加载 |

`capabilities.schema.json` 在 S4 输出处显式校验；其余 6 份在对应 stage 写盘前校验。

---

## 2. `state.json` 幂等算法

### 2.1 `input_sha256` 计算口径

对每个 stage，写盘前计算：

```
input_sha256(stage) = sha256( concat( 上游各输出文件内容字节
                                    + 本 stage 涉及的插件文件字节
                                    + configs/router.json 字节
                                    + configs/default.run.json 字节
                                    + llm/prompts/*.md 版本字节
                                    + stage_id 字符串 ) )
```

要点：

- 「上游输出」按**字节内容**参与（不是文件名、不是 mtime），内容变即 hash 变。
- 计划草稿中的 `router.yaml` 在本冻结中即 `$ROOT/configs/router.json`；prompts 版本按 `$ROOT/bookleme/llm/prompts/*.md` 内容哈希参与，换 prompt 即失效。
- 插件文件按 `--plugin-dir` 解析后的**实际生效路径**内容参与（用户插件覆盖内置时以生效者为准）。
- `state.json` 每条记录结构：`{stage_id, status: completed|failed|skipped, input_sha256, output_paths[], model_fingerprint, plugin_hash, started_at, finished_at}`。

### 2.2 跳过（skip）的充要条件

某 stage 被跳过，**当且仅当同时**满足：

1. `state.json` 中该 stage `status == "completed"`；
2. 现算的 `input_sha256(stage)` 与 `state.json` 记录的 `input_sha256` **完全相等**；
3. 该 stage 声明的 `output_paths[]` **全部存在且非空**（防止零字节占位文件被误判为已完成）。

三者缺一即重跑该 stage。

### 2.3 删除某 stage 输出后只补该 stage 及下游

- 删除 S_k 的任一 `output_paths[]` 文件后重跑：S_k 因条件 3 不满足而重跑。
- S_k 重跑会重写其输出字节 → 使 S_{k+1} 的「上游输出字节」变化 → `input_sha256(S_{k+1})` 与记录不符 → S_{k+1} 重跑；依次向下游传导至 S9。
- **S_0..S_{k-1} 全部命中 2.2 三条件而被跳过**，不重复读书、不重复抽取、不重复校验。
- 特例说明：第 11 节硬验收清单第 11 条写作「删除 S5 输出重跑，只补 S5（断点续跑实测）」，其验收意图是**验证上游 S0–S4 不被重跑**（即 `state.json` 证明 S4 只跑一次，对应清单第 10 条）；本 2.3 节描述的是通用传导规则（含下游），两者口径差异见交付说明中的「计划内部不一致」条目。
- 缓存：`$ROOT/cache/<input_sha256前12>/` 保存该 stage 中间结果；LLM 响应（后续批次接入后）按 `sha256(prompt+model+slice)` 缓存。

---

## 3. 共享 IR（两引擎不重复读书的结构性保证）

### 3.1 为何 S3 ‖ S4

- S3（路由）与 S4（能力抽取）**都只以 S2 的 `segments.json` + `slices/` 为输入**，彼此之间没有数据依赖。
- S4 的 capability 抽取是**体裁无关**的：先把全书按框架原子化拆成 `capabilities.json`（每条带 `genre_tags[]` / `engine_targets[]`），**不预设最终引擎**；S3 只决定 `engines[]` / `genres[]` 标签，不改变 capability 内容。
- 因此二者可并行，S5 在二者汇合后才启动。这是「S4 只跑一次」的前提。

### 3.2 为何两引擎不重复读书

- S1（全文提取）、S2（分段）、S4（能力抽取）、S5（忠实度校验）**全程只执行一次**，产物落在同一 `$ROOT/out/<run_id>/`。
- **只有 S6 分流**：knowledge_pack 与 behavior_skill 各自 render，但读取的是**同一份** `capabilities.json` / `claim_ledger.json` / `fidelity_report.json`，不重新打开 `full_text.txt`、不重新分段、不重新抽取。
- `state.json` 中 S1/S2/S4/S5 各只有一条 `completed` 记录，即「双引擎共享 S1/S2/S4/S5」的可验证证据（硬验收清单第 10 条）。

### 3.3 `capability.engine_targets` 如何过滤

- 字段 `engine_targets[]` 取值域 ⊆ `{ "knowledge_pack", "behavior_skill" }`，可同时含两者。
- S6 渲染 `knowledge_pack` 时，只取 `engine_targets` 含 `"knowledge_pack"` 的 capability；渲染 `behavior_skill` 时只取含 `"behavior_skill"` 的。
- 同时含两者 → 该能力进入两个引擎（内容一致，模板不同）。
- 空数组或字段缺失 → 该 capability 不进任何引擎，S4 记 `warning` 并从 `coverage_score` 分子中剔除，不静默丢弃。
- 体裁→默认引擎映射（写进 `$ROOT/configs/router.json` 的 `default_engines`）：`coach → [behavior_skill]`、`analysis → [behavior_skill, knowledge_pack]`、`checklist → [behavior_skill, knowledge_pack]`、`reference → [knowledge_pack]`；该映射只用于给 capability 打 `engine_targets` 默认值，不改变 S6 的过滤逻辑。

---

## 4. 可观测性纪律（写进 `pipeline.py`，不可省）

1. **批次三要素**：每次启动一次性给出 ① 计划总量（stage 数 / case 数 / 文件数）② 可实时自盯的日志绝对路径 ③ 预计完成时间。三要素落 `$ROOT/progress.md`，并同步维护 `$ROOT/tasks.json`、`$ROOT/state.json`、`$ROOT/ITERATION_LOG.md`、`$ROOT/round-tracker.md`。
2. **日志绝对路径**：`$ROOT/logs/<M>/run-<run_id>.log`（`<M>` ∈ `M0..M5`），每里程碑每运行一个文件；`degradation_log.json` / `validation_report.json` 等结构化留痕落 `$ROOT/out/<run_id>/`；`plugin_scan.json` 为 M4 规划，本批未生成。
3. **整批一次提示**：默认整批跑完只提示一次（完成汇总），中间进度靠落盘状态 + 探针取证自盯，**不做逐 stage 弹提示**。
4. **仅报错打断**：只有 `ERROR` 级事件立即打断（S6 渲染异常、S7 hard gate 失败、S8 软链接冲突、CI measured 退化 >5%）；warning / degradation 只记盘不打断。
5. **禁止长阻塞看守**：流水线内**零停顿**（全部交互前移为启动参数，唯一人工闸门「发布」也做成启动前 `--public --confirm-public PUBLISH`），不得用长轮询/长睡眠看守进程；用落盘 `state.json` + 轻量探针判断完成。

---

## 5. 范围锚定（抄自计划第 10 节）

### 5.1 v1 必须跑通的唯一最小闭环

> 合成中文书 → `--genre <指定>` → 单引擎 → 1 个产物目录 → `quick_validate.py` 退出码 0 → 装到真源。任何里程碑都必须有**可运行产物**，不允许出现「只有文档没有代码」的阶段。

### 5.2 v1 明确不做

> 跨书库级合并与冲突检测（M2 只预留 `book_sha256` 接口）、Web UI / SaaS / 市场与收益、OCR 模型训练与图像理解、实时反馈学习服务、多语言 UI、自动生成网站。**M2 先打通 `state.py` + `pipeline.py` + `hashing.py` 幂等骨架**，再并行填各模块，避免一次性铺开 100 个文件却跑不通。

---

## 6. 依赖方向（抄自计划第 9 节）

`bookleme`（核心库，纯 Python，**不 import 任何宿主 SDK**）◄─ `bookleme/cli.py` ◄─ WorkBuddy Skill 薄封装（**子进程调用 CLI，不 import 核心**）。核心路径不 import `$ROOT/.vendor/` 中任何可选包；CLI 不直接调用宿主 MCP / WebSearch 工具，公开资料一律先由调用方落盘到 `sources/public/`（`bookleme fetch` 为 M4 规划，本批 CLI 未实现）。
