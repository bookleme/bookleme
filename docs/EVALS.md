# BookLeme 评测与硬验收（M1 设计冻结）

> **M2 实现口径（以代码为准，2026-11-08）**：本文件描述设计目标；实际实现在 `/Users/bertram/Desktop/BookLeme/bookleme/`。共享中间 IR 在 `cache/<book_sha256前12>/`，`out/<run_id>/` 只放本次产物与报告；`router_result.json`、`provenance_manifest.json` 按 run 隔离。完整差异见 `docs/ARCHITECTURE.md` 的「M2 实现口径校正」表。文中凡提「可插拔 LLM 接口」，一律按统一口径理解：**设计上预留为可插拔接口，本批代码未实现该接口文件，留待后续批次接入**（`bookleme/llm/client.py` 与 `CapabilityExtractor` Protocol 本批均不存在，只有 `bookleme/llm/__init__.py` 的 `LLM_AVAILABLE = False` 占位）。

> 状态：M1 设计冻结。本文定义评测集来源、指标口径、CI 回归门、全量硬验收清单与冒烟测试。
> 前缀 `$ROOT = /Users/bertram/Desktop/BookLeme`。
> 本机零第三方依赖：评测运行器用标准库 `unittest` 组织；指标计算确定性；`groundedness` / V2 / V3 的 judge 设计上预留为可插拔接口、**本批代码未实现该接口文件**，留待后续批次接入（本批确定性兜底，标 `heuristic`）。本批 S4 为确定性抽取器（合成书显式结构化标记），**未实现 LLM 抽取、未验证「框架优于摘要」**。

---

## 1. 评测集三来源

| 来源 | 路径（绝对路径） | 用途 | 入库 |
|---|---|---|---|
| 合成书 | `$ROOT/evals/cases/synthetic/` | **自撰 4 段各约 3000 字中文合成文本，分别对应 4 体裁**（coach / analysis / checklist / reference）；**承担体裁标签与 golden**（`$ROOT/evals/golden/`、`router_labels.json`、`capability_gold.jsonl`）；零版权风险；本批带 `[CAP]` + `R:/I:/A1:/A2:/A3:/B:` 六字段显式结构化标记供确定性抽取器使用（见 `evals/cases/synthetic/coach_book.md`） | 入库 |
| 公版书 | `$ROOT/evals/cases/public_domain/` | 公版文本（如《孙子兵法》）；**只用于中文章节切分、衍生与版权检查，不承担体裁标签** | 入库 |
| 用户自备书 | `$ROOT/evals/cases/user_books/` | 用户自备书，dogfood 可替换其一 | **被 `.gitignore` 排除，绝不入库** |

**dogfood**：① 合成教练型书（双引擎）② 公版书（双引擎）；用户自备书到位可替换其一。**不下载受版权书籍、不 clone 上游进我们仓库、不把任何原文提交 Git。**

---

## 2. 9 个指标

`$ROOT/out/<run_id>/metrics.json` 逐条带 `metric_type`。

| 指标 | `metric_type` | 目标值 |
|---|---|---|
| `router_accuracy` | `measured` | ≥0.90（合成集） |
| `citation_resolution_rate` | `measured` | 1.00 |
| `verbatim_violation_rate` | `measured` | 0.00 |
| `coverage_score` | `measured` | ≥0.85 |
| `trigger_hit_rate` | `measured` | ≥0.90 / 误触发 ≤0.05 |
| `negative_refusal_rate` | `measured` | 1.00 |
| `artifact_compliance_rate` | `measured` | 1.00 |
| `unsupported_claim_rate` | `measured+heuristic` | ≤0.05（分类口径见 FIDELITY.md 第 6 节：主体 measured + judge 启发式补充，硬门按 measured 执行） |
| `groundedness` | `heuristic` | 只报告，不作硬门 |

---

## 3. CI 回归退化阈值 5%

- 基线文件：`$ROOT/evals/baseline.json`，按 `bookleme_version + model_fingerprint + plugin_hash` 版本化。
- 每次 CI 用 `python -m unittest discover` 跑评测后，把 `metrics.json` 的 **measured** 指标与 `baseline.json` 比对。
- **任一 measured 指标退化 > 5% → CI fail**（S9 失败 / 硬验收清单第 21 条）。
- `heuristic` 指标（含 `groundedness`）**只报告，不参与 5% 退化硬门**。
- 本项目只报告 `baseline.json` 中自己实测的数字；**禁止把上游 24×–51×（其自测）或 2.4×–15.6×（其模型估算）转写成本项目结论**。

---

## 4. 全量硬验收清单（逐字抄录计划第 11 节，22 条，一条不少、不增量改写）

