# Changelog

## 0.1.0 (2026-11-08) — M0/M1/M2/M3 可运行骨架

- 上游 `virgiliojr94/book-to-skill` 源码审计与四方收敛性比较（隔离参考目录，未导入代码）。
- S0–S9 stage DAG：确定性提取、中英文标题分段、12 特征体裁路由、原子能力抽取、逐字引文校验、插件渲染、双校验与版权硬门、幂等安装、冒烟评测。
- 7 个 JSON Schema、外置路由权重、2 个内置插件（coach_dialogue / knowledge_reference）、双引擎自动路由与歧义兜底。
- 版权工程化：provenance manifest、6 条不抄原文硬检查、默认私有、公开分发启动前裸词确认。
- 零第三方依赖核心；可选依赖仅用于官方 `quick_validate.py` / jsonschema / pytest 双保险。
- **修正**：归一规则由「整篇 NFKC」改为「只剥离不可见字符 + 仅折叠康熙部首 U+2F00–U+2FDF 与 CJK 兼容表意文字 U+F900–U+FAFF」；依据上游 `sanitize.py:168-176` 及其测试，整篇 NFKC 会改写全角/连字/带圈数字并破坏逐字引文精确匹配。已失效缓存重跑全部批次，新增回归测试锁死。
- **修正（跨 run 一致性）**：`sources.json` 改用稳定 `run_id=shared-<sha12>` + 文件 mtime；`provenance_manifest.json`、`router_result.json`、`router_evidence.json` 从共享 `cache/` 移到 `out/<run_id>/`，避免不同 run 互相覆盖导致追溯串味与单/双引擎串味；`capabilities.json` 不再写入 per-run 路由结果。新增 2 项回归测试，共 16 项。
- **文档收口**：C1–C7 表述精确化全部落地（零 LLM 口径、提取链归属、PD-05 状态、不宣称已验证、幂等粒度、四类性能数字禁令）；5 份设计文档统一「M2 实现口径」提示块与 LLM 措辞；`EVALS.md` 22 条清单与计划逐字一致。

**如实标注的未完成项**：S4 为确定性抽取器（LLM 抽取器是接口占位）；S3 歧义判定为确定性兜底（`llm_judge_invoked: false`）；V2/V3/groundedness 为 heuristic 且值为 `null`；`professional_analysis` 与 `decision_checklist` 插件、跨书合并、OCR/图表理解、Web UI 与市场收益属后续批次。
