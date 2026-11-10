# Changelog

## 0.1.3 (2026-11-10) — P2 清尾：全部遗留项归零

- **漏字修复**：Step 3 "每条判断都要带上处" → "带上出处"（渲染层一处，双引擎产物同修）。
- **单位命名修复**：`output_contract.min_tokens/max_tokens` → `min_chars/max_chars`
  （渲染单位是「字」，字段名不再误导；render 层保留旧键回退，第三方插件模板不受影响）。
- **冒烟用例补齐**：新增 `coach-resume`（中断续聊恢复：先读 state.json 定位断点、不重复已问）
  与 `coach-long-dialogue`（拒绝问卷化、维持一次一问与 6-9 题预算）两条，覆盖此前缺的
  续聊与长对话纪律行为。
- **intent_map 死元数据移除**：coach_dialogue 的错位映射（奥德赛计划→framework-04，
  真实应为 05）与 knowledge_reference 的冗余映射一并删除——无人消费且与能力序号漂移的
  元数据不再随插件发布。
- 回归 +4（TestP2Cleanup：漏字双引擎 / 单位命名 / 冒烟覆盖 / 死元数据清零），共 34 项全过。

**至此 0.1.1/0.1.2 如实标注的未办项全部了结。** 后续批次候选（非缺陷）：V2/V3 groundedness
真实化、professional_analysis / decision_checklist 插件、跨书合并、OCR/图表理解。

## 0.1.2 (2026-11-10) — P1 四项：契约渲染收口 + 提问顺序落盘

- **required_fields 死契约修复**：`output_contract.required_fields` 渲染进 SKILL.md「必备字段（缺一不可）」，
  并生成进 `assets/blueprint-template.md` 的「必备字段核对」清单——「证伪/放弃条件」「最小原型」等
  字段要求不再被静默丢弃。
- **孤儿资产修复**：工作流 Step 4 显式引用 `assets/blueprint-template.md` 作为正文骨架
  （仅 behavior_skill 引擎；knowledge_pack 无此资产）。
- **交付约定落盘**：`output_contract.file_name` 渲染为「交付约定」（Markdown 落盘、建议命名
  `<产物名>_<YYYY-MM-DD>.md`、交付时给出完整文件绝对路径），消除执行者即兴发挥。
- **提问顺序落盘（session-map）**：coach_dialogue 新增 `session_map`——完整会话默认八阶段序
  （真问题甄别→仪表盘→指南针→能量地图→锚问题→奥德赛计划→四维评分→原型+失败免疫收尾）、
  6-9 题目预算、按 topic-index 定位框架卡（不写死编号）、断点恢复对照 state.json；
  渲染为 `references/session-map.md`，Step 2 挂载。至此插件文档"价值在提问顺序"名实相符。
- **示例自适应**：速查类产物（必备板块本身即溯源元信息）保持单示例，「正文+元信息附录」双层
  示例仅用于板块≠元信息的产物，消除 kp 再生时的示例冗余（上一批标注的遗留项一并了结）。
- **顺手修（P2 新发现，直接威胁本批交付）**：S6 缓存哈希此前只含插件源码、不含渲染器
  ——改 `render/skill.py` 会命中陈旧缓存吐旧产物（与曾修复的 s2_hash 同类缺陷）→
  哈希纳入 `render/*.py` 源码内容，结构锁测试锁死。
- 回归 +4（TestOutputContractRendering：契约字段渲染 / 模板引用与必备字段清单 /
  session-map 生成与挂载 / S6 缓存结构锁），共 30 项全过。

**如实标注的未办项（P2）**：`routing_rules.intent_map` 仍为死元数据且与真实能力序号不一致
（奥德赛计划→framework-04 应为 05）；冒烟用例缺中断续聊与长对话纪律覆盖；`render/skill.py`
Step 3 "带上处"漏字；`min_tokens/max_tokens` 字段名与渲染单位「字」不一致。

## 0.1.1 (2026-11-09) — P0 修复：可中断续聊链路 + 输出格式单一 schema

首次真实委托（9 轮教练会话，产出完整人生设计蓝图）实测暴露两处断链，本次修复并回归：

- **P0 续聊断链**：此前 SKILL.md 只指示"恢复时读 state.json"，全链路无人指示写入，且
  `state-guide.md` 给出构建期相对路径 `out/sessions/...`（装机后不可解析）——真实会话 9 轮
  未产生任何 state 文件，中断即全丢。修复：① 工作流与 Gotchas 明确"每轮问答结束写入
  state.json"；② `state_io.py` 新增 `default_state_dir()`（env `BOOKLEME_STATE_DIR`，
  回落 `~/.bookleme/sessions`），`load/save` 的 `state_dir` 改为可省略；③ state-guide 改为
  运行期可解析约定并渲染状态机取值（opening…close）。
- **P0 输出格式双 schema 矛盾**：`output_seed` 的七板块必备结构与硬编码"示例结构"的元信息
  条目互相冲突，真实交付只能靠执行者即兴合并。修复：示例结构改为统一双层——正文逐节
  （由 `output_contract.sections` 生成）+「元信息附录」溯源层，明确"两层都要交付"。
- 新增回归测试 3 项（TestRuntimeStateContract：状态写读链路、state_io 往返与默认目录、
  单 schema 与板块覆盖），共 26 项全过。

**如实标注的未办项**（P1/P2，已列入后续批次）：`output_contract.required_fields` 尚未渲染
进产物（证伪/放弃条件会被静默丢弃）；`assets/blueprint-template.md` 与 `file_name` 交付约定
未被 SKILL.md 引用；`routing_rules.intent_map` 为死元数据且与真实能力序号不一致；冒烟用例
缺中断续聊与长对话纪律覆盖；`render/skill.py` Step 3 "带上处"漏字待修。

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