```
[ ] 1  quick_validate.py 对全部产物退出码 0
[ ] 2  frontmatter 顶层键 ⊆ {name,description,license,allowed-tools,metadata}，无 version/tags/author/homepage/argument-hint
[ ] 3  name 匹配 ^[a-z0-9-]+$、≤64、无首尾连字符、无 --
[ ] 4  description ≤1024、无 < >、不以 [TODO: 开头、含 3–5 个中文触发词（len() 实测）
[ ] 5  lint.py：正文无 [TODO: ...]、五段章节齐、Gotchas ≥4、章节间 ---、≤500 行
[ ] 6  技能包内无 README.md / 安装指南 / CHANGELOG / 重复 quick reference / full_text.txt / slices/
[ ] 7  references/ 用相对路径且每个文件写明「何时读」
[ ] 8  产物由 plugin.output_contract 决定，未把上游五文件模板当唯一产物
[ ] 9  4 个内置插件 plugin validate 全过（含 voice_calibration、state_machine、≥1 negative eval）
[ ] 10 双引擎共享 S1/S2/S4/S5，state.json 证明 S4 只跑一次
[ ] 11 删除 S5 输出重跑，只补 S5（断点续跑实测）
[ ] 12 12 个路由特征确定性可复现；歧义路径产出 router_evidence.json 且不停人
[ ] 13 逐字引文校验、≤150 字、shingle ≤0.10、总引文比 ≤0.03、连续复制 ≤150 全部通过
[ ] 14 provenance_manifest.json 字段齐；local/public 分级；user_rights 非 unknown
[ ] 15 默认 private；public 需启动前 --public --confirm-public PUBLISH
[ ] 16 冒烟负例「书中未回答」100% 拒答
[ ] 17 docs/FIDELITY.md 标注 PD-05 UNVERIFIED、PD-04~PD-12 BLOCKED，README 无「零幻觉」表述
[ ] 18 所有 measured / heuristic 指标分类正确，未把启发式写成既成事实
[ ] 19 真源写入路径唯一例外已显式声明；Claude 逐条软链接补齐且幂等不覆盖
[ ] 20 批次三要素（总量 / 日志绝对路径 / 预计时间）落 progress.md；整批一次提示、仅报错打断
[ ] 21 CI 全绿；仓库内无任何书籍原文（copyright_gate 全仓扫描）
[ ] 22 交付消息列出所有改动文件的完整绝对路径
```

> 说明：以上 22 条为计划第 11 节原文逐字抄录，交付前逐条打勾，全过才算完成。其中第 11 条「只补 S5」的验收意图是验证上游 S0–S4 不被重跑（配合第 10 条「S4 只跑一次」）；通用幂等传导规则（含下游）见 ARCHITECTURE.md 第 2.3 节，两者口径差异见交付说明的「计划内部不一致」条目。第 17 条「PD-05 UNVERIFIED、PD-04~PD-12 BLOCKED」需按两种口径理解：上游任务台账 `PD-05 = BLOCKED` 是**任务进度状态**，本项目未验证假设表 `PD-05 = UNVERIFIED` 是**认知状态**（「结构化框架优于摘要」未被验证），二者不矛盾；逐字清单保留原文不改，口径澄清见 FIDELITY.md 第 8 节。**M2 实现口径校正（以代码为准）**：共享中间 IR 在 `cache/<book_sha256前12>/`（`out/<run_id>/` 只放本次产物与报告）；`verification.json` / `regen_queue.json` / `plugin_scan.json` 本批未生成，S5 实际产出 `capabilities_verified.json` / `claim_ledger.json` / `fidelity_report.json`；`bookleme fetch` CLI 本批未实现；格式支持 7 种（txt/md/html/pdf/epub/docx/rtf，MOBI/AZW3 标 `deferred`）；根目录 `round-tracker.md` / `claim-ledger.md` 留 M4；`provenance_manifest.json` 已移到 `out/<run_id>/`（不进共享 cache），`sources.json` 用稳定 `run_id=shared-<sha12>` + 文件 mtime 保证跨 run 幂等。完整对照见 `docs/ARCHITECTURE.md`「M2 实现口径校正」表。

---

## 5. 冒烟测试 5 类 case

文件：`$ROOT/evals/negative_cases.json` + 各插件 `eval_prompts`（PLUGIN_SPEC.md 要求 ≥1 negative）。S7 前跑，**负例必须 100% 拒答**，任一失败 → S7 abort。

| 类型 | 含义 | 期望 |
|---|---|---|
| `positive` | 书中有答案的问题 | 必须答且**带出处**（`evidence_path` 指向 `slices/`） |
| `negative_unanswered` | **一个书中未回答的问题** | **必须答「书里没讲」且不得编造出处**；`quote_verified` 不得为 true |
| `boundary` | 部分覆盖的问题 | 只答已覆盖部分并**声明缺口**，不补全、不臆测 |
| `trigger_hit` | 命中 3–5 个中文触发词的输入 | 正确触发对应 Skill，计入 `trigger_hit_rate` |
| `trigger_miss` | 不含触发词的输入 | 不误触发（误触发率 ≤0.05） |

- `negative_refusal_rate` 目标 1.00；负例任一失败 → S7 abort，不安装。
- Generator→Evaluator→Re-generator ≤3 轮，收敛门 = hard gate 全过 + 无 P0；reviewer 必须读 `$ROOT/cache/<book_sha256前12>/slices/` 原始切片（共享 IR，见 ARCHITECTURE.md「M2 实现口径校正」），不读摘要。
