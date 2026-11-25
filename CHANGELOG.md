# Changelog

## 2.1.0（未发布 · 分支 feat/2.0）— 把「体验」落到产物价值，而不是界面

一句话：**复杂留给我们系统，不留给用户**。但「体验」不等于做一个网页——这一版先把自己
做偏的东西撤回，再把同一条思想落到**产物本身能不能用**上。

### Reverted（做偏的部分，已撤回）

- **撤回检视台（单文件 HTML UI）**：`inspect.py` + `inspector_template.html` + CLI 子命令
  + 4 项测试全部删除。它是给自己看的开发者工具，不是产品价值；技能真正的界面是
  **它在大模型里的表现**（出报告 / 连续深入对话）。
  它真正回答的那个问题（「这次到底得到了什么」）改由 `bookleme check` 用文本回答。

### Added（把界面该回答的问题，放回命令行）

- **`bookleme check [run_id]`**：产物可用性验收，第一行给判决（可直接用 / 能用但有薄处 /
  不建议用）。逐产物给出：能回答什么（框架名）、能不能照着做（有步骤+边界的比例）、
  出处是否可逐字定位、不能答什么、哪里薄（未锚定的图、缺 smoke、索引断链）。
  `--json` 给机器，`--strict` 供 CI 把「可改进」也当失败。
- **`references/coverage.md`**：由原文目录生成的覆盖范围（不做推断），并在 SKILL.md Step 1
  与 topic-index 里指路——智能体判断「书里有没有」时有据可依，不再凭印象外推。
- **`evals/smoke.md` 对所有体裁生成**（此前只有行为类）：速查类同样需要负例与边界用例。
- **SKILL.md 增「方法主线」**：由原文目录给出这本书的路线（第一章 → 第二章 …），
  取代纯模板话术，读者一眼能判断这技能覆盖的是不是他要的东西。
- **安装前预检全部目标**：目标是多个产物时先全查一遍冲突，宁可一个都不装，
  也不装了一半才发现；显示名截断不再切坏括号（`书（合成评测·教练` → `书·教练`）。

### Changed（系统能判断的，不留给用户）

- **输入直接收**：`--input` 现在接受**目录**（自动摊平支持的文档、跳过隐藏文件）与
  **http(s) 网址**（自动抓取为公开源后编译）——不必再「先 fetch 再 run、再记路径」。
- **书名自动推断**：依次取文档元数据 / 首个一级标题 / 清洗过的文件名，并在日志里
  说明**取自哪里**（用户才知道要不要用 `--title` 覆盖）。
- **公开源不再静默混入语料**：以前只要 fetch 过一次，之后每次 run 都会把那些内容
  并进语料（表现为书名是你的、覆盖章节和图却是别人的）。现在只纳入**本次抓取的 URL**，
  或显式加 `--include-public`；被跳过的数量会打出来，不静默。
- **run 结束给下一步**：产物路径之外，直接给 `check` / `eval` 命令，以及「加 `--install` 即可安装」。
- **抓取失败说人话**：SSL / 代理失败时给出「先手动下载，再用 --input 指向本地文件」，
  不再把 15 行 urllib 栈丢给用户。

### Fixed（审查轮：安全与诚实性）

- **密钥与端点跨厂商错配（安全）**：配置指了 A 家端点、密钥来自 B 家时，会把 B 的密钥
  发往 A 的服务器。现在端点与密钥必须同源，绝不跨厂商补齐。
- **LLM 配置进缓存指纹**：配了模型不重算、换模型指纹不变——指标会被当成同一次实验。
- **读图卡出处锚点错位**：切引文后又用 `find` 重找，落到引文首次出现处（目录页）。
  现在直接用图的权威锚点，`verify_quotes` 尊重已有锚点。
- **judge 平票记为「未知」**（此前记 False，会得出 100% 不支持率的假结论）；
  指纹绑定两个 prompt；票数按实际可用 persona 上报。
- **`fetch` 拒绝 `file://` 与内网/环回/云元数据地址**（此前是任意文件读取器）。
- **`claim_ledger.source_tier` 与 provenance 同源**（此前写的是抽取方式等级）。
- 插件 validator 遇 `None` 字段不再抛裸栈；安全扫描只扫代码不扫注释；
  `--plugin-dir` 不存在会明说；`--genre` 拼错开跑前报错并列出可用值。
- 图注与位图按序配对不确定时如实标注（`pairing_uncertain` / `unlabeled_figure`）。
- 终端去掉逐文件 `wrote` 噪音与「预计 30-45 分钟」的假承诺，改打真实耗时。

### 回归

**91 项全过**（新增：check 可用性验收、目录输入与书名推断、公开源隔离、coverage 只含本书目录、
judge 平票/指纹/票数、占位符单次替换、validator 类型闸门、配置 schema 等）。


## 2.0.0 (2026-11-24) — 多源知识编译：网页 + 论文 + 图表资产

