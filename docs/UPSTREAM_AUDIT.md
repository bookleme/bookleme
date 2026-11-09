# BookLeme M0 — 上游本地源码审计笔记

> **本文件仅用于研究对齐，未导入任何上游代码。**
> 全部结论来自对只读参考目录 `$UPSTREAM_REF/` 的 `Read` / `Grep` 逐字阅读；本轮未 `git clone`、未联网、未修改参考目录内任何文件、未把上游任何源码或模板复制进 `bookleme/` 项目。
> 审计对象：上游 `virgiliojr94/book-to-skill`（MIT / Python / master）。star 数等 GitHub 元数据不在此目录内，属计划模式在线取证范畴，见 ADR-001。
> 审计日期：2026-11-08（M0 研究对齐阶段）。本机 `python3` 为 3.13.12，缺 `yaml/jsonschema/pytest/jinja2`（见 ADR-001 末节）。

---

## 0. 审计方法与技术约束

- 手段：仅 `Read`（逐字）/ `Grep`（正则全仓）+ 一次 `python3 -c` 验证 Unicode NFKC 行为。无网络请求、无 git 操作、无文件写入（除本文件及 ADR/baseline 外）。
- 行号：全部以本次本地 clone 的文件实际行号为准，格式 `路径:行号`。
- 术语：「零 LLM」= 代码里不存在对 LLM 推理 API 的调用；「确定性」= 同输入恒同输出；「降级」= 可选依赖缺失时回退到标准库实现。
- 未逐字阅读但与结论相关的文件：`parsers/{calibre,docx,rtf}.py`、`pdf_inspector_integration.py`、`scripts/extract.py`、`exceptions.py`、`docs/{architecture,faq,performance}.md`、`README.md`（这些通过 Grep 与依赖关系核对，非逐字）。

---

## 1. 按文件的关键发现

### 1.1 `book_to_skill/parsers/pdf.py`

| 行号 | 发现 |
|---|---|
| `:12` | `_PART_HEADER`：识别 `Part I / Part 2` 分部标题。 |
| `:29-30` | `_ROMAN_1_99` / `_PDF_PAGE_NUM`：罗马页码用「规范数字形状」精确匹配，而非 `[ivxlcdm]{1,7}`。注释 `:14-28` 说明后者会把 `MIX/CIVIL/DIM/MILD/VIVID` 等真实单词当作页码删掉——**宁可留一个游离数字也不删真文本**。 |
| `:38-81` | `clean_pdftotext`：以 `\f` 分页；统计每页首尾行，出现于 >1/2 页的判为页眉/页脚并仅在页边删除（`:71-74` 只删 `first`/`last` 行，避免误删正文中与页眉同名的章节标题）；末尾做连字符换行合并（`:79-81` 自承「naive dehyphenation」可能把 `well-\nknown` 拼成 `wellknown`）。 |
| `:84-98` | `extract_with_pdftotext`：`subprocess.run(["pdftotext","-layout","-enc","UTF-8",...,"-"])`，`timeout=120`，`errors="replace"`，失败返回 `None`。 |
| `:101-117` | `looks_image_only`：只取前 5 页，无文本即判扫描版；无 `pdftotext` 时返回 `False` 让后续链兜底。 |
| `:120-138` | `extract_with_pypdf`：逐页 `extract_text()`，用 `\f` 拼接后复用 `clean_pdftotext`。 |
| `:141-184` | `extract_pypdf_page_records`：物理页独立记录，含 `low_confidence_reasons`（`sanitized_invisible_text` / `empty_page_text` / `possible_joined_decimal_cells`），`requires_manual_review` 标志；注释 `:144-147` 明确「文本层顺序不等于已验证的表格布局或 full_text 偏移」。 |
| `:187-210` | `pdf_outline_titles`：读取 PDF 内嵌书签（outline）；若顶层是 `Part` 且有子项，则用子项（章）替代分部——「Part I > Chapter 1..7」产出章而非部。 |
| `:213-242` | `pdf_outline_all_titles`：递归 `walk` 收集全部书签标题（文档序）。 |
| `:245-254` | `extract_with_pdfminer`：同样 form-feed 分页。 |
| `:257-277` | `extract_with_docling`：`do_ocr=False`、`do_table_structure=True`、`export_to_markdown()`；仅 technical 模式启用。这是上游**唯一**对表格结构有显式处理的路径。 |
| `:280-320` | `count_pages`：`pdfinfo` → `pypdf` → `pdfminer` 数 `\f` 的三级兜底，全失败返回 0。 |

**降级结论**：PDF 文本链为 `pdftotext → pypdf → pdfminer`（调用点在 `utils.py:1543-1573`），technical 模式先试 `docling`；**全仓没有 `pdfplumber`**。

### 1.2 `book_to_skill/parsers/epub.py`

| 行号 | 发现 |
|---|---|
| `:14-25` | `_IMAGE_EXTENSIONS`：图像成员清单。 |
| `:49-57` | `_decode_epub_xml`：先判 UTF-32 BOM（其前缀与 UTF-16 LE BOM 相同，必须长者优先），再 UTF-16，最后 UTF-8 `errors="replace"`。 |
| `:68-104` | `extract_with_ebooklib`：`ebooklib` + `BeautifulSoup`，按 **spine 顺序**（非 manifest href 顺序）取 `ITEM_DOCUMENT`，去重后再补漏。 |
| `:107-130` | `_find_opf_path`：先读 `META-INF/container.xml` 的 `full-path`，失败再 glob 任意 `.opf`。 |
| `:133-141` | `_resolve_manifest_href`：把 OPF IRI 当 URL 解析（`unquote(urlsplit(html.unescape(href)).path)`）再 `posixpath.normpath`。 |
| `:144-210` | `extract_with_zipfile`：**纯标准库** EPUB 抽取器（zipfile + 复用 `_HTMLTextExtractor`），按 spine 建阅读顺序，缺失时按文件名排序兜底。 |
| `:213-223` | `count_epub_chapters`：数 `<itemref>`（≈章数）。 |
| `:226-235` | `count_epub_images`：数被「纯文本 EPUB 解析器」丢弃的图像成员。 |

**降级结论**：EPUB 链 `ebooklib → 标准库 zipfile`（`utils.py:1479-1495`）。图像内容**一律不抽取**，仅计数并告警（`utils.py:64` `_EPUB_IMAGE_NOTICE_THRESHOLD=5`；`SKILL.md:268` 提示 `images_dropped > 5`）。

### 1.3 `book_to_skill/parsers/html.py`

