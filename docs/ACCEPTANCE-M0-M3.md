# M0–M3 硬验收清单（22 条全量）

> 依据已批准计划第 11 节逐条核对。**PASS = 本批实测通过；DEFERRED = 明确留到 M4/M5，不冒充完成。**
> 批次：smoke-001（双引擎）、smoke-002（断点续跑）、single-001（单引擎覆盖 + 完整幂等）、unittest-run（16 项回归）、gate-test（公开闸门）。

| # | 验收项 | 状态 | 证据 |
|---|---|---|---|
| 1 | `quick_validate.py` 对全部产物退出码 0 | **PASS** | `validation_report.json`：两个产物 `official_validator.status=passed`、stdout `Skill is valid!`；自有 `validate_text` 零错误 |
| 2 | frontmatter 顶层键 ⊆ 白名单，无 version/tags/author/homepage/argument-hint | **PASS** | 生成物 `SKILL.md` 仅 `name` + `description` |
| 3 | `name` 匹配 `^[a-z0-9-]+$`、≤64、无首尾连字符、无 `--` | **PASS** | `book-a4add8d6-bs` / `book-a4add8d6-kp` |
| 4 | `description` ≤1024、无 `<`/`>`、不以 `[TODO:` 开头、含 3–5 中文触发词 | **PASS** | 两插件各 4 个触发词；`build_description` 有硬断言；单测覆盖 |
| 5 | 正文无 `[TODO: ...]`、五段章节齐、Gotchas ≥4、章节间 `---`、≤500 行 | **PASS** | `lint_skill_dir` 零错误；`examples/coach`、`examples/reference` 复核通过 |
| 6 | 技能包内无 README / 安装指南 / CHANGELOG / 重复 quick reference / full_text.txt / slices/ | **PASS** | `lint_skill_dir` 的 `FORBIDDEN_FILES` 检查零错误 |
| 7 | `references/` 用相对路径且每个文件写明「何时读」 | **PASS** | 每个 reference 首行均为 `## 何时读本文件`；SKILL.md 用 `` `references/topic-index.md` `` |
| 8 | 产物由 `plugin.output_contract` 决定，未把上游五文件模板当唯一产物 | **PASS** | behavior 14 文件（含 state_io.py / blueprint-template.md），knowledge 11 文件（含 cheatsheet.md / index-guide.md） |
| 9 | 4 个内置插件 `plugin validate` 全过 | **DEFERRED** | 本批 2 个（coach_dialogue / knowledge_reference）全过；`professional_analysis`、`decision_checklist` 留 M4 |
| 10 | 双引擎共享 S1/S2/S4/S5，`state.json` 证明 S4 只跑一次 | **PASS** | `build_manifest.json.shared_ir`；重跑时 S4 SKIP |
| 11 | 删除 S5 输出重跑，只补 S5 | **PASS** | smoke-002 实测：S0–S4 全 SKIP、仅 S5 重算、S6/S7/S9 SKIP |
| 12 | 12 个路由特征确定性可复现；歧义路径产出 `router_evidence.json` 且不停人 | **PASS** | 单测两次 `compute_features` 完全一致；router_evidence.json 存在。**如实标注**：本批 `llm_judge_invoked=false`，3 独立 judge 未接入 |
| 13 | 逐字引文校验、≤150 字、shingle ≤0.10、总引文比 ≤0.03、连续复制 ≤150 全过 | **PASS** | 最大单条引文 24 字；shingle 0.084181 / 0.068348；引文比 0.02097 / 0.016918；连续复制 0。**归一规则已按上游 `sanitize.py:168-176` 修正为「不整篇 NFKC，仅折叠康熙部首」**，并由 `test_normalize_is_scoped_not_whole_text_nfkc` 锁死；修正后已失效缓存重跑全部批次 |
| 14 | provenance 字段齐；local/public 分级；`user_rights` 非 unknown | **PASS（部分）** | 字段与 schema 校验全过，本批 user_rights=owned；**public 来源通路代码已实现但未用真实公开资料实测**，留 M4 |
| 15 | 默认 private；public 需启动前 `--public --confirm-public PUBLISH` | **PASS** | `gate-test` 只给 `--public` 被拒：`公开分发必须在启动命令显式给 --public --confirm-public PUBLISH` |
| 16 | 冒烟负例「书中未回答」100% 拒答 | **PASS** | 两个产物 `negative_refusal_rate=1.0`；5 类 case 全过 |
| 17 | `docs/FIDELITY.md` 标注 PD-05 UNVERIFIED、PD-04/PD-06~PD-12 BLOCKED，README 无「零幻觉」结论 | **PASS** | `fidelity_report.json.unverified_assumptions` 与文档一致；README 中所有 `no hallucination` 表述均明确归属**上游**且为批判语境，未作为本项目结论 |
| 18 | 所有 measured / heuristic 指标分类正确，未把启发式写成既成事实 | **PASS** | `groundedness` / V2 / V3 为 `null` 且 `metric_type=heuristic`；只报告不设硬门 |
| 19 | 真源写入路径唯一例外已声明；Claude 逐条软链接补齐且幂等不覆盖 | **DEFERRED** | `install/workbuddy.py` 已实现（lexists 检查、不覆盖、绝对路径软链接），但本批 `install=false`，**未对真源做任何写入**；留 M5 实测 |
| 20 | 批次三要素落 `progress.md`；整批一次提示、仅报错打断 | **PASS** | 每次 run 日志首三行给出总量 / 日志绝对路径 / 预计完成；`progress.md` 同步 |
| 21 | CI 全绿；仓库内无任何书籍原文（copyright_gate 全仓扫描） | **DEFERRED** | `.github/workflows/ci.yml` 已写并通过本地等价检查；**未在远端 runner 实跑**；本地版权门全过，全仓无 PDF/EPUB/全文 |
| 22 | 交付消息列出所有改动文件的完整绝对路径 | **PASS** | 本批交付回复 |

