# NOTICE

## 本项目

读了么 / BookLeme — 把一本书编译成可安装的 Agent Skill。MIT，见 `LICENSE`。

## 不含第三方书籍内容

本仓库**不含任何书籍原文、封面图或受版权保护的文本**。`evals/cases/synthetic/` 下的文本为项目自撰合成样本；`evals/cases/public_domain/` 仅放公版文本；`evals/cases/user_books/` 被 `.gitignore` 排除，用户自备书绝不入库。

## 上游研究与案例致谢（仅作研究对齐，未导入任何代码）

- `virgiliojr94/book-to-skill`（MIT）：clone 到 `/Users/bertram/Desktop/BookLeme-上游参考/` 仅用于源码审计；本仓库未复制、未导入其任何代码或模板。借鉴的三条原理及逐条差异见 `docs/decisions/ADR-001-research-convergence.md`、`docs/UPSTREAM_AUDIT.md` 与 `README.md` 差异表。
- 微信公众号「数字生命卡兹克」《人生设计课》教练式 Prompt 案例、公众号「Alpha Engineer」《穿透财报》Skill 案例：仅作为「教练型 / 分析型」两类体裁的形态参考，未复制任何原文 Prompt、书籍内容或专有数据。

## 依赖

核心库零第三方依赖（仅 Python 标准库）。可选验收依赖（PyYAML / jsonschema / pytest / Jinja2）装在 `.vendor/`，不入库，仅用于调用官方 `quick_validate.py` 等双保险校验。

## 商标与平台

AlphaEngine / AlphaClaw / Claude Code / Codex / WorkBuddy 等名称归各自权利人所有，本项目与之无隶属或授权关系。