| 行号 | 发现 |
|---|---|
| `:8-85` | `_HTMLTextExtractor`：标准库 `html.parser` 子类。`SKIP_TAGS={script,style,head}`；`BLOCK_TAGS`（`:18-24`）开/闭标签都发换行边界，注释 `:13-17` 说明「不处理闭合边界会使 `<h2>Chapter 1</h2>Intro` 拼成 `1I`，导致 `_EXPLICIT_CHAPTER` 因无词边界而失效」；`CELL_TAGS={td,th}`（`:29`）用 `\t` 而非 `\n` 分隔以保持表格行在同一行（便于把表格目录解析成单行标题）。`:81-85` 明确不二次 `unescape`，避免双编码实体塌缩。 |
| `:88-135` | `extract_html_content`：三级降级 `trafilatura`（真正做主内容/样板检测）→ `BeautifulSoup`（去 script/style/head）→ 标准库 `_HTMLTextExtractor`；每级都打印「Trying X ... OK / not available」，避免静默返回不同文档。 |

### 1.4 `book_to_skill/parsers/text.py`

| 行号 | 发现 |
|---|---|
| `:5-13` | `_BOMS`：BOM 表按长度降序，UTF-32 必须排在 UTF-16 之前。 |
| `:16-41` | `read_text_file`：有 BOM 按 BOM 声明的编码解码（失败即 `None`，**不接受 cp1252/latin-1 兜底**，注释 `:30-32` 说明「BOM 是显式编码声明，兜底会静默接受乱码」）；无 BOM 时链 `utf-8 → cp1252 → latin-1`。 |

### 1.5 `book_to_skill/sanitize.py`（Unicode 消毒规则，重点）

| 行号 | 发现 |
|---|---|
| `:6-10` | 定位：移除「用于隐藏文档内提示注入」的不可见码点。 |
| `:11-24` | 组 1 零宽/不可见间隔：`200B/200C/200D/2060/FEFF/00AD/034F/180E/2061/2062/2063/2064`。 |
| `:26-50` | 组 2 Bidi 控制符（**Trojan Source / CVE-2021-42574**）：`200E/200F/061C/202A-202E/2066-2069`。注释 `:33-36` 说明合法的阿拉伯文/希伯来文由 Unicode Bidi 算法自然右排，不受影响。 |
| `:55-60` | 组 3 不可见「字母」（Hangul Filler `115F/1160/3164/FFA0`）——不属于 Cf 分类，基于类别过滤会漏掉。 |
| `:66-76` | 组 4 注释/废弃格式控制符 `206A-206F/FFF9-FFFB`。 |
| `:78-110` | 组 5 `Default_Ignorable` 载体（蒙古文自由变体选择符、高棉元音、速记格式等），注释 `:86-98` 自承「静态清单是权衡，新版 UCD 可能新增」。 |
| `:112-118` | `_INVISIBLE_CODEPOINTS` = 上述各集合并集。 |
| `:120-123` | 组 6 Unicode Tag Block `E0000-E007F`（可把整段 ASCII 藏成不可见 tag）。 |
| `:125-138` | 组 7 变体选择符 `FE00-FE0F` + `E0100-E01EF`（组合符号，非 Cf，类别过滤会漏）。 |
| `:145` | 组 8 废弃格式范围 `206A-206F`。 |
| `:147-155` | 组 9 行间注释控制 / 乐谱格式 `1D173-1D17A`。 |
| `:158-178` | **康熙部首（U+2F00–U+2FDF）**：PDF 字体子集映射错误会把「判断力」抽成「判断⼒」。注释明确：「每个码点都有兼容分解，**NFKC 就是全部映射**」（`:164-166`）；但**折叠范围被刻意限定在该块**——`:168-171`「对全文做 NFKC 还会改写全角、连字、带圈数字、CJK 兼容表意文字：合法文本，sanitize.py 绝不能碰」；`:173-177` CJK Radicals Supplement（U+2E80–2EF3）**故意不折叠**，因为无分解、需人工表且部分是普通日文汉字。 |
| `:181-193` | `_kangxi_radical_fold()`：逐码点 `unicodedata.normalize("NFKC", radical)`，仅保留有变化的，`str.maketrans` 生成翻译表。 |
| `:196-204` | `fold_cjk_radicals`：单独暴露，注释 `:199-203` 说明「这是可读性修复而非安全剥离，不计入 `sanitize_extracted_text` 返回的删除数」。 |
| `:207-225` | `is_invisible_codepoint`：对外暴露，供生成物扫描器复用（见 `tools/scan_generated_skill.py:33`），保证「抽取器」与「扫描器」两套注入防御不漂移。 |
| `:228-248` | `sanitize_extracted_text`：`text.isascii()` 快路径；只对 `set(text)` 中的不同字符做替换（`:241`）；返回 `(cleaned, removed)`，`removed = len(text)-len(cleaned)`（折叠不改变长度，故只统计删除）。 |

**关键定性**：上游**不整篇 NFKC**；普通多语言文本逐字节保留（由 `tests/test_sanitize_extracted_text.py:33-40` 与 `tests/test_cjk_radical_normalization.py:59-75` 断言）。这与「NFKC 归一」的常见简化理解不同，详见 ADR-001「被推翻或需要修正的结论」。

### 1.6 `book_to_skill/utils.py`（核心：章节检测、结构、抽取流水线、幂等）

**确定性 token 估算**
- `:85-89` `_CJK_RE`（含补充平面 `\U00020000-\U0003FFFF`）。
- `:92-108` `estimate_tokens`：拉丁按 `words / WORDS_PER_TOKEN`，CJK 按 `cjk / CJK_CHARS_PER_TOKEN` 直接计字符；注释 `:99-100`「刻意无依赖，保证同一本书永远得同一数字」。常量在 `config.py:31-35`（0.75 / 1.5）。

