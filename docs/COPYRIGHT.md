# BookLeme 版权工程化（M1 设计冻结）

> **M2 实现口径（以代码为准，2026-11-08）**：本文件描述设计目标；实际实现在 `$ROOT/bookleme/`。共享中间 IR 在 `cache/<book_sha256前12>/`，`out/<run_id>/` 只放本次产物与报告；`router_result.json`、`provenance_manifest.json` 按 run 隔离。完整差异见 `docs/ARCHITECTURE.md` 的「M2 实现口径校正」表。文中凡提「可插拔 LLM 接口」，一律按统一口径理解：**设计上预留为可插拔接口，本批代码未实现该接口文件，留待后续批次接入**（`bookleme/llm/client.py` 与 `CapabilityExtractor` Protocol 本批均不存在，只有 `bookleme/llm/__init__.py` 的 `LLM_AVAILABLE = False` 占位）。

> 状态：M1 设计冻结。核心原则：**输出仍是衍生笔记，不含原文段落；默认 private；版权作为设计约束而非事后声明**。
> 前缀 `$ROOT = $ROOT`。`copyright_gate.py` 全部确定性（标准库实现，零第三方依赖）。

---

## 1. 混合输入与来源分级

输入分两类，**分别标可信度**（与 FIDELITY.md 第 3 节的 S / A / B / C 对齐）：

| 类别 | `origin` | `tier` | 说明 | 落盘位置 |
|---|---|---|---|---|
| 本地有权文件 | `local` | `S` | 用户拥有权利的正文（主输入） | CLI `--input` 指向路径，S1 只读 |
| 作者访谈 / 官方讲义 | `public` | `A` | 公开补充资料 | `$ROOT/sources/public/<sha256(url)>.json` |
| 权威书评 | `public` | `B` | 公开补充资料 | 同上 |
| 推算 / 二次转述 | `public` | `C` | 公开补充资料 | 同上 |
| 公版书 | `public` | `A` | 如《孙子兵法》，dogfood 用 | `$ROOT/evals/cases/public_domain/` |

**硬规则**：公开来源最高只能 `A / B / C`；任何 `S` 级断言必须有 `local` 支撑。CLI **不直接调用任何宿主 MCP / WebSearch 工具**；由调用方（`bookleme fetch` 为 M4 规划，本批 CLI 未实现）把公开资料抓取后落盘到 `$ROOT/sources/public/<sha256(url)>.json`（含 `sha256(content)`、`url`、`title`、`publisher`、`retrieved_at`、`license_note`、`tier`），或由 Skill 薄封装在宿主侧抓完落盘；**S1 起核心只读本地文件**，保证离线可复现。

---

## 2. `provenance_manifest.json` 完整字段表

文件：`$ROOT/out/<run_id>/provenance_manifest.json`（S0 建骨架，S1 / S5 / S8 逐步补全）。**M2 校正**：该 manifest 含 `run_id` / `generated_at`，已明确留在 `out/<run_id>/`、**不进共享 `cache/<book_sha256前12>/`**（避免不同 run 覆盖导致追溯串味）；`sources.json` 用稳定 `run_id`（`shared-<sha12>`）+ 文件 mtime，保证跨 run 内容不变、S1 可幂等跳过。校验依据 `$ROOT/schemas/provenance.schema.json`。

| 字段 | 类型 | 子字段 / 约束 |
|---|---|---|
| `manifest_version` | str | 清单结构版本 |
| `run_id` | str | 关联 `$ROOT/out/<run_id>/` |
| `book` | object | 书籍元数据 |
| `book.title` | str | 书名 |
| `book.author` | str | 作者 |
| `book.isbn` | str | ISBN（无则 null） |
| `book.language` | str | 如 `zh` |
| `book.sha256` | str | 全书内容 `sha256`（即 `book_sha256`，跨书接口预留键） |
| `book.file_count` | int | 输入文件数 |
| `book.user_rights` | enum | `owned \| licensed \| public_domain \| unknown`；**`unknown → blocked`** |
| `sources[]` | list[object] | 每个源一条 |
| `sources[].source_id` | str | 源 ID |
| `sources[].origin` | enum | `local \| public` |
| `sources[].kind` | str | `pdf / epub / docx / html / md / txt / rtf / mobi / azw3 / public_json`；**M2 校正**：本批已实现前 7 种，MOBI/AZW3 依赖 Calibre、缺失时标 `deferred` 且不中止 |
| `sources[].path` | str | 本地绝对路径（public 可空） |
| `sources[].url` | str | 公开源 URL（local 可空） |
| `sources[].sha256` | str | 内容 sha256 |
| `sources[].bytes` | int | 字节数 |
| `sources[].mime` | str | MIME 类型 |
| `sources[].tier` | enum | `S \| A \| B \| C` |
| `sources[].license_note` | str | 权利 / 许可说明 |
| `sources[].retrieved_at` | str | ISO8601 抓取时间 |
| `sources[].extract_status` | enum | `ok \| partial \| skipped`（扫描版 `partial` 不中止） |
| `sources[].figure_text_lost` | list | 图表 / 表格文字丢失的段标识 |
| `derivative` | object | 衍生声明（硬约束值） |
| `derivative.contains_original_text` | bool | **必须 `false`** |
| `derivative.max_quote_chars` | int | **150** |
| `derivative.shingle_overlap_ceiling` | number | **0.10** |
| `derivative.total_quote_ratio_ceiling` | number | **0.03** |
| `distribution` | object | 分发性决策 |
| `distribution.default` | str | **`"private"`** |
| `distribution.decision` | enum | `private \| publishable \| blocked` |
| `distribution.reason` | str | 判定理由 |
| `distribution.confirmed_by` | str | `null` 或 `"--confirm-public PUBLISH"` |
| `attribution` | object | 署名 + 免责（见第 5 节） |
| `engine` | object | 引擎信息 |
| `engine.bookleme_version` | str | 引擎版本 |
| `engine.plugin_id` | str | 生效插件 `genre_id` |
| `engine.model_fingerprint` | str | 模型指纹（本批 LLM 未接入时记 `"deterministic-extractor"`） |
| `generated_at` | str | ISO8601 生成时间 |