## 实测指标（仅合成书样本，不得外推）

| 指标 | 值 | 类型 | 目标 |
|---|---|---|---|
| `citation_resolution_rate` | 1.0 | measured | 1.00 |
| `verbatim_violation_rate` | 0.0 | measured | 0.00 |
| `coverage_score` | **0.6667** | measured | 0.85（**未达标，如实记录**：6 个框架集中在 6 个章节中的 4 个；M4 需扩充评测集或重新论证目标） |
| `negative_refusal_rate` | 1.0 | measured | 1.00 |
| `unsupported_claim_rate` | 0.0 | measured+heuristic | ≤0.05 |
| `shingle_overlap_max` | 0.084181 | measured | ≤0.10 |
| `trigger_hit_rate` | 1.0 | measured | ≥0.90 |
| `artifact_compliance_rate` | 1.0 | measured | 1.00 |
| `groundedness` | `null` | heuristic | 只报告，LLM judge 未接入 |

## 本批明确的未完成 / 不宣称项

- S4 是确定性抽取器（`[CAP]` 标记 / 启发式卡片），**未接 LLM 抽取**；S3 歧义判定为确定性兜底（`llm_judge_invoked: false`）。
- V2 预测力、V3 独特性、3 独立 judge、Generator→Evaluator 自迭代尚未接入。
- `professional_analysis`、`decision_checklist` 插件、跨书合并、OCR/图表理解、Web UI、市场收益均属后续批次。
- router 在合成教练书上 `margin=0.129876 < 0.15`，触发歧义兜底双引擎；这是兜底机制生效，不是路由失败，也未做调参过拟合。

## C1–C7 表述精确化落地记录（M0 源码审计报告收尾）

M0 本地源码审计交付 `docs/UPSTREAM_AUDIT.md` + `ADR-001~003` + `evals/baseline.json`，提出 7 处需精确化/修正的表述，**无一条核心原理被推翻**。逐条处置：