**多语言章节标题检测（20+ 语言/文字）**
- `:117-120` `_EXPLICIT_CHAPTER`：`chapter|unit|lesson|module|lecture|part|chapitre|kapitel|cap[ií]tulo|capitolo|hoofdstuk|chương|ch.?`，编号限 1..99（丢弃 `2025.` 这类年份），支持罗马数字。
- `:125` `_HEADING_TAIL`：编号后必须是行尾/标点/首字母大写词；小写续写（`Chapter 6 explores...`）判为散文交叉引用。
- `:136-138` `_PERIOD_TAIL` / `_TAIL_WORD` / `_TITLE_TAIL_MAX_WORDS=8`：基于 Rust Book 实测（`:126-135`，13 个误判全为散文/代码）判「句点尾是散文还是标题」。
- `:149-151` `_ROMAN_HEAD` / `_LC_MD_ROMAN` / `_ROMAN_VALUES`：大写行首罗马数字安全，小写仅在 Markdown 标题内接受（避免 `vi: the editor` → 6）。
- `:156` `_MD_HEADING_PREFIX`：`## Chapter 1` / `== Section` 前缀剥离。
- `:167-172` `_CN_NUM_VALUES` / `_CN_NUM_UNITS` / `_CN_NUM_CLASS`（`〇零一二两三四五六七八九十百千`）。
- `:174-185` `_KANGXI_NUMERAL_TRANS`：**第二套**康熙数字映射（硬编码 `0x2F00→一 / 0x2F06→二 / 0x2F0B→八 / 0x2F17→十`）；`:177` 注释称「NFKC does not map these」——**经本次实测该说法不成立**（`python3` 验证 NFKC 把 `U+2F00` 映射为 `一`）。这是上游注释与事实的内部不一致，见 ADR-001。
- `:189-191` `_FW_DIGITS`（全角 `０-９`）、`_CN_CHAPTER`（`第X[章回卷节篇讲]`）、`_MD_CN_HEADING`（`## 一 · 缘起`）。
- `:193-463` 其余语言/文字章节正则：泰文(`:199`)、天城文/印地语(`:211`)、孟加拉(`:222`)、奥里亚(`:235`)、泰米尔(`:247`)、僧伽罗(`:270`)、泰卢固(`:282`)、卡纳达(`:293`)、马拉雅拉姆(`:306`)、古吉拉特(`:321`)、旁遮普/古尔穆奇(`:336`)、俄语 `глава`(`:347`)、希腊语 `κεφάλαιο`(`:356`)、希伯来语 `פרק`(`:368`)、亚美尼亚语(`:379`)、韩语(`:393`)、波斯/阿拉伯语（`:411-463`，含 `_FA_ORDINALS` 序数词表 `:428-456`）。合计 **20+ 语言/文字**，证实计划第 1 节。
- `:488-502` `_TOC_HEADERS`（EN/ES/PT/FR/DE/IT/NL）、`_TOC_CJK_PATTERN`（`目[ \t\u3000]*(录|錄|次)`）、`_TOC_PATTERN`。

**反误判与结构回退**
- `:508-545` 前置/后置 matter 白名单（`preface/foreword/.../index/glossary/notes/...`）、`appendix` 前缀、`_is_non_chapter_section`。
- `:552-560` `_ATX_HEADING` / `_SETEXT_UNDERLINE` / `_CODE_FENCE`。
- `:563-605` `_closed_fence_line_numbers`：跳过闭合代码围栏内的行。
- `:606-629` `_MIN_NUMBERED_TITLES=3` / `_MIN_NUMBERED_BODY_CHARS=200` / `_numbered_titles_are_structural`：数字开头的标题（「1. Introduction」也可能是列表项）用「章后正文中位数 ≥200 字符」判定，且**不要求编号连续/从 1 起**（`:613-619`）。
- `:632-725` `_structural_chapter_headings`：ATX/Setext 标题按深度分组，取「最浅且 ≥2 个不同标题」的层；跳过代码围栏；纯标点标题、裸数字开头标题被拦下；无层达 2 个时回退全收（仅当数字检测为 0 时触发，不会夸大真实书）。
- `:728-772` 中数/罗马数互转；`:774-789` `_is_prose_period_tail`；`:791-949` `_match_chapter_number`（`:803-805` 先做康熙数字 `translate`；`:807-820` 「至少两个空格」规则排除 `1. Item` 与 unified-diff `1  + use...` 行）；`:900` `_chapter_number`。
- `:950-1105` 标题文本、目录 leader、页内 chapter 头、outline 标题匹配、隔离标题行、章内容边界、`chapter_line_ranges`（`:1066`）。

**detect_structure / PDF outline 优先**
- `:1106-1195` `detect_structure`：全文扫描（非仅头部）、数**不同**章节号（ToC 条目与正文标题不重复计数）、跳过代码围栏、句点尾参照上一行判散文、返回 `{chapters_detected, chapters_method, chapter_headings_sample, has_toc}`。`chapters_method ∈ {numeric, structural, none}`；注释 `:1152-1157` 强调「哪条分支回答必须随计数一起上报，否则错误计数会悄悄变成 Step 3 的计划和章文件」。
- `:1198-1219` `apply_pdf_outline`：**「Prefer the PDF's embedded outline over the text heuristics」**；≥2 个非前后置 matter 标题时覆盖为 `chapters_method="outline"`，并附 `chapter_titles` / `chapter_range_end_titles`；文本启发式仅作无 outline 时的回退。调用点 `:1630-1631`（仅 PDF）。

**抽取流水线与幂等**
- `:1222-1258` `parse_arguments`；`:1260-1317` `resolve_input_files`。
- `:1319-1325` `_sha256_file`：流式（1 MiB 块），常量内存，适配多 GB 源文件。
- `:1328-1400` `reuse_is_safe`：**整运行级续跑**判据——`workdir` 存在、extraction_mode 未变、记录源与当前输入在「文件名 + sha256」上一一对应；注释 `:1334-1337` 说明 size 不参与（metadata 只记 2 位小数），指纹已涵盖。注意：这是**整运行复用**，不是按 stage 跳过。
- `:1403-1660` `extract_single_file`：
  - `:1413-1452` 后缀不支持时嗅探 magic bytes（`%PDF` / `PK` → epub 或 docx）。
  - `:1454` `prepare_dependencies`；`:1456-1460` MOBI/AZW 无 `ebook-convert` 直接报错。
  - `:1469-1504` EPUB 链 + `images_dropped`。
  - `:1505-1577` PDF 链：`:1507-1513` **`looks_image_only` 命中即 `raise ExtractionError`（"Run OCR on it first, then retry: ocrmypdf"）——扫描版是硬中止该源、无内置 OCR**；`:1514-1541` technical 先试 docling；`:1543-1573` 文本链 `pdftotext → pypdf → pdfminer`，全失败给出安装提示。
  - `:1578-1613` TEXT / HTML / DOCX / RTF / Calibre 分支。
  - `:1615-1626` `sanitize_extracted_text` 在**抽取之后、算指标之前**执行；`[security] removed N invisible Unicode code point(s)` 写 stderr；纯不可见内容直接 `ExtractionError("no visible content")`。
  - `:1628-1635` `estimate_tokens` → `detect_structure` → （PDF）`apply_pdf_outline` → 打印 `chapters: N (method)`。
  - `:1636-1660` metadata：`source_file / filename / format / extraction_method / fallback_reason / file_size_mb / sha256 / pages / chars / words / estimated_tokens / images_dropped / text / **structure`。
