# Changelog

## 1.0.0 (2026-11-13) — 首个正式版：LLM 抽取器 + 真实书稿实战

收敛 0.1.x 三个补丁轮的全部遗留项，并补上两件此前未入账的大事：S4 LLM 抽取器落地、
两本真实书稿端到端 dogfood。至此「确定性抽取 → LLM 抽取」三级调度、逐字引文终身回验、
双引擎插件体系全部成形，以 1.0.0 作为首个稳定版本发布（MIT，github.com/bookleme/bookleme）。

### 亮点

- **S4 接入 LLM 抽取器**（`443360e`）：OpenAI 兼容 chat/completions 适配器（stdlib
  urllib，零第三方依赖），环境变量 `BOOKLEME_LLM_BASE_URL/API_KEY/MODEL/TIMEOUT` 配置，
  缺配置自动回退确定性抽取器、流水线零中断；`deterministic-markup → llm → heuristic`
  三级调度。**引文终身逐字回验**：`_locate_quote_verbatim()` 把模型引文定位回原文——
  精确 find 失败则空白不敏感定位后切原文子串，引文恒为原文切片、绝不收模型的空白版本，
  不可回溯时兜底确定性首句。每次真实 HTTP 计 `llm_calls`，`model_fingerprint =
  sha256(model + prompt_version)` 绑定 prompt 版本防换模型漂移；版本化 prompt
  `llm/prompts/capability_extract_v1.md`（R_quote 强制逐字 8-24 字）。部分模型
  （kimi-k3）仅接受 `temperature=1`，遇 400 温度错误自动重试一次。可信度三级：
  S(0.9 markup) / B(0.7 llm) / C(0.4 heuristic)。
- **真实书稿实战暴露并修复 3 处合成样例测不出的缺陷**（`40b32f1`）：① S2 目录污染——
  目录页「第N章」行被标题正则误判为段，新增 `_merge_duplicate_headings()` 同名标题
  合并、被删段区间并入后继段、序言并入首段；② S4 引文非逐字——`re.sub(r'\s+',' ')`
  折叠换行导致引文不再是原文子串，重写为 `_first_sentence_quote()` 纯切片引文 +
  从句边界截断（16 字预算 + 8 边界窗口，消「有这样一」式半句），并防引文取自目录行；
  ③ S2 缓存不失效——`s2_hash` 纳入分段源码。真实书稿实测：14/14 能力 verified、
  `citation_resolution=1.0`、`verbatim_violation=0`、`coverage=1.0`、版权六门全过。
- **P0–P2 三轮修复，34 项回归全过**（`5a07430`/`1d01426`/`12cf1ea`）：P0 续聊断链
  （每轮写 `state.json` + 运行期路径约定 `~/.bookleme/sessions`，9 轮真实教练会话实测）；
  P1 契约渲染收口（`required_fields`/`file_name` 落盘、session-map 提问顺序八阶段、
  S6 缓存纳入渲染器源码）；P2 清尾（漏字/单位命名/冒烟用例/死元数据归零）。
- **开源发布与品牌**（`2ae14b0`…`df1e1b9`）：MIT License、GitHub Actions CI 绿、
  README 中英双版（banner/徽章/导航锚点/三方对比）、公开前隐私清理（源码路径参数化
  `BOOKLEME_SKILLS_ROOT`/`BOOKLEME_CLAUDE_SKILLS`、零绝对路径/邮箱/凭证入库）。
- **两本真实书稿 dogfood**：《斯坦福大学人生设计课》（209 页 PDF）双引擎编译 +
  9 轮真实教练对话回归；《这本书可能救你的命》（273 页 PDF）双引擎编译
  （`knowledge_pack` + `behavior_skill`），`citation_resolution=1.0`、
  `shingle_overlap=0.0008`、版权六门全过。

### Added
- S4 LLM 抽取器与版本化 prompt（`443360e`）
- `coach-resume`（中断续聊恢复）与 `coach-long-dialogue`（长对话纪律）冒烟用例（`12cf1ea`）
- session-map：完整会话八阶段提问序 + 6-9 题预算 + 断点恢复对照（`1d01426`）
- CI / License / Python / 零依赖徽章（`e2a8d84`）

### Fixed
- 续聊断链：SKILL.md 指示每轮写 `state.json`，state 目录改运行期可解析（`5a07430`）
- 输出格式双 schema 矛盾 → 统一「正文 + 元信息附录」双层（`5a07430`）
- `output_contract.required_fields` 与 `file_name` 交付约定不再被静默丢弃（`1d01426`）
- S6 缓存哈希纳入 `render/*.py` 源码，改渲染器不再命中陈旧缓存（`1d01426`）
- 真实书稿三缺陷：目录污染 / 引文非逐字 / S2 缓存不失效（`40b32f1`）
- 渲染触发语双重嵌套（`40b32f1`）
- Step 3「带上处」漏字、`min_tokens`→`min_chars` 单位命名、intent_map 死元数据（`12cf1ea`）
- LICENSE 精简为标准 MIT 文本以便 GitHub licensee 识别（`2bcfe3f`）

### Documentation
- README 中英双版 + 去折叠排版升级，忠实度表换真实书稿批实测值（`7aa923a`/`df1e1b9`）
- NOTICE 补插图说明与同名项目区分（`2bcfe3f`/`7aa923a`）

### Notes on selected changes

**引文终身逐字回验** —— LLM 抽取器最危险的失败模式不是"没抽出来"，而是"抽出来的引文
不是原文"（缩进/换行/标点被模型规范化），下游逐字校验会全灭。`_locate_quote_verbatim()`
的策略是：**永远从原文切片，永远不用模型给的字符串**——先精确 find，失败则两侧空白
不敏感定位，再取原文子串；连兜底的启发式首句也是原文切片。配合 S5 的
`verbatim_violation` 指标，引文从生成到消费全程可回溯。

**三级调度与诚实标注** —— `deterministic-markup → llm → heuristic` 按可用性降级，
任何一级失败都不中断流水线；`llm_calls` 与 `model_fingerprint` 进 metrics，未调用 LLM
时如实记 0/`null`，不伪造数字。`groundedness`/V2/V3 仍为 heuristic（LLM judge 未接入），
`coverage_score` 实测值如实保留（合成批 0.667 未达 0.85 目标、真实书稿批 1.00 达标）。

**examples/ 的 provenance 仍标注生成时的 0.1.x 版本**——它们是 0.1.x 时期真实生成的
样例快照，属历史证据，1.0.0 未重跑刷新，故 `references/provenance.md` 中的
「生成引擎：BookLeme 0.1.0」为当时的实况记录。

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
