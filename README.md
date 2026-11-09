# 读了么（BookLeme）

[![CI](https://github.com/bookleme/bookleme/actions/workflows/ci.yml/badge.svg)](https://github.com/bookleme/bookleme/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Zero deps](https://img.shields.io/badge/runtime-zero%20third--party%20deps-brightgreen.svg)](./pyproject.toml)

把一本书编译成可安装的 Agent Skill。通用，不限金融领域；**自研**，不复用上游仓库代码。

## 它和 virgiliojr94/book-to-skill 有什么不同

| 维度 | 上游项目 | BookLeme |
|---|---|---|
| 产物 | 可查阅的知识包（SKILL.md + chapters + glossary/patterns/cheatsheet） | **双引擎**：知识包 + 会运行的行为 Skill（教练对话 / 专业分析流水线） |
| 生成器 | 一份巨型 SKILL.md 操作规程，由宿主 Agent 逐步执行，不可单测、不可 diff | 代码化 stage DAG S0–S9，中间产物全部有 JSON Schema，**stage 级** sha256 幂等续跑（上游是整运行级 `reuse_is_safe()` 复用，粒度不同） |
| 体裁 | 固定 5 文件 + 固定 10 节模板 | **可插拔插件**：新增体裁只写一个文件定义 schema / 状态机 / 输出契约 / 反模式 |
| 忠实度 | "no hallucination" 是叙述性主张，无自动回验 | 逐字引文校验 + claim ledger + 7 个指标，明确区分 measured / heuristic |
| 输入 | 本地技术书 PDF，扫描版中止 | 混合输入（本地有权文件 + 标注可信度的公开资料），中文分段不依赖 "Chapter N" |
| 交互 | 5 处强制停人 | 全部交互前移为启动参数，流水线内零停顿 |
| 版权 | 靠 prompt 规则与自律 | provenance manifest + 6 条确定性硬门 + 默认私有 |
| 分发 | 单个宿主技能目录 | 一套两出口：本机 WorkBuddy Skill + 可独立开源的 GitHub 项目 |

借鉴的只有三条**工程上采纳、但未经本项目验证**的设计原理：编译期与运行期分离、渐进式披露三级、确定性提取与概率性生成解耦。「提炼结构而非摘要」同样只是设计选择——上游把它列为未验证假设 PD-05（任务状态 `BLOCKED`），本项目标为 `UNVERIFIED`（认知状态），**不得表述为已验证结论**。详见 `docs/decisions/ADR-001-research-convergence.md` 与 `docs/UPSTREAM_AUDIT.md`。

**关于「零 LLM 调用」的精确口径**：上游**生产期抽取器与当前评测工具**的 Python 代码里没有任何 LLM API 调用，生成阶段靠宿主 Agent 的常规推理；但其研究计划中规划的 live 评测 harness 允许引入模型，因此不能笼统写成「全仓任何地方都不含模型调用」。本项目本批同理：核心运行时零 LLM 调用，S4 抽取与 S3 歧义判定均为确定性实现，LLM judge 是后续批次的可插拔接口。

## 与同名项目 bookforge-ai 的区别（避免混淆）

GitHub 上已存在组织 `bookforge-ai`（bio：*"Non-fiction books, distilled into agent skills."*）及其仓库 `bookforge-ai/bookforge-skills`（**42 stars / 2 forks**，CC-BY-SA-4.0，描述 *"Agent skills distilled from non-fiction books. Works with Claude Code, Codex, Gemini CLI, Cursor, Copilot, and 20+ platforms."*，2026-03 创建）。它与本项目**同名同概念、但定位不同**，为避免搜索与认知混淆，本项目已更名为 **读了么（BookLeme）**：

| | `bookforge-ai/bookforge-skills` | 读了么（BookLeme） |
|---|---|---|
| 定位 | **产物库**：已蒸馏好的 skills 集合 | **转换器工具链**：书 → Skill 的编译器 |
| 交付物 | skills 文件本身 | 双引擎流水线 + 体裁插件体系 + 忠实度评测 |
| 技术栈 | JavaScript | Python，stage DAG，零第三方依赖 |
| 许可 | CC-BY-SA-4.0 | MIT |

**两者无隶属关系，本项目未使用其任何代码或内容。**本项目自研自 `virgiliojr94/book-to-skill` 的源码审计之后（未导入其任何代码）。

## 快速开始

核心零第三方依赖，Python >= 3.9：

```bash
cd $ROOT
python3 -m bookleme --version
python3 -m bookleme run --input evals/cases/synthetic/coach_book.md --title "人生设计练习册（合成）"
python3 -m bookleme plugin validate bookleme/plugins/builtin/coach_dialogue.py
python3 -m bookleme eval --run-id <run_id>
python3 -m unittest discover -s tests -v
```

`run` 常用参数：`--engine auto|knowledge_pack|behavior_skill|both`、`--genre <plugin_id>`、
`--no-router`、`--install`（写技能真源，默认关闭）、`--user-rights owned|licensed|public_domain|unknown`、
`--public --confirm-public PUBLISH`（公开分发的启动前裸词确认，本批不会真的执行远端发布）。

## 目录

- `bookleme/` 核心库（extract / segment / router / capabilities / fidelity / render / plugins / validate / install / eval）
- `configs/router.json` 12 个路由特征的 cap、权重、prior、hard gates（全部外置可 diff）
- `schemas/*.schema.json` 7 个标准 JSON Schema
- `bookleme/plugins/builtin/<genre>.py` 体裁插件
- `evals/cases/synthetic/` 合成评测文本（零版权风险，带 golden 标记）
- `out/<run_id>/` 每次运行的产物、校验报告与指标
- `cache/<sha12>/` 共享中间表示（跨 run 复用）
- `docs/` 设计与决策记录；`docs/decisions/` ADR

## 当前状态（如实标注）

本批完成 **M0 研究对齐 / M1 设计冻结 / M2 核心引擎 / M3 首个产物** 的可运行骨架：

- ✅ S0–S9 端到端跑通；双引擎共享 IR；**stage 级** sha256 幂等与断点续跑（删 S5 输出只补 S5）；共享 IR 与 per-run 决策结果已隔离（`router_result.json` / `provenance_manifest.json` 按 run 落盘）；官方 `quick_validate.py` 与自有 lint 双校验；6 条版权硬门；冒烟负例；16 项回归测试全过。
- ✅ 内置 2 个体裁插件：`coach_dialogue`（行为型）、`knowledge_reference`（知识型）。
- ⚠️ **本批 S4 使用确定性抽取器**（合成书的 `[CAP]` 显式标记 / 无标记时的启发式卡片），S3 歧义判定使用确定性兜底并显式标记 `llm_judge_invoked: false`。LLM 抽取器与 3 独立 judge 是后续批次的接口占位，**当前不宣称已实现模型判断**。
- ⚠️ `professional_analysis`、`decision_checklist` 两个插件、跨书合并、Web UI / 市场收益、OCR 与图表理解均属后续批次。
- ⚠️ 指标中 `groundedness` / V2 / V3 为 heuristic，未接入 LLM judge 时值为 `null`，**不伪造数字**。三类上游数字一律不得转写成本项目结论：① `24×–51×` 是其 context-dump 对比自测；② `2.4×–15.6×` 是其 discovery-loop **模型估算**（`discovery_tax.py` 自述）；③ 论文约 `2×` token 主张仍处 `BLOCKED` 假设阶段；另有其约 `$1/书` 的 LLM 成本估算同样不是本项目实测。详见 `docs/decisions/ADR-003-fidelity-metrics.md`。

## 版权

MIT 只覆盖转换器。请只处理你有权使用的文件；输出是结构化衍生笔记，不是原文复现；第三方书籍生成的 Skill 默认私有，不得分发。详见 `docs/COPYRIGHT.md` 与 `NOTICE.md`。