- `:1663-1687` `prepare_output_dir`；`:1689-1754` `write_pdf_page_sidecar`；`:1756-1803` intro/support/usage 打印；`:1804+` `main()`（批处理循环，按源捕获 `ExtractionError`，单源失败不拖垮整批——见 `:1415-1419` 注释）。

### 1.7 `book_to_skill/config.py` / `dependencies.py` / `cli.py`

| 文件:行号 | 发现 |
|---|---|
| `config.py:5-27` | `default_output_dir` 用 **PID 命名** `book_skill_work-<pid>`：注释 `:8-13` 说明原先所有运行共用固定路径，后完成的会静默覆盖先完成的 `full_text.txt`/`metadata.json`，Agent 可能「用错文档建技能」；`BOOK_SKILL_WORKDIR` 可覆盖。 |
| `config.py:31-35` | `WORDS_PER_TOKEN=0.75`、`CJK_CHARS_PER_TOKEN=1.5`（cl100k 近似）。 |
| `config.py:37-45` | 支持扩展名族：pdf / epub / docx / rtf / txt,text,md,markdown,rst,adoc,asciidoc / html,htm,xhtml / mobi,azw,azw3。 |
| `config.py:47-57` | `PYTHON_DEPENDENCIES`：`pdf-inspector / docling / pypdf / pdfminer.six / ebooklib / beautifulsoup4 / python-docx / striprtf / trafilatura`——**全部是本地解析/布局库，无任何 LLM SDK**。 |
| `dependencies.py:16-77` | `DEPENDENCY_GROUPS`：每种格式标注可选模块、系统命令、回退说明；`:71-76` MOBI/AZW 是唯一 `required=true`、无回退。 |
| `dependencies.py:118-134` | `install_python_packages`：`subprocess.run([sys.executable,"-m","pip","install",...])`，`timeout=600`。 |
| `dependencies.py:215-264` | `prepare_dependencies`：按格式触发「缺依赖时询问/安装/回退」。 |
| `dependencies.py:267-343` | `run_dependency_check`（`--check`）：逐格式打印状态，**始终返回 0**（`:271-272`「缺可选依赖不是错误，多数格式降级到回退」）；`:340-342`「missing Python packages are optional — most formats fall back to a stdlib parser」。 |
| `cli.py:8-9` | `sys.dont_write_bytecode=True`（避免部署的技能目录里留下 `__pycache__`）。 |
| `cli.py:17-30` | `main()`：强制 UTF-8 stdout/stderr；`install_pdf_inspector_hook()`（可选加速层，缺失时 no-op）→ `utils_main()` → `enrich_pdf_inspector_metadata()`。CLI 本身极薄。 |

### 1.8 `AGENTS.md` / `SKILL.md`

| 文件:行号 | 发现 |
|---|---|
| `AGENTS.md:7-12` | **两半架构的权威表述**：「1. a deterministic Python extractor (`scripts/extract.py` -> `book_to_skill/`), and 2. a spec-driven generator (`SKILL.md`) executed by an agent. Do not blur those responsibilities without a measured reason.」——智能在宿主 Agent 的推理里，不在 Python。 |
| `AGENTS.md:24-28` | `docs/research/progressive-disclosure-evals.md` 是研究计划的执行台账，定义任务顺序、证据门、哪些论文想法只是假设。 |
| `AGENTS.md:30-39` | 不可协商规则：`:32`「Measure, do not assert. No claimed quality, token, routing, accuracy, or cost improvement without reproducible evidence.」；`:33` 不得把论文假设变成生产行为；`:35` 绝不提交受版权原文；`:36` 评测工作避免新增运行时依赖；`:39` 不得为让实验通过而削弱安全检查/消毒/生成物扫描。 |
| `AGENTS.md:74-93` | 验证门：`pytest -q`、`ruff check .`、`python3 tools/validate_skill.py SKILL.md`；`:93`「跳过/失败/用未验证声明替代的门，任务不算 DONE」。 |
| `AGENTS.md:95-104` | 评测成本纪律：`:97`「Live model experiments are expensive and are never the first validation step」，单元/夹具测试优先，预算/条件/模型/语料预注册。 |
| `SKILL.md:1-4` | frontmatter 仅 `name` + `description`；无 `allowed-tools`（注释 `:16-19` 说明为保持宿主中立刻意省略）。 |
| `SKILL.md:23-39` | Philosophy：「Extract structure, not summaries」；把 Named frameworks / principles / techniques / anti-patterns / **Voice calibration** 列为「toolkit」——但全部是**散文概念**，无结构化字段（印证计划「Voice calibration 提出却无字段」）。 |
| `SKILL.md:43-65` | 4 种模式；`:54` Analyze Only「Stop — do NOT generate skill files」。 |
| `SKILL.md:88` | 生成物默认落到 `~/.agents/skills/`（跨宿主一份物理拷贝），Claude Code 需 Step 10 软链接。 |
| `SKILL.md:92-105` | Step 0：`:94` 无参数即停。 |
| `SKILL.md:118` | Step 1.5「Before extracting, ask the user」（强制停人 #1）。 |
| `SKILL.md:139-259` | Step 2：`:247` `--check` 预检；`:251` `metadata.json` 内容；`:257`「Always confirm the extraction is the document you asked for」。 |
| `SKILL.md:261-295` | Step 2.5 成本预估；`:294`「Wait for the user to confirm before proceeding」（强制停人 #2）；`:278` 与 `:292` 明确「价格/模型名常变，不硬编码美元数，若展示须标为估算并注明日期」。 |
| `SKILL.md:298-325` | Step 2.6 REPL 式切片：`:309-315` `grep -n -E "^\s*(Chapter|CHAPTER)\s+[0-9]+"` + `sed -n '<start>,<end>p'`；`:323`「200 页书 ≈75k token，每章重读一次 28 遍 ≈2M input token」。 |
| `SKILL.md:327-360` | Step 3 结构分析；`:337` Analyze Only 在此停。 |
| `SKILL.md:364` | Step 4「Before generating, ask the user」（强制停人 #3）。 |
| `SKILL.md:439-520` | Step 7 逐章生成；`:506`「Keep it faithful to the source; never copy long raw passages」。 |
| `SKILL.md:522-553` | Step 8 支撑文件；`:539` cheatsheet = 「the author's judgment: the decisions they'd make and why」。 |
| `SKILL.md:613` | 「Full text: `<output_text from metadata.json>` — grep it for depth ... (local extraction, not shipped)」——渐进式披露第三级。 |
| `SKILL.md:627-637` | Step 9.5 生成物安全扫描；`:636`「stop and ask a human to review」（强制停人 #4）。 |
| `SKILL.md:770-814` | Step 11 可选发布；`:778`「Visibility is a separate closed question — never inferred ... require a one-word reply」（强制停人 #5）；`:788` 仓库 README 需注明「content is synthesized summaries, not the book text」。 |
| `SKILL.md:871-881` | Quality Rules 8 条：`:873` #1「Extract structure, not summaries」；`:874` #2 保留作者精确命名（「The 5 Whys」≠「ask why multiple times」）；`:877` #5「Front-load SKILL.md — compaction keeps the first 5,000 tokens」；`:878` #6 章文件按需加载；`:879` #7「Never copy raw book text」；`:880` #8 Topic Index 是导航关键。 |