输入从「一本书」扩展到「书 + 网页 + 论文」，且**图必须用起来**：原文/原网页的图示
被提取为产物资产并挂接到对应能力卡。真实的图解博客与 arXiv 论文端到端实测通过。

### 亮点

- **`bookleme fetch <url>`（新子命令）**：抓取公开网页/论文落盘 `sources/public/`
  （版权内容不入库，.gitignore 全覆盖）。HTML → 正文（复用零依赖 html 提取器）+
  页面图片下载（`<figure>/<figcaption>/<img alt>` 语义，magic bytes 识别格式，
  24 张/2MB 上限）；PDF → 实体文件 + sidecar 元数据（url/tier/license_note/
  retrieved_at）。stdlib urllib（自动走 http_proxy），零第三方依赖。
- **图表提取（`extract/figures.py`）**：图注识别（图N/表N/Figure N/Table N，
  纯函数可测）+ pypdf 逐页栅格图提取；同页文档序配对（图注↔位图），配不上的
  如实落「仅图注」/「仅位图」。**图注逐字锚定**到全局归一化语料（char 级可溯），
  定位不到置 `null` 不伪造。矢量图（多数 LaTeX 论文）诚实降级为 caption-only。
- **图挂接到能力卡**：最近能力卡（窗口 2000 字符内）——图注紧邻的讨论即配套对象。
  （实测教训：能力卡 span 是引文句、图注是另一段文本，「区间包含」永远挂不上。）
  渲染「配套图示」块 + `assets/figures/` 全量图片资产 + `references/figures-index.md`
  锚定状态索引。**图注原文不复制入产物**（版权纪律：22 条图注全量入产物会把引文比
  推到 13%，被版权门正确拦下）；逐字图注存共享 IR `figures.json`。
- **图片分发政策（版权门）**：原文图片随衍生笔记公开 = 复制传播原图，比文本引文
  性质更重——非自有/公版一律阻断公开分发（`figure_distribution_block` 纯函数，
  私有安装不受影响）。版权门如实计数图片资产与图注引文比。
- **多源合编**：`sources/public/` 工作集自动入编译，与 `--input` 按 sha256 去重
  （防同一文件重复计源）。实测：arXiv 论文 PDF + 图解博客 HTML 合编，
  35 图（27 位图进产物）、auto 路由单引擎、版权六门全过。
- **Schema**：新增 `figures.schema.json`；能力卡加可选 `figure_refs`；
  内置子集校验器补 `pattern/minLength/maxLength` 执法（此前 Schema 写了但没执行）。
- **dogfood 实测（arXiv 1706.03762 + jalammar 图解博客）**：
  论文批 22 图（6 位图/16 仅图注，20 锚定），引文比 0.017；多源批 35 图（27 位图），
  引文比 0.016、shingle 0.0043，`all_passed=True`。图挂接语义正确
  （Transformer 架构图 → 「3.1 Encoder and Decoder」卡）。

### Added
- `bookleme fetch` 子命令与 `sources/public/` 公开源工作集（文件型 + 文本型）
- `extract/figures.py`：图注识别 / PDF 栅格图提取 / 网页图收编 / 逐字锚定
- `figures.json` 共享 IR + `schemas/figures.schema.json`
- 能力卡 `figure_refs`、产物 `assets/figures/`、`references/figures-index.md`
- 「配套图示」渲染块（不复制图注原文）
- `figure_distribution_block` 图片分发政策（纯函数）
- 回归测试 +9（图注定位/锚定/挂接/渲染/抓取 mock/版权门/分发政策/schema）

### Fixed
- S0 多源去重：`--input` 与 `sources/public/` 同一文件按 sha256 去重，防重复计源
- schema_check 补齐 `pattern/minLength/maxLength`（Schema 声明与执法不一致）

### Notes on selected changes

**图注为什么不复制进产物** —— dogfood 实测：22 条图注逐字渲染把引文比推到 13%
（上限 3%），版权门正确拦截。图注是原文文本，全量列出就是复制。定稿口径：
图片资产（图本体）全量交付、图注原文只存共享 IR `figures.json`（逐字可溯），
产物只留元数据（ID/类型/锚定状态/页码/资产路径）与回读指引——「图用起来」
指图本身可用（打开即看），不是把图注抄进笔记。

**矢量图的诚实降级** —— arXiv 论文多为 LaTeX 矢量图，pypdf 提不到栅格位图，
如实落「仅图注」（caption-only），绝不截图伪造、绝不留空充数。实测论文 16/22
为矢量图；网页图（PNG/JPG）则全量提取（博客 24 张）。

**已知不完美（如实记录）**：图注正则会把「Table 2 summarizes...」式正文句
误判为图注（论文批 22 条中约 1-2 条）；网页 alt-only 图片无锚定位（不挂卡）。
均不影响交付正确性，留待后续批次收紧。

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
