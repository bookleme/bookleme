<p align="center">
  <img src="docs/assets/bookleme-banner.png" alt="BookLeme — From Books to Skills" width="100%">
</p>

<h1 align="center">读了么 · BookLeme</h1>

<p align="center">
  <a href="README.md"><strong>简体中文</strong></a> ·
  <a href="README.en.md">English</a>
</p>

<p align="center">
  <strong>把一本书编译成可安装的 Agent Skill —— 从「读过」到「会用」。</strong>
</p>

<p align="center">
  <a href="https://github.com/bookleme/bookleme/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/bookleme/bookleme/ci.yml?style=for-the-badge&label=CI&color=brightgreen" alt="CI"></a>
  <img src="https://img.shields.io/badge/License-MIT-blue?style=for-the-badge" alt="MIT License">
  <img src="https://img.shields.io/badge/Python-3.9%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/runtime-zero%20third--party%20deps-brightgreen?style=for-the-badge" alt="Zero deps">
  <img src="https://img.shields.io/badge/formats-PDF%20%C2%B7%20EPUB%20%C2%B7%20DOCX%20%C2%B7%20MD%20%C2%B7%20HTML%20%C2%B7%20RTF%20%C2%B7%20MOBI-green?style=for-the-badge" alt="Formats">
</p>

<p align="center">
  <a href="#why">为什么</a> ·
  <a href="#what">生成什么</a> ·
  <a href="#engines">双引擎</a> ·
  <a href="#fidelity">忠实度</a> ·
  <a href="#quickstart">快速开始</a> ·
  <a href="#arch">架构</a> ·
  <a href="#compare">同类对比</a> ·
  <a href="#roadmap">路线图</a> ·
  <a href="#docs">文档</a>
</p>