**强制停人计数**：Step 1.5(`:118`)、Step 2.5(`:294`)、Step 4(`:364`)、Step 9.5(`:636`)、Step 11 可见性(`:778`)，共 5 处；另有 Mode 2(`:54`)、Step 0(`:94`)、Step 3(`:337`) 等条件停止。证实计划第 1 节「5 处强制停人」。

### 1.9 `docs/research/progressive-disclosure-evals.md`（PD 系列与质量门，重点）

| 行号 | 发现 |
|---|---|
| `:3` | 状态「**ACTIVE PLAN — planning only; no paper-derived production change is authorized by this document**」。 |
| `:5` | 一手来源 He et al., *Is Progressive Disclosure All You Need for Long-Context Agents?*, arXiv:2607.17598。 |
| `:15` | 「discovery_tax.py ... 其文档正确说明 discovery-loop 数字是 **model**，不是真实 agent 轨迹的 measurement」。 |
| `:29-42` | 论文支持/不支持：`:36` 单层 flat 是研究中整体最佳默认；`:39` `KEY_ELEMENTS` 被使用但**未做独立消融**；`:40`「The paper does **not** validate the current `book-to-skill` semantic representation: frameworks, mental models, anti-patterns, decision rules, glossary/patterns/cheatsheet... were not the independent variable」；`:41` 不验证向代码/技术手册迁移；`:42` 成本结果（K=20 En.QA `68.3M` vs `32.5M`）是条件特定的未缓存测量，**不是通用 2× 声明**。 |
| `:44-48` | 「**Flat is the default to beat. Deeper routing is an experiment, not a forbidden architecture and not a production requirement.**」 |
| `:50-60` | 开放问题（假设）：`:54`「结构化表示是否比 `summary + key elements + raw chunk` 更利于 application/decision？」；`:59` 结构化章 + 源证据是否优于纯结构/纯原文。 |
| `:93-123` | 成本纪律：`:95-108` 每个 live-model 运行前必须有 config/manifest（源哈希、condition、问题集哈希、model/harness、generation model、prompt/config 哈希、seed/repetition、`max_calls` / `max_input_tokens` / `max_output_tokens` / 可选 `max_cost_usd`、reason 与能改变的决策）；`:110` runner 必须**停止**而非静默超预算。 |
| `:126-151` | 规划目录；`:150`「Evaluation code must not become a runtime dependency of `book-to-skill`」。 |
| `:154-195` | 核心指标：路由/导航、结果、效率、表示诊断（`:194`「Do not infer hidden reasoning from an answer string」）。 |
| `:198-223` | **任务台账**：PD-00/01/02/03 = `DONE`；**PD-04 ~ PD-12 全部 `BLOCKED`**（`:214-222`）。 |
| `:228-250` | PD-00：`:232`「Create a **zero-API** baseline snapshot」；`:250` 基线须清楚标注 modeled vs measured。 |
| `:313-337` | PD-03：`:328`「Generation of summary/KEY_ELEMENTS **may require a model in live mode**; tests must use fixed fixture outputs so CI remains offline/deterministic」；`:332`「Do not add this representation to production SKILL.md」。 |
| `:340-361` | PD-04 runner + 首个 live harness adapter；`:352`「`--dry-run` with planned conditions/calls/budgets and **no model calls**」（反证 live 模式会调用模型）。 |
| `:365-395` | **PD-05（最高优先级研究问题）**：「Once routing is held constant, does the current structured `book-to-skill` payload help an agent *apply* knowledge better than raw chapter text or a simple representation?」四条件 `RAW_CHUNK / SIMPLE / B2S_STRUCTURED / B2S_STRUCTURED_WITH_SOURCE_FALLBACK`（`:375-378`）；`:394`「No production claim from one dataset/cell ... A null result is a valid outcome」。 |
| `:519-541` | PD-12 是证据评审/生产决策门，非编码任务；`:539`「Make RAG superiority claims — **Never universal**」。 |
| `:545-563` | 证据台账：`:556` PD-05 = `BLOCKED`（注意：上游口径是 BLOCKED，非 UNVERIFIED）。 |
| `:567-579` | **Claims guardrail（不得当成既定事实发布）**：`:571` 论文验证了完整生成器；`:572` `KEY_ELEMENTS` 改善路由；`:573`「book-to-skill uses 2x fewer tokens」；`:574`「Skills beat RAG」；`:575`「Flat always beats hierarchy」；`:576` 结果适用于技术书/代码；`:577`「**Structured frameworks/mental models/anti-patterns are better than summaries.**（That is PD-05's question.）」 |
| `:597-611` | 完成定义：`:611`「成功标准不是所有特性都上线，而是能识别哪些想法值得其复杂度」。 |

### 1.10 `docs/performance.md` / `README.md` / `docs/faq.md`（数字与宣称）