| 编号 | 处置 | 落点 |
|---|---|---|
| C1 零 LLM 调用口径 | 已限定为「上游生产期抽取器与当前评测工具零 LLM API 调用；规划中的 live 评测 harness 允许模型」 | `README.md` |
| C2 NFKC 范围 | **已改实现并失效缓存重跑**：不整篇 NFKC，仅折叠康熙部首；新增回归测试 | `extract/base.py`、`tests/test_bookleme.py` |
| C3 提取链归属 | 已区分「上游 `pdftotext→pypdf→pdfminer`/docling、扫描版 abort」与「BookLeme 自有 `pypdf` 单链、扫描版标 `partial` 不中止」；**删去文档里不存在的 `pdfplumber` / `ebooklib` / `striprtf`** | `docs/ARCHITECTURE.md` S1 行、`README.md` |
| C4 PD-05 状态 | 上游 `BLOCKED`（任务状态）≠ 本项目 `UNVERIFIED`（认知状态），已分别标注 | `fidelity/report.py`、`docs/FIDELITY.md`、ADR-003 |
| C5 不得宣称已验证 | README 原「三条已被验证的原理」已改为「工程上采纳、但未经本项目验证」 | `README.md` |
| C6 幂等粒度 | 上游整运行级 `reuse_is_safe()` ≠ 本项目 stage 级 `input_sha256`，差异表已注明 | `README.md` 差异表 |
| C7 性能数字禁令 | 由两类扩为四类：`24×–51×` 自测 / `2.4×–15.6×` 模型估算 / 论文 `~2×`（BLOCKED）/ 约 `$1/书` 估算，全部不得转写为本项目结论 | `README.md`、`fidelity/report.py`、ADR-003 §9 |

**工程改进**：S4 的 `input_sha256` 纳入 `bookleme/capabilities/*.py`、S5 纳入 `bookleme/fidelity/*.py`、S9 纳入 `fidelity_report.json`，源码或指标定义变更会自动失效缓存，避免旧产物被误当成新代码结果。`ADR-002 §8` 的验收锚点已补实测结论（不再只是待办）。

## 跨 run 一致性修复（M2 复查发现的两处真实缺陷）

| 缺陷 | 现象 | 修复 | 回归测试 |
|---|---|---|---|
| 共享 IR 被 run 专属字段污染 | `sources.json` 含 `run_id` 与当前时间、`provenance_manifest.json` 含 `run_id`/`generated_at`，却都写在共享 `cache/<sha12>/`；不同 run 互相覆盖，provenance 追溯串味、S1 幂等被打断 | `sources.json` 用稳定 `run_id=shared-<sha12>` + **文件 mtime**；`provenance_manifest.json` 移到 `out/<run_id>/` | `test_shared_ir_is_run_independent`：两次不同 run 后 `sources.json` 字节相同、两个 manifest 的 run_id 各自正确、同一 run 重跑 S1 SKIP |
| 路由结果被 per-run 参数串味 | `router_result.json` 依赖 `--engine/--genre/--no-router`，却放在共享 cache；`smoke-001`（双引擎）覆盖后 `single-001`（单引擎）错误产出 2 个产物 | `router_result.json` / `router_evidence.json` 移到 `out/<run_id>/`；`capabilities.json` 不再写入 per-run 的 `genre_tags`/`engine_targets`；S1 跳过时把 `toc.json` 的 `entries` 规范化为列表 | `test_router_result_is_per_run`：双引擎 run 得 2 个产物、单引擎 run 得 1 个产物，两者 `router_result.json` 分别在各自 out 目录 |

**修复后实测**：`smoke-001` = 2 个产物（ambiguity 双引擎）、`single-001` = 1 个产物（cli 覆盖）、`smoke-002` 删 S5 输出后仅 S5 重算、`single-001` 完整重跑 10 条 SKIP；16 项回归全过。

**文档一致性收口**：5 份设计文档（ARCHITECTURE / PLUGIN_SPEC / FIDELITY / COPYRIGHT / EVALS）已统一加入「M2 实现口径（以代码为准）」提示块，就地修正 `plugin_scan.json` / `regen_queue.json` / `bookleme fetch` / `round-tracker.md` 等「计划写成已实现」的表述，并把 LLM 接口措辞统一为「设计上预留为可插拔接口，本批代码未实现该接口文件，留待后续批次接入」。**`docs/EVALS.md` 的 22 条硬验收清单与计划文件逐字比对 `EXACT MATCH = True`，一个字符未改。**