> **开发中（分支 `feat/2.0`，尚未发版）**：在 2.0.0 之上正在做三件事——LLM judge
> 接入（`groundedness` / V2 / V3 从 `null` 变真值）、读图 → 能力卡（视觉模型把图示
> 里的信息写成能力卡）、两个体裁插件内置化。**版本号仍为 2.0.0，未发布 2.1.0**；
> 本 README 的功能描述以已发布版为准，开发进度见
> [CHANGELOG.md 未发布段](CHANGELOG.md#未发布210-候选--分支-feat20--judge-真值--读图能力卡--插件内置化)。

---

<a id="why"></a>

## 为什么需要它

模型已经足够聪明，真正稀缺的是**人类实际的工作经验**。

而一本书里最值钱的，从来不是结论，而是作者的**工作方式**：

| 书 | 真正值钱的部分 |
|---|---|
| 《人生设计课》 | 不是人生答案，而是那串**提问顺序** —— 追问出用户自己的答案 |
| 《穿透财报》 | 不是行业结论，而是**判断条件 + 证据规则 + 证伪条件** |

问题是：读完之后，这些「工作方式」散落在 300 页里，无法被调用、无法被复用、无法被验证。

**BookLeme 把它们编译成可运行的 Agent Skill。**

<p align="center">
  <img src="docs/assets/bookleme-witch-study.png" alt="把知识编译成技能" width="72%">
</p>

### 三条设计原理

> ⚠️ **工程上采纳，但未经本项目验证** —— 「提炼结构而非摘要」只是设计选择，不是已被验证的结论。本项目把它标为 `UNVERIFIED`，不写成既成事实。

<table>
<tr>
<td width="33%" valign="top"><b>01 · 编译期 / 运行期分离</b><br/><br/>书只在编译时读一遍，运行时按需加载知识分片。</td>
<td width="33%" valign="top"><b>02 · 渐进式披露三级</b><br/><br/>常驻入口 → 按需分片 → 本地全文。</td>
<td width="33%" valign="top"><b>03 · 确定性 × 概率性解耦</b><br/><br/>确定性提取与概率性生成分离 —— 可单测、可 diff、可回归。</td>
</tr>
</table>

---

<a id="what"></a>

## 它生成什么

不是「读书笔记」，而是**两类可安装、可调用、可验证的产物**：

<p align="center">
  <img src="docs/assets/bookleme-witch-library.png" alt="双引擎产物" width="62%">
</p>

<table>
<tr><th></th><th>📚 知识包 · <code>knowledge_pack</code></th><th>⚡ 行为 Skill · <code>behavior_skill</code></th></tr>
<tr><td><b>形态</b></td><td>可查阅的结构化知识库</td><td>会运行的流程与状态机</td></tr>
<tr><td><b>装的是</b></td><td>Topic Index 路由表 + 按需加载的框架分片 + 决策速查 + 出处清单</td><td>角色 + 硬约束 + 状态机 + 具名输出契约 + 反模式 + 情绪护栏</td></tr>
<tr><td><b>典型场景</b></td><td>「这本书里 X 框架怎么用？」</td><td>「陪我做一次完整的人生设计对话」</td></tr>
<tr><td><b>样例</b></td><td><code>examples/reference/</code>（11 文件）</td><td><code>examples/coach/</code>（14 文件）</td></tr>
</table>

**核心特性**

- 🎛 **双引擎自动路由** —— 按 12 个确定性体裁特征自动判定，也可人工指定；两引擎共享中间表示，一本书不会被读两遍
- 🧩 **可插拔体裁插件** —— 新增体裁只需写一个文件（schema / 状态机 / 输出契约 / 反模式），零改核心
- 🔍 **逐字忠实度回验** —— 每条引文必须是原文精确子串，7 个指标区分 `measured` / `heuristic`
- 🛡 **版权工程化** —— 6 条确定性硬门 + provenance manifest + 默认私有，杜绝原文复现
- ⚙️ **零第三方依赖** —— 核心只用 Python 标准库
- 🔁 **stage 级幂等** —— sha256 断点续跑，删任一阶段产物只补该阶段

---

<a id="engines"></a>

## 双引擎 · 可插拔体裁

**体裁插件**决定一本书长成什么样子。内置 4 种：

| 插件 | 体裁 | 状态 | 关键设计 |
|---|---|---|---|
| `coach_dialogue` | 教练 / 自我对话 | ✅ 已实现 | 一问一答状态机、结论归用户、情绪护栏、可中断续聊 |
| `knowledge_reference` | 框架速查 | ✅ 已实现 | Topic Index 路由、按需加载、「书里没讲」必须拒答 |
| `professional_analysis` | 专业分析流水线 | 🔜 M4 | 证据绑定、口径表、**每条结论必填证伪条件** |
| `decision_checklist` | 决策清单 | 🔜 M4 | 阈值 / 权衡矩阵 / 决策树 / 不适用边界 |

> 新增体裁 = 在 `bookleme/plugins/user/<genre_id>.py` 写一个文件。字段契约见 [docs/PLUGIN_SPEC.md](docs/PLUGIN_SPEC.md)。

**插件强制声明**（缺一即拒绝加载）：`state_machine`、`output_contract`、`hard_constraints`、`anti_patterns`、`voice_calibration`（语气 / 称谓 / 禁用语 / **结论归属**）、`copyright_profile`、`trigger_words`（3–5 个中文触发词）、`eval_prompts`（必须含至少 1 个负例）。

---

<a id="fidelity"></a>

## 忠实度与版权

上游项目把「no hallucination」写成主张，却没有自动回验。**我们把「零幻觉」拆成 7 个可测指标**：

| 指标 | 类型 | 目标 | 实测 · 真实书稿批 |
|---|---|---|---|
| `citation_resolution_rate` | measured | 1.00 | ✅ 1.00 |
| `verbatim_violation_rate` | measured | 0.00 | ✅ 0.00 |
| `negative_refusal_rate` | measured | 1.00 | ✅ 1.00 |
| `trigger_hit_rate` | measured | ≥0.90 | ✅ 1.00 |
| `artifact_compliance_rate` | measured | 1.00 | ✅ 1.00 |
| `shingle_overlap_max` | measured | ≤0.10 | ✅ 0.0006 |
| `coverage_score` | measured | ≥0.85 | ✅ **1.00** |
| `groundedness` | heuristic | 只报告 | 有 judge 时为真实多数票；没配模型时 `null`（不伪造） |

> 📎 指标取自真实书稿批（273 页中文书，run 20261109-164758）：14/14 能力 verified、双引擎冒烟全过、版权六门全过（引文占比 0.016 / 上限 0.03）。早期合成书批过程值（`coverage_score` 0.667）如实留档。

> 🧪 **真实书稿实战**：273 页中文书端到端编译出的教练 Skill，已通过 9 轮真实对话回归 —— 一次一问 · 重力问题甄别 · 中断续聊断点恢复 · 万字蓝图交付。

**6 条版权硬门**（任一失败即不安装、不发布）：单条引文 ≤150 字且逐字可追溯 · 总引文比 ≤0.03 · 连续复制 ≤150 字 · 13 字 shingle 重叠 ≤0.10 · 产物不含全文 / 切片 · `contains_original_text = false`。

**版权边界**：输出是**结构化衍生笔记，不含原文段落**。使用权利默认按「未确认」处理——**私有自用照常，禁止公开分发**（要公开再用 `--user-rights` 声明并加 `--public --confirm-public PUBLISH`）。系统不会替你默认认领所有权。MIT 只覆盖转换器，不覆盖任何书籍。详见 [docs/COPYRIGHT.md](docs/COPYRIGHT.md)。

**图示也要守版权**：论文/网页里的原图会以图片资产形式进入产物（`assets/figures/`），这属于复制原图本体——因此含图产物在权利非自有/公版时**禁止公开分发**，私有安装不受影响。

---

<a id="quickstart"></a>

## 快速开始

```bash
git clone https://github.com/bookleme/bookleme.git
cd bookleme

# 零第三方依赖，Python ≥ 3.9 即可
python3 -m bookleme --version

# 先体检：环境、体裁、最近一次跑得怎么样（不需要你配置任何东西）
python3 -m bookleme doctor

# 端到端：书 → Skill
python3 -m bookleme run --input evals/cases/synthetic/coach_book.md --title "我的第一本书"

# 看看这次到底编译出了什么：单文件 HTML 检视台（双击即可打开）
python3 -m bookleme inspect
open out/<run_id>/inspect.html

# 校验产物（官方校验器 + 自有 lint + 版权硬门）
python3 -m bookleme validate examples/coach

# 回归测试
python3 -m unittest discover -s tests -v
```

**从网上与论文取材**（2.0 起）：

```bash
python3 -m bookleme fetch https://arxiv.org/pdf/1706.03762   # 论文 PDF（含图）
python3 -m bookleme fetch https://example.com/article         # 网页（含配图）
python3 -m bookleme run --input sources/public/xxx.pdf --title "论文标题"
```

抓来的资料会自动参与下一次编译；原书图片会被提取成 `assets/figures/` 资产并挂到对应能力卡。

**常用参数**

```bash
--engine auto|knowledge_pack|behavior_skill|both   # 产物形态（默认自动判定，一般不用指定）
--genre <plugin_id>                                # 强制体裁（默认由路由判定，填错会直接报错并列出可用值）
--no-router                                        # 跳过体裁判定，双引擎全出
--install                                          # 写入技能真源（默认关闭，只出产物）
--user-rights owned|licensed|public_domain|unknown # 仅在要公开分发时才需要声明
--public --confirm-public PUBLISH                  # 公开分发（裸词确认）
```

**关于「要不要配大模型」——默认不用**

编译期调模型（更深的卡片抽取、忠实度 judge、读图预填）**是可选增强，不是前提**：

- 没有任何配置 → 照常出产物，`groundedness` / `V2` / `V3` 如实显示 `null` 并注明「未接入，不伪造」；
- 想用 → 设置任意常见厂商的标准环境变量（如 `OPENAI_API_KEY` / `MOONSHOT_API_KEY` /
  `DASHSCOPE_API_KEY` / `DEEPSEEK_API_KEY` / `ARK_API_KEY` …）就会被**自动识别**，无需知道
  BookLeme 的专有变量名；也可写 `~/.bookleme/config.json` 的 `llm` 段；
- **读图不需要编译期视觉模型**：产物里带「读图任务」区块，由使用该技能的智能体
  （多数模型原生支持多模态）在需要时亲自看图作答——这才是这套东西该有的分工。

```bash
python3 -m bookleme doctor    # 看当前识别到什么
```

---

<a id="figures"></a>

## 图示：从「提取」到「用起来」

书和论文里最有信息量的往往是图。2.0 起，图不再被当作「图片附件」，而是**一等公民**：

| 环节 | 做什么 |
|---|---|
| 提取 | PDF 逐页抓栅格图 + 图注；网页抓 `<figure>/<figcaption>` 配图；矢量图如实标「仅图注」 |
| 锚定 | 图注逐字定位到原文；网页图用「图前正文片段」定位（实测锚定率 2/27 → **33/35**） |
| 挂接 | 挂到**最近的能力卡**（窗口 2000 字符内）——图注紧邻的讨论就是它的配套对象 |
| 交付 | 图片资产进 `assets/figures/`；`references/figures-index.md` 给锚定状态与页码 |
| 读图 | 产物带「读图任务」区块：由使用该技能的智能体**亲自看图**作答（多数模型原生支持多模态） |
| 解读（可选） | 编译期若检测到可用模型，会把图示直接写成能力卡（`origin=figure`，可信度 B） |

**图注原文不进产物**：图注是原文文本，22 条全量复制会把引文比顶到 13%（上限 3%），版权门会拦下。
逐字图注与精确位置存在共享 IR `figures.json` 里，随时可回读、可溯源。

---

<a id="inspect"></a>

## 检视台 · `bookleme inspect`（开发者工具，不属于产物）

> **它是什么**：一个**离线开发工具**，帮你看清「这次编译到底得到了什么」。
> **它不是什么**：不是技能的一部分，不进产物、不被智能体读取、不影响运行时体验。
> 技能真正的「界面」是下一节说的**对话与交付契约**。
> 用不上就删掉 `bookleme/inspect.py` + `bookleme/inspector_template.html` + CLI 子命令，核心功能不受影响。

编译产物原本散在几个 JSON 和一堆 Markdown 里，要看懂「这次到底得到了什么」只能手工翻文件。
检视台把**结论放在最前面**，单文件、零依赖、离线可开：

```bash
python3 -m bookleme inspect          # 默认最近一次 run
python3 -m bookleme inspect <run_id>  # 指定
open out/<run_id>/inspect.html
```

七个分区：**概览**（能不能用 · 关键数 · 产物路径一键复制）· **图示**（图库 + 锚定状态 + 点开看大图）·
**能力卡**（可搜可筛，每张卡带逐字锚点与体裁字段）· **忠实度**（7 指标 + judge 摘要 + 未验证假设折叠）·
**门禁**（6 条硬门的实测值与上限）· **阶段**（S0–S9 每段状态与备注）· **来源**（源清单与权利级别）。

深浅色跟随系统也可手动切换；手机上单列、宽屏多列；动画只用 transform/opacity，
`prefers-reduced-motion` 下全部降级为瞬时。

---

<a id="ux"></a>

## 技能在大模型里怎么被用（这才是产品的「界面」）

产物是给**智能体**用的技能包，它的使用体验由两件事决定：**怎么问**（连续深入对话）与
**怎么交**（出报告）。这两件事的契约在四个内置体裁里是**同一套**。

### 交付动线（四个体裁一致）

```
先结论（一句话就能用的判断）
  → 再依据（带出处、可逐字追溯）
    → 再边界（不适用条件 / 证伪条件）
      → 最后「还需要哪些数据」
```

### 连续深入对话的三条纪律

| 纪律 | 行为 |
|---|---|
| **可见进度** | 每轮反馈末尾交代「第 N 问 / 共 6-9 问」——只作交代，不催答、不连发 |
| **可打断可收回** | 用户想跳过某问、想回上一问、改主意 → 立刻照办并说明现在进行到哪一步 |
| **不打断手上的事** | 用户说「先这样/回头再说/到此为止」→ 立刻切 `paused` 状态，收束出当前结论就停，不追问 |

中断不丢进度：每轮把 `current_state / asked_questions / answers` 写入 `state.json`，
说「接着上次」即可从断点继续（`references/state-guide.md` 有完整约定）。

### 图不是附件，是一等公民

书和论文里最有信息量的往往是图。技能包会带「读图任务」区块：由**使用该技能的智能体**
亲自看图作答，并注明「依据 FIG-XXX（原文 p.N）」；图里看不清就明说「图中此处无法辨认」。

---

<a id="arch"></a>

## 架构 · S0–S9 编译流水线

```
S0 输入登记 ─► S1 确定性提取 ─► S2 中文分段 ─┬─► S3 体裁路由 ────────┐
                                              └─► S4 原子能力抽取 ────┼─► S5 忠实度校验
                                                    （共享中间表示）  ┘
                                                                          │
                                S9 冒烟评测 ◄─ S8 安装 ◄─ S7 四重校验 ◄─ S6 双引擎渲染
```

**关键设计**：S3 与 S4 并行且都以 S2 为输入；两引擎共享 S1/S2/S4/S5 全部中间表示，**只有 S6 分流** —— 一本书不会被读两遍。

| 层 | 职责 | 执行者 |
|---|---|---|
| S0–S2 | 提取、归一、中文分段（不依赖 "Chapter N"） | 确定性 Python |
| S3 | 12 特征体裁路由 + 歧义兜底（自动双引擎，不停人） | 确定性 + 可插拔 LLM |
| S4 | 原子能力抽取（RIA++ 六段） | 确定性抽取器 + 可选 LLM 抽取器（OpenAI 兼容 · 引文终身逐字回验 · 缺配置自动回退） |
| S5 | 逐字引文校验 + claim ledger + 7 指标 | 确定性 + judge 占位 |
| S6 | 插件驱动渲染（标准库字符串模板） | 确定性 Python |
| S7–S9 | 四重校验、幂等安装、冒烟评测 | 确定性 Python |

详细设计：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

<a id="compare"></a>

## 与同类项目对比

<table>
<tr><th></th><th><b>读了么 BookLeme</b></th><th><code>virgiliojr94/book-to-skill</code></th><th><code>bookforge-ai/bookforge-skills</code></th></tr>
<tr><td><b>定位</b></td><td>书 → Skill 的<b>编译器工具链</b></td><td>书 → 知识包（靠宿主 Agent 执行）</td><td>已蒸馏 skills 的<b>产物库</b></td></tr>
<tr><td><b>产物</b></td><td>知识包 <b>＋</b> 会运行的行为 Skill</td><td>仅知识包</td><td>skills 文件集合</td></tr>
<tr><td><b>生成器</b></td><td>代码化 stage DAG，可单测 / 可 diff</td><td>一份巨型 SKILL.md 操作规程</td><td>—</td></tr>
<tr><td><b>忠实度</b></td><td>7 指标 + 逐字引文校验 + 负例拒答</td><td>无自动回验</td><td>—</td></tr>
<tr><td><b>体裁</b></td><td>可插拔插件，新增体裁只写一文件</td><td>固定 5 文件 + 10 节模板</td><td>—</td></tr>
<tr><td><b>版权</b></td><td>6 条确定性硬门 + 默认私有</td><td>prompt 规则 + 自律</td><td>CC-BY-SA-4.0</td></tr>
<tr><td><b>许可</b></td><td>MIT</td><td>MIT</td><td>CC-BY-SA-4.0</td></tr>
</table>

> 本项目自研自对 `book-to-skill` 的源码审计之后，**未导入其任何代码或模板**；与 `bookforge-ai` 无隶属关系，未使用其任何内容。逐条差异见 [docs/decisions/ADR-001-research-convergence.md](docs/decisions/ADR-001-research-convergence.md)。

---

<a id="roadmap"></a>

## 路线图

- ✅ **M0–M3** 研究对齐 · 设计冻结 · 核心引擎 · 首批插件与产物（**当前**）
- 🔜 **M4** 补齐 `professional_analysis` / `decision_checklist` 插件、4 段合成书评测集、两本书 dogfood、接入 LLM judge
- 🔜 **M5** 真源 Skill 安装、`evals/baseline.json` 出实测数、跨书能力合并

**如实标注的边界**（本项目不夸大）：LLM judge 未接入（`groundedness` / V2 / V3 仍为 `null`，只报告不设硬门）；`professional_analysis` 与 `decision_checklist` 尚在 M4；真实书稿批 `coverage_score` 已达 1.00，早期合成书批过程值 0.667 如实留档。

---

<a id="docs"></a>

## 文档

| 文档 | 内容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | S0–S9 流水线、幂等模型、共享 IR、可观测性 |
| [docs/PLUGIN_SPEC.md](docs/PLUGIN_SPEC.md) | 18 个插件必填字段、4 内置插件骨架、加载与安全扫描 |
| [docs/FIDELITY.md](docs/FIDELITY.md) | 7 指标、逐字引文校验、V1/V2/V3、未验证假设表 |
| [docs/COPYRIGHT.md](docs/COPYRIGHT.md) | 混合输入、provenance、6 条硬门、可分发性判定 |
| [docs/EVALS.md](docs/EVALS.md) | 评测集设计、22 条硬验收清单、冒烟测试 |
| [docs/ACCEPTANCE-M0-M3.md](docs/ACCEPTANCE-M0-M3.md) | 逐条验收记录与实测数字 |
| [docs/UPSTREAM_AUDIT.md](docs/UPSTREAM_AUDIT.md) | 上游源码逐字审计笔记 |
| [docs/decisions/](docs/decisions/) | ADR-001 研究收敛性 · ADR-002 双引擎 · ADR-003 忠实度指标 |

---

## 贡献

欢迎 Issue 与 PR。提交前请跑：

```bash
python3 -m unittest discover -s tests -v
python3 -m bookleme schema --state
python3 -m bookleme plugin validate bookleme/plugins/builtin/coach_dialogue.py
```

**红线**：绝不提交书籍原文 / 封面 / 扫描件；绝不导入上游仓库代码；绝不把未验证假设写成既成事实。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 许可

[MIT](LICENSE) © 2026 BookLeme contributors

MIT 只覆盖转换器（代码 + 技能定义），**不覆盖任何用本工具处理的书籍或文档**。详见 [NOTICE.md](NOTICE.md)。

<p align="center">
  <sub>📖 读了么 —— 你读了吗？读了，就变成你的技能。</sub>
</p>