| 文件:行号 | 发现 |
|---|---|
| `docs/performance.md:2` | description：「**Measured token cost of book-to-skill: 24x-51x fewer tokens** than dumping a book into context, the Discovery Loop Tax...」。 |
| `docs/performance.md:42-46` | 表：Think Python 2 `119,264 / 12,152 / ~5,000 / 24× / 2.4×`；Working Backwards `175,253 / 33,444 / ~5,000 / 35× / 6.7×`；AI Engineering `256,287 / 77,866 / ~5,000 / 51× / 15.6×`。 |
| `docs/performance.md:52-55` | `:52-53`「**context-dump advantage (24–51×)** is the strongest claim: that cost recurs on every conversation turn」；`:54-55`「**discovery-loop advantage (2.4–15.6×)** is a one-time cost and **a model** using the book's real ToC/chapter sizes」。 |
| `docs/performance.md:59-70` | 生成成本 ≈ `$1/book`（按 Claude Sonnet 4.5 `$3/$15 per MTok` 从实测 token **估算**）。 |
| `README.md:52-53` | 「Structure, not a summary」；「answers from the real content, **no hallucination**」。 |
| `README.md:65` / `:70` | 「it either hallucinates or says it doesn't have the content」；「**No hallucination.** No digging through PDFs」。 |
| `docs/faq.md:50-52` | 广泛已知书在 Claude 训练数据里「may hallucinate specific quotes or chapter locations」；而 book-to-skill「Every framework name, every anti-pattern list, every chapter number is **grounded in the text you provided**. No training data drift, no hallucinated chapter titles」。 |

**定性**：`24×–51×` 是上游基于实测 token 数的**自测/自报比值**；`2.4×–15.6×` 原文自述为**模型估算**；此外 `progressive-disclosure-evals.md:42/:573` 还单独点名论文的 `~2×`（K=20 En.QA）是条件特定、不可当通用结论。「no hallucination / grounded」在 README/faq 是**营销话术**，全仓无任何自动回验（见 §3）。

### 1.11 `tools/`（质量工具与评测工具）

| 文件:行号 | 发现 |
|---|---|
| `tools/validate_skill.py:1-32` | 多宿主 frontmatter 合规校验器（lens: claude/copilot/amp/hermes/openclaw/opencode）。注意：这是**上游自己的工具**，与计划第 7 节讨论的本机 `skill-creator/scripts/quick_validate.py` 不是同一个文件。 |
| `tools/validate_skill.py:49-135` | `CLAUDE_CODE_TOOLS`(`:49`)、`AMP_TOOLS`(`:60`)、`reserved_name_words={"anthropic","claude"}`(`:67`)、各 lens 的 `recognized_keys`（`:113-116` 含 `homepage/user-invocable/disable-model-invocation/...`）。 |
| `tools/validate_skill.py:213-291` | `audit()`：name 必填/≤64/正则/保留词；description 必填/≤1024（部分 lens 软限 60）；allowed-tools 与 body 内 bash 的一致性；未知顶层键 warn；body >500 行软 warn。**全是 frontmatter/宿主规则，无内容忠实度检查**。 |
| `tools/scan_generated_skill.py:2` | 「**Advisory** scan for prompt injection and unsafe authority in generated skills」。 |
| `tools/scan_generated_skill.py:23-33` | 文件数/字节上限；`:33` 复用 `sanitize.is_invisible_codepoint`——「两套注入防御不能漂移」（`:28-31` 记录过一次漂移事故）。 |
| `tools/scan_generated_skill.py:35-96` | `_CONTENT_RULES`：`prompt.ignore_previous / disregard_system / role_reassignment / fake_system_prefix / system_tag / chat_template_tag / tool_call_tag`；`:71-84` 强调只匹配带分隔符的 token 而非英文短语，否则每本讲 tool call 的书都会误报。 |
| `tools/scan_generated_skill.py:98-101` | `_EXFILTRATION_TERM` / `_OUTBOUND_TERM`（curl/wget/send/post/upload/transmit、http(s)://）。 |
| `tools/scan_generated_skill.py:280-302` | 检查 frontmatter 是否声明/扩大 `allowed-tools`、是否显式 `disable-model-invocation: false`。 |
| `tools/scan_generated_skill.py:316-363` | `main()`：findings → 退出码 1（advisory，`:350` 「Review ... before loading, installing, or publishing」、`:352-354`「规则刻意宽泛，可能匹配合法的 AI/LLM 文本」、`:355`「No files were modified」）；通过 → 0；扫描不完整 → 2。 |
| `tools/discovery_tax.py:3-28` | 「Discovery Loop Tax」：三策略（context-dump / discovery-loop / book-to-skill）的 token 成本；`:16-24` 诚实声明「token 数用 tiktoken 或 words/0.75 启发式，方法会打印」「**discovery-loop figure is a *model* with stated assumptions, not a measurement of a specific agent**」「给 best case 与 loop case 两种」。 |
| `tools/discovery_tax.py:53-56` | 直接复用 `utils._chapter_number` 与 `utils._TOC_PATTERN`，保证与抽取器对「章/目录」的定义一致。 |
| `tools/evals/score.py:2` | 「**Pure scoring and accounting for synthetic evaluation trajectories**」。 |
| `tools/evals/score.py:26-76` | `score_trajectory`：`:27`「without loading files or deriving missing observations」；从**预录** `observed.opens / answer_correct / route_correct / evidence_reached` 得出 `correct / wrong_routing / wrong_answer / irrelevant_opens_before_target / unknown`；`:55-64` 任一为 UNKNOWN 即整体 UNKNOWN；`:74-75` usage 只保留显式非负整数。 |
| `tools/evals/score.py:79-98` | `aggregate`：「never estimate missing usage」，只累加已记录的 token/call。 |
| `tools/evals/score.py:101-105` | `score`：按 question_id 排序，确定性输出。 |
| `tools/evals/replay.py:2` | 「Replay a versioned synthetic trajectory fixture deterministically」；`:12-13` schema 版本；`:31-34` `replay()` = 加载夹具 → `score()` → 附 schema/fixture 版本；`:16-17` canonical JSON（`sort_keys` + `allow_nan=False`）。 |
| `tools/evals/manifest.py:2` | 「deterministic, **secret-free** manifests for evaluation runs」。 |
| `tools/evals/manifest.py:18-32` | `SCHEMA_VERSION="pd-run-manifest/v1"`、`_REQUIRED`（condition / question_set_hash / **models** / **harness_id** / prompt_hashes / config_hashes / seed / repetition / budgets / artifacts / results / reason / decision）、`_SECRET_MARKERS`、密钥值正则（Bearer / sk- / ghp_ / AKIA / JWT / glpat-）。 |
| `tools/evals/manifest.py:122-174` | `build_manifest`：校验必填、拒绝密钥、源文件 sha256、`seed/repetition` 允许字面量 `"unsupported"`、budgets 硬上限、`:173` `run_id = sha256(canonical_json(identity))`、`:164` git commit（不可用时标 `"unavailable"` 并从 identity 移除）。`:158` 的 `harness_id` 是**通用「评测/代理运行器」标识符**，不是任何叫「Harness」的平台名。 |
| `tools/evals/paper_flat.py:2` | 「deterministic, **experiment-only PD-03 paper-flat** skill pack」。 |
| `tools/evals/paper_flat.py:14-16` | `_CHAPTER`：按章标题或开箱回退整篇一块。 |
| `tools/evals/paper_flat.py:53-91` | `build_paper_flat`：产出**单层** `SKILL.md`（含「Activation-time chunk table」：path / Description / **SUMMARY** / **KEY_ELEMENTS**）+ `chunks/chunk-NN.md` 原始载荷；`:84` 明确 split policy。注释 `:28-32` 把首个标题前的文本折进第一块，保证「读完全部块 = 读完全文」。 |