---

## 3. 不抄原文 6 条硬检查（S5 + S7 双门）

`copyright_gate.py` 全确定性；**S5（生成期）与 S7（校验期）各跑一次**，任一失败 → **abort，不安装不发布**。

| # | 检查 | 阈值 | 数据源 |
|---|---|---|---|
| 1 | 单条引文长度且 `quote_verified` | **≤150 字** 且 `quote_verified = true` | `capabilities.json` / `claim_ledger.json` |
| 2 | 总引文比（引文字数 / 产物总字数） | **≤0.03** | 产物全文 |
| 3 | `max_contiguous_copy_chars`（产物与原文最长连续相同字符） | **≤150** | `full_text.txt` + 产物 |
| 4 | 13 字 shingle Jaccard（产物任意段 vs 原文） | **≤0.10** | `full_text.txt` + 产物 |
| 5 | 产物内无 `full_text.txt` / `slices/` / 原书文件拷贝 | 不存在 | 产物目录扫描 |
| 6 | `derivative.contains_original_text` | **`=== false`**（严格） | `provenance_manifest.json` |

上述 6 条中涉及文本比较的检查（#1 单条引文长度、#3 连续复制、#4 shingle）统一使用 **FIDELITY.md 第 5 节的受限归一规则**（`U+2F00–U+2FDF` 康熙部首 + `U+F900–U+FAFF` CJK 兼容表意文字做 NFKC 折叠，**绝不整篇 NFKC**，与 M2 代码 `extract/base.py::normalize` 一致），保证与逐字引文校验同口径；整篇 NFKC 会改写全角 / 连字 / 带圈数字，破坏精确匹配。

失败处理：写 `$ROOT/out/<run_id>/validation_report.json` 的 `copyright = false`、`all_passed = false`，S7 abort；`invalidated` 能力本批直接置 `status=rejected`；`regen_queue.json` 与 Generator→Evaluator 自迭代为 M4 规划，本批未生成 / 未接入。

---

## 4. 可分发性判定规则

| 条件 | `distribution.decision` |
|---|---|
| `book.user_rights == "unknown"` | **`blocked`** |
| `book.user_rights == "owned"` 或 `"licensed"` | **`private`**（默认） |
| `book.user_rights == "public_domain"` **且** 6 条硬检查全过 **且** 署名齐 | **`publishable`**（默认仍 `private`，需显式转 public） |

- `gh repo create --private` **默认私有**。
- 转 public 必须在**启动命令**显式给 `--public --confirm-public PUBLISH`：**`PUBLISH` 为裸词确认**，写入 `distribution.confirmed_by`；**不在运行中询问**（流水线内零停顿）。
- 缺 `--public`、或缺裸词 `PUBLISH`、或拼写不符 → 维持 `private`，不发布。
- `blocked` → S8 不安装、不发布。

---

## 5. 署名与免责声明出现位置

`$ROOT/out/<run_id>/build/<engine>/<slug>/references/provenance.md` 与 `SKILL.md` 的 `## Gotchas` **各写一份**，内容含：作者 / 书名 / ISBN / 衍生声明 / 不含原文 / 非替代品（不替代原书） / 生成日期 / 引擎版本（`bookleme_version` + `plugin_id` + `model_fingerprint`）。

---

## 6. dogfood 与仓库卫生

- **dogfood 只用合成书（`$ROOT/evals/cases/synthetic/`）+ 公版书（`$ROOT/evals/cases/public_domain/`）**：① 合成教练型书（双引擎）② 公版书（双引擎）；用户自备书到位可替换其一，但**绝不入库**。
- `$ROOT/evals/cases/user_books/` 用户自备书目录**被 `.gitignore` 排除**，绝不提交 Git。
- **不下载受版权书籍、不 clone 上游进我们仓库、不把任何原文提交 Git**；CI 用 `copyright_gate` 做全仓扫描（硬验收清单第 21 条）。

---

## 7. 许可证边界（明确声明）

> **MIT 只覆盖转换器，不覆盖任何书籍。**

- `$ROOT/LICENSE` 的 MIT 许可**仅适用于 BookLeme 的转换器代码**（CLI / 核心引擎 / 插件 / 评测脚手架 / 文档模板）。
- 它**不覆盖**：任何输入书籍（本地有权文件、公版书、公开资料）的版权；任何输出衍生笔记对原书的可分发性；`provenance_manifest.json` 中 `book` / `sources[]` 所指第三方内容。
- 输出是否为可发布衍生作品，由本文第 4 节的 `user_rights` + 6 条硬检查 + 署名齐备度单独判定，与 MIT 无关。
- 署名与免责（第 5 节）、`$ROOT/NOTICE.md` 与 `references/provenance.md` 用于标注第三方权利，不得因 MIT 而省略。