### 1.12 `tests/` 抽查（7 个，看它测了什么 / 没测什么）

| 测试文件:行号 | 测了什么 | 没测什么 |
|---|---|---|
| `tests/evals/test_score.py:20-59` | 合成轨迹的 5 类分类（正确/错路由/错答案/无关先开/unknown）、显式 unknown 不被推断、`aggregate` 只累加已记录 token/call。 | 生成内容是否忠于原书；groundedness；引文；幻觉；覆盖率。 |
| `tests/test_cjk_radical_normalization.py:31-97` | 康熙部首经 NFKC 折叠为表意字、折叠不改长度、不映射到另一个部首、与 Unicode 兼容分解一致；**整篇 NFKC 被明确禁止**（`:59-75` 参数化 ligature/带圈数字/全角/罗马数字必须逐字节保留）；折叠不计入 `removed`；部首不算不可见码点。 | 其它 Unicode 安全性（在专门测试里）、章节检测业务。 |
| `tests/test_pdf_outline_chapters.py:67-137` | 有 outline 时 `chapters_method=="outline"` 且标题/数量取自 outline；无 outline 回退 `numeric`；`chapter_ranges` 写入 metadata 且边界行正确。 | outline 与正文不一致时的冲突处理、无 pypdf 时（`pytest.importorskip` 直接跳过）。 |
| `tests/test_sanitize_extracted_text.py:24-97` | 零宽 + tag block 被删；普通多语言文本 `sanitized.encode()==original.encode()`；`extract_single_file` 在算指标**之前**消毒；纯不可见内容被拒；`main()` 只落消毒后文本且 metadata 的 chars 一致。 | 逐字引文回验；bidi 控制（在 `test_sanitize_bidi_controls.py`）；真实 PDF 字体子集。 |
| `tests/test_chapter_numeric_false_positives.py:40-158` | 折行散文、括号续写、unified-diff、代码围栏**不**被当成章；孤立 `Chapter 6.` 仍是标题；Markdown 标记标题的长尾被信任；真实数字书不受影响。 | 20+ 语言全量（分散在其它测试）、LLM 消歧、语义分段。 |
| `tests/evals/test_manifest.py:38-80` | 相同输入 → 相同 manifest/run_id；改 condition / 源字节 / commit 都会改 run_id；缺字段/负预算/`api_key`/Bearer/sk-/ghp_/AKIA/JWT/glpat- 一律清晰失败。 | 任何 live 模型运行；生成内容质量。 |
| `tests/test_validate_skill.py:17-60` | frontmatter 解析对 UTF-8 BOM 容错；hermes / openclaw lens 接受各自 frontmatter 且无 frontmatter warn。 | 正文五段式/Gotchas/触发词/描述质量（这些是本机 skill-creator 规范，不属上游工具）。 |

**总体**：上游测试面很宽（目录里 ~60 个测试文件，覆盖解析、章节检测、消毒、安全扫描、宿主兼容、幂等、评测夹具），但**全部是确定性/离线/单元测试**；`tests/evals/` 用固定夹具，`:PD-02` 明确「without spending model tokens」。**没有任何一个测试校验「生成的章节内容忠实于原书」**。

---

## 2. 五点专项核实结论（对应任务书第 2 节）

**① Python 代码里是否真的没有任何 LLM API 调用 → 是（生产代码），但需加限定语。**
- 全仓 `*.py` Grep：`openai|anthropic|api_key|chat.completions|requests.|httpx|urllib.request|genai|litellm|langchain|generate_content|messages.create` 的命中全部落在：注释里谈「文档内提示注入」、测试夹具、`manifest.py:24` 的**密钥拒绝守卫**、`validate_skill.py:67` 的保留词 `{anthropic, claude}`、`discovery_tax.py:20` 的「统计 *model*」。
- `book_to_skill/` 与 `tools/` 的 import 全为标准库 + 可选本地解析库（`pypdf/pdfminer/ebooklib/bs4/docx/trafilatura/striprtf/docling/pdf_inspector`）；`from urllib.parse import unquote, urlsplit`（`epub.py:9`）仅做 URL 路径解析，非网络；`http://schemas.openxmlformats.org/...`（`docx.py:11`）是 XML 命名空间字符串。
- `subprocess` 仅用于 `pdftotext` / `pdfinfo` / `ebook-convert` / `pip install` / `git rev-parse HEAD`。
- `AGENTS.md:7-12` 权威说明两半架构；`progressive-disclosure-evals.md:232` 「zero-API baseline」。
- **限定语**：评测规划允许 live 模型（`progressive-disclosure-evals.md:328`、`:352`、`:340-361` PD-04；`manifest.py:24` 有 `models` 字段；`AGENTS.md:97`）。故准确表述是「**当前已提交的生产抽取器与评测工具零 LLM；规划中的 live 评测在预算内用模型，仅评测、不进运行时**」。计划第 1 节的绝对表述对「现存代码」成立，建议按此精确化。

**② 章节检测算法的具体规则 → 证实且远比计划描述丰富。**
- 多语言：`utils.py:117-120`（10+ 欧洲/越南语章词 + unit/lesson/module/lecture/part/ch）、`:149-151` 罗马数字、`:190-191` 中文 `第X[章回卷节篇讲]` 与 Markdown 中文序数标题、`:193-463` 泰/印地/孟加拉/奥里亚/泰米尔/僧伽罗/泰卢固/卡纳达/马拉雅拉姆/古吉拉特/旁遮普/俄/希腊/希伯来/亚美尼亚/韩/波斯-阿拉伯——**20+ 语言/文字**确认。
- Kangxi 归一化：**两套并存**——`sanitize.py:181-204` 基于 NFKC 的 U+2F00–U+2FDF 折叠（作用于抽取文本），`utils.py:174-185`+`:805` 的硬编码 4 数字映射（作用于章节号解析）；`utils.py:177` 「NFKC does not map these」经实测为**不实注释**。
- PDF outline 优先：`utils.py:1198-1219` `apply_pdf_outline` 明确「Prefer the PDF's embedded outline over the text heuristics」，`chapters_method="outline"`；`parsers/pdf.py:187-242` 提供标题；`tests/test_pdf_outline_chapters.py:67-83` 断言 outline 胜过编号行、无 outline 才回退启发式。
- 反误判：`:125` 标题尾、`:136-138` 句点尾、`:807-820` 两空格规则与 diff 排除、`:563-605` 代码围栏跳过、`:606-629` 数字标题「正文中位数 ≥200」判据、`:632-725` 结构标题按深度分组、`detect_structure`(`:1106-1195`) 数不同编号并上报 method。

**③ sanitize 的 Unicode 规则 → 证实且成体系。**
- 9 组不可见/格式码点（见 §1.5）；核心是防「文档内提示注入」与 Trojan Source（`:27` CVE-2021-42574）。
- 康熙折叠**刻意限定在部首块**，明确拒绝整篇 NFKC（`:168-171`），普通文本逐字节保留（两个测试断言）。
- `is_invisible_codepoint` 被生成物扫描器复用（单点真源，`scan_generated_skill.py:33`）。
- 在抽取之后、指标之前执行（`utils.py:1615-1626`），返回删除计数，折叠不计入。

**④ 评测打分逻辑与是否校验「生成内容忠于原书」 → 不校验，无一例外。**
- `score.py` 只给**合成轨迹**做路由/答案分类与 usage 记账，且「不推断未观测状态」；`replay.py` 确定性重放夹具；`manifest.py` 做可复现清单与密钥守卫；`paper_flat.py` 造 PD-03 实验基线包；`discovery_tax.py` 自述为 *model*；`validate_skill.py` 是 frontmatter/宿主合规；`scan_generated_skill.py` 是 advisory 安全扫描。
- 全仓**无** groundedness / 逐字引文校验 / claim ledger / shingle 重叠 / 覆盖率 / 负例拒答的自动门。
- 「no hallucination」仅以营销话术存在于 `README.md:53/:70`、`docs/faq.md:50-52`，无任何代码支撑——这正是计划第 2 节缺口「无忠实度/覆盖率回验，'no hallucination' 无支撑」的本地铁证。

**⑤ 是否存在对「结构化框架优于摘要」的验证 → 不存在，且上游自己明确禁止当成事实。**
- `SKILL.md:25/:30/:873`、`README.md:52` 把「Extract structure, not summaries」作为**设计立场/散文**。
- `progressive-disclosure-evals.md:40` 论文未把当前语义表示（frameworks / mental models / anti-patterns / glossary / patterns / cheatsheet / 章模板）作为自变量；`:54` 把它列为开放问题；`:577` Claims guardrail 点名「Structured frameworks... are better than summaries」不可发布，「That is PD-05's question」；PD-05(`:365-395`) 是 BLOCKED 的最高优先级实验，`:394` 明言零结果也是有效结果。
- 结论：**零实验验证**，BookLeme 把它标 `UNVERIFIED` 是正确的。

---

## 3. 上游「没有」的东西（BookLeme 差异化的立足点）

1. 无 LLM 客户端 / prompt 版本化 / `model_fingerprint`（Python 侧）。
2. 无忠实度层：无 `claim_ledger`、无逐字引文校验、无 shingle 重叠、无覆盖率、无负例拒答、无 V1/V2/V3。
3. 无结构化插件字段：`state_machine` / `output_contract` / `hard_constraints` / `voice_calibration` / `falsification_condition` 全是散文概念（`SKILL.md:30-35`）。
4. 无 OCR：扫描版 PDF 直接 `ExtractionError` 中止（`utils.py:1507-1513`），只提示外部 `ocrmypdf`。
5. 无 `figure_text_lost` 级结构化标注：EPUB 图像只计数告警（`epub.py:226-235`、`utils.py:64`），PDF 表格仅 technical/docling 路径部分处理（`pdf.py:267-277`）。
6. 无按 stage 的幂等跳过：只有整运行级 `reuse_is_safe`（`utils.py:1328-1400`）。
7. 无「不停人」流水线：5 处强制停人是设计特性（`SKILL.md:118/294/364/636/778`）。
8. 无体裁路由 / 双引擎 / 行为状态机 / 会话状态（产物是固定 5 文件知识包）。
9. 无 CI 级回归基线比对（其 `evals/` 是实验夹具与清单，PD-04 起才规划 live runner）。

---

## 4. 术语与元数据核对（本地可证部分）

- **star 数**：本目录内无 star/fork 数据（GitHub 元数据不入库）。计划以 API 实时原值 **37,244 stars / 3,942 forks** 为准、WebSearch 的 `1.2k / 1.7k / 2.7w` 为过时摘要不采信——本地源码无从反证，按计划裁定采信。
- **Harness 术语**：本地出现的 `harness` 一律是通用名词——`manifest.py:158`/`:168` 的 `harness_id`（评测运行器标识）、`tests/evals/test_manifest.py:25` 的 `"fixture-harness"`、`progressive-disclosure-evals.md:37`（"depends on the harness"）、`:100`（model and harness）、`:348`（"Inspect available upstream tooling"）、`:356`（"adapter capability declaration"）。**没有任何「Harness 平台 / Skill 市场 / +2000 积分 / +100 积分 / Top 模型 Token 无限量 / 仅限机构投资者」字样**，本地证据支持计划第 1 节的术语澄清（载体是 AlphaEngine / AlphaClaw 的 Skill 市场，与「Harness Engineering」是另一套方法论）。
- **¥1,500/小时心理咨询**：全仓 Grep 无此字样，属用户定位概括/微信语境，不写入项目结论。

---

## 5. 声明

- 本文件是**研究对齐笔记**，不是设计文档、不是规范、不是实现。
- **未导入任何上游代码**：`bookleme/` 项目内没有任何来自 `_reference/book-to-skill/` 的 `.py` 复制、没有以其模板为唯一产物、没有把 `full_text.txt` / 书籍原文提交。
- 所有上游结论在 ADR-001 中与「三份独立报告 + GitHub API 复核」做四方收敛性比较后再决定是否采信；本文件只负责提供「本地源码审计」这一方的证据。
