"""结论与证据的绑定：把「一条规则」拆成**来源事实 / 适用条件 / 生成的推论**。

为什么需要这个
--------------
BookLeme 原本把一条规则写成一个整体句子（`I_rephrase`），然后用一条引文
（`R_quote`）当它的证据。这在实践里会出问题：

> 「低精度只用于存储以省显存提速，计算前反量化回高精度执行」

这句**读起来像普遍规则**，但它其实是**微软特定方案**的概括——原文说的是
MAI 在 MAI Base 2 上选了 MXFP8 + 算时反量化，不是「所有低精度场景都该这样」。
引用能找到（引文逐字命中），但**引文不足以支撑整条结论**。

Codex 的评审把这个缺口讲得很准：
> 引用能找到，但不足以支持整条结论时，标记为「待核验」。

所以本模块把一条规则拆成三部分，**各自绑证据、各自判状态**：

| 部分 | 是什么 | 证据从哪来 |
|---|---|---|
| `fact`（来源事实） | 原文明确说了什么 | 必须有逐字引文支撑 |
| `condition`（适用条件） | 这条事实成立的上下文 | 原文里的限定语 |
| `inference`（生成的推论） | 我们从事实推出来的 | **是我们加的**，不是原文的 |

三部分分别判 `supported` / `partial` / `unverified`：

- `fact` 有逐字引文 → `supported`
- `condition` 原文有对应限定 → `supported`；原文没写 → `partial`（按 P0-2 降级）
- `inference` 由事实推出但原文没直说 → `partial`，**必须标注「这是推论」**
- 整条结论里没有任何部分被引文支撑 → `unverified`（待核验）

同时做 **P0-2：强结论检测与降级**。

强结论词（原文没明确支持却写成绝对判断的表述）：
「必须」「只能」「一律」「总是」「不适用」「收益不成立」「不可能」「不会」…

处理原则（Codex 原话）：
> 支持不足时改成「该案例主要讨论……，其他场景需要另行验证」。

注意：**这不是把好规则改弱**。原文真的写了「必须」时，强结论**保留**并标
`strong_claim_supported`；原文没写却出现强结论 → 降级 + 标 `downgraded`。
"""
from __future__ import annotations

import re

#: 强结论标记词 —— 出现在规则/边界里说明这是绝对判断
STRONG_CLAIM_MARKERS = (
    "必须", "只能", "一律", "总是", "不适用", "收益不成立", "不可能", "不会",
    "绝对", "永远", "任何情况下", "无一例外", "根本不", "绝不",
)

#: 英文强结论标记词
STRONG_CLAIM_MARKERS_EN = (
    "must ", "only ", "always ", "never ", "cannot ", "impossible", "never ",
    "not applicable", "guaranteed", "under no circumstances",
)

#: 降级改写模板（Codex 评审原文口径）
DOWNGRADE_CLAUSE = "该案例主要讨论此场景，其他场景需要另行验证"
DOWNGRADE_CLAUSE_EN = "this case mainly covers this scenario; other scenarios need separate verification"

#: 推论标记 —— 提醒读者这部分是我们推的，不是原文写的
INFERENCE_MARKER = "（推论：原文未直说，由上述事实推出）"
INFERENCE_MARKER_EN = "(inference: not stated directly in the source; derived from the facts above)"

#: 状态取值
STATUS_SUPPORTED = "supported"      # 有逐字引文支撑
STATUS_PARTIAL = "partial"          # 部分支撑 / 属推论
STATUS_UNVERIFIED = "unverified"    # 待核验：无任何引文支撑
STATUS_DOWNGRADED = "downgraded"    # 强结论被降级


def find_strong_claims(text: str) -> list[str]:
    """找出文本里的强结论标记词。返回命中的词列表（去重、保序）。"""
    if not text:
        return []
    hits: list[str] = []
    low = text.lower()
    for marker in STRONG_CLAIM_MARKERS:
        if marker in text and marker not in hits:
            hits.append(marker)
    for marker in STRONG_CLAIM_MARKERS_EN:
        if marker in low:
            shown = marker.strip()
            if shown not in hits:
                hits.append(shown)
    return hits


def has_strong_claim(text: str) -> bool:
    return bool(find_strong_claims(text))


def downgrade_boundary(text: str) -> tuple[str, bool]:
    """把「绝对边界」降级为「案例边界 + 需另行验证」。

    返回 (降级后的文本, 是否发生了降级)。

    降级规则（保守，不丢信息）：
    - 文本里已有「该案例主要讨论」这类限定 → 不动
    - 否则在句末追加降级限定，并把「不适用」改写为「不直接适用」
    """
    if not text:
        return text, False
    if DOWNGRADE_CLAUSE in text or "另行验证" in text:
        return text, False
    if not has_strong_claim(text):
        return text, False
    out = text
    # 「不适用」是评审点名的最强断言之一 → 改成「不直接适用」。
    # 要覆盖各种句式：独立出现、「不适用于…」、「本章不适用」、「都不适用」…
    # 用正则统一处理，避免漏掉某种搭配（实测漏了「本章不适用」）。
    out = re.sub(r"(?<!不直接)不适用", "不直接适用", out)
    out = out.replace("不直接直接适用", "不直接适用")   # 防重复替换
    out = out.replace("收益不成立", "该收益未经验证")
    sep = "" if out.endswith(("。", "；", "！", "?", ".")) else "。"
    out = f"{out}{sep}{DOWNGRADE_CLAUSE}。"
    return out, True


def split_rule_parts(rephrase: str, boundary: str, author_case: str,
                     quote: str) -> dict:
    """把一条规则拆成 fact / condition / inference 三部分并各自判状态。

    判据（确定性、可测，不依赖模型）：
    - `fact`：**有逐字引文**（quote 非空）→ supported；否则 unverified
    - `condition`：边界里有强结论 → 若原文有对应限定语则 supported，否则 partial
      （原文没写适用条件时不能声称「不适用」）
    - `inference`：规则正文里带推论性连接词（所以/因此/从而/意味着/可以据此）
      → partial（必须标注推论）；否则 supported（复述原文事实）

    为什么要这样判：原文的**适用条件**往往藏在上下文里而不在这张卡上。
    卡上没有条件 ≠ 原文没条件。所以 condition 判 partial 而非 unverified，
    并在渲染时提示「该边界是产物侧的保守表述，需回原文核对」。
    """
    quote_ok = bool(quote and quote.strip())
    strong_in_boundary = find_strong_claims(boundary or "")
    strong_in_rule = find_strong_claims(rephrase or "")

    # 条件：有强结论时，若规则里同时出现限定语（「若/当/仅/只/在…时/适用于」）
    # 说明作者确实把条件写进去了 → supported；否则 partial
    condition_signals = ("若", "当", "仅", "只", "在", "适用于", "对于", "前提",
                         "if ", "when ", "only ", "for ")
    has_condition_signal = any(sig in (rephrase or "") for sig in condition_signals)
    if strong_in_boundary:
        # 原文没明确支持这个绝对边界 → 降级（P0-2）
        # 「原文支持」的判据：规则里同时有条件信号（说明作者把条件写进去了），
        # 且引文里也出现了对应的强结论（说明不是我们凭空加的）。
        quote_has_strong = has_strong_claim(quote or "")
        if has_condition_signal and quote_has_strong:
            condition_status = STATUS_SUPPORTED
        else:
            condition_status = STATUS_DOWNGRADED
    else:
        condition_status = STATUS_SUPPORTED

    # 推论判定：`I_rephrase` 恒为**产物侧的重写**，不是原文复制。
    #
    # 判据不能只看因果连接词——实测全部卡的 I_rephrase 与 R_quote 的最长共同
    # 连续片段只有 2–4 字（如「按「存储精度」与「计算精度」分离设计…」），
    # 说明它们是重写而非复述。但重写有两种：
    #   a) 忠实转述原文事实（supported）——内容都在引文覆盖范围内
    #   b) 加了原文没有的概括/推论（partial，必须标注）
    # 区分办法：看规则里有没有**引文覆盖不到的内容特征**——
    # 因果连接词（所以/因此…）是典型；但中文规则常省略连接词，
    # 所以还要看「指令性/判断性」表述（「要」「应该」「必须」「只需」…），
    # 这类是我们加的执行指引，原文不一定这么写。
    #
    # 保守取向：判不准时标 partial（提示读者这是推论）——宁可多提示，
    # 不可让读者把我们的概括当成原文原话。
    inference_signals = ("所以", "因此", "从而", "意味着", "可以据此", "应当",
                         "换句话说", "也就是说", "要分别", "须分别", "先分清",
                         "只需", "应该", "不妨", "务必", "切勿", "别只",
                         "so ", "therefore", "thus ", "which means", "hence",
                         "should ", "must ", "first check")
    normative_signals = ("要", "须", "应该", "先", "再", "别", "切勿", "务必")
    inference_strength = "none"
    strong_aligned = False
    is_inference = any(sig in (rephrase or "") for sig in inference_signals)
    if is_inference:
        inference_strength = "medium"
    if not is_inference:
        # **引文与规则都有强结论** → 是复述，不是推论。
        # 背景：原文真的写了「must / 必须」时，规则里跟着写不算我们加的。
        # 不要求词形相同（引文英文 must、规则中文「必须」也算一致）——
        # 只看「两边是不是都在下强判断」。
        # 命中这条时**直接结束判定**（不再走后面的指令性/长度判据）：
        # 否则「必须」会被指令性词表再判一次，把结论翻回去。
        rule_strong = find_strong_claims(rephrase or "")
        quote_strong = find_strong_claims(quote or "")
        if rule_strong and quote_strong:
            is_inference = False
            inference_strength = "none"
            # **定案**：引文与规则都在下强判断 → 是复述。
            # 必须短路后面的判据，否则「必须」会被指令性词表与长度比再翻回去。
            strong_aligned = True
    if not is_inference and not strong_aligned:
        # 无连接词时：规则若含指令性措辞而引文没有，同样算推论。
        # 注意要排除已被上面「强结论一致」覆盖的情况（那里已 return 不了，
        # 故这里靠 is_inference 标志短路）。
        rule_norm = sum(1 for sig in normative_signals if sig in (rephrase or ""))
        quote_norm = sum(1 for sig in normative_signals if sig in (quote or ""))
        # 强结论词本身（必须/只能/一律…）不算「我们加的指令性措辞」——
        # 那是原文的强判断，由上面的强结论一致性判据管。
        rule_norm -= len([s for s in rule_strong
                          if s in normative_signals])
        quote_norm -= len([s for s in quote_strong
                           if s in normative_signals])
        is_inference = rule_norm > quote_norm
        if is_inference:
            # 指令性措辞是我们加的执行指引 → 至少 medium
            inference_strength = "medium"
    if not is_inference and not strong_aligned:
        # **引文明显短于规则** 也是推论信号（关键判据）。
        # 理由：引文只能覆盖它自己的长度。规则比引文长出一截，说明多出来的
        # 内容是产物侧扩写的——原文没写，我们写了。
        # 实测被判 supported 的三张卡都是这种情况：
        #   引文「we selectively use MXFP8 for MoE weights and KV caches」（55 字）
        #   规则「按「存储精度」与「计算精度」分离设计：低精度只用于存储…」（77 字）
        # 扩写的「存储/计算分离」「在既定边界应用更新」原文都没直说。
        # 阈值取 1.1：规则只要比引文长 10% 以上就可能含扩写内容。
        # 判不准时标 partial 是**保守取向**——宁可多提示「这是推论」，
        # 不可让读者把我们的概括当成原文原话。
        q_len = len(quote.strip())
        r_len = len((rephrase or "").strip())
        if q_len and r_len > q_len * 1.1:
            is_inference = True
            # 超出多少 → 决定推论强度（全部 partial 会失去区分度）
            excess = r_len / q_len
            if excess >= 1.6:
                inference_strength = "high"
            elif excess >= 1.3:
                inference_strength = "medium"
            else:
                inference_strength = "low"

    return {
        "fact": {
            "text": quote.strip() if quote_ok else "",
            "status": STATUS_SUPPORTED if quote_ok else STATUS_UNVERIFIED,
            "note": "逐字引文，可回原文逐字核对" if quote_ok else "无可逐字核对的引文",
        },
        "condition": {
            "text": (boundary or "").strip(),
            "status": condition_status,
            "strong_claims": strong_in_boundary,
            "note": ("原文限定语已写入" if condition_status == STATUS_SUPPORTED
                     else "产物侧的保守表述；原文的条件可能写在上下文里，需回原文核对"),
        },
        "inference": {
            "text": (rephrase or "").strip(),
            "status": STATUS_PARTIAL if is_inference else STATUS_SUPPORTED,
            "is_inference": is_inference,
            "strength": inference_strength,
            "marker": INFERENCE_MARKER if is_inference else "",
            "note": ("由上述事实推出，原文未直说"
                     + (f"（超出引文 {inference_strength}）"
                        if inference_strength != "none" else "")
                     if is_inference else "复述原文事实"),
        },
        "strong_claims_in_rule": strong_in_rule,
        "overall": (STATUS_UNVERIFIED if not quote_ok else
                    (STATUS_PARTIAL if (is_inference or
                                        condition_status == STATUS_PARTIAL)
                     else STATUS_SUPPORTED)),
    }


def annotate_capability(ria: dict) -> dict:
    """给一张能力卡加证据绑定信息（就地返回新 dict，不改原对象）。

    产出挂在 `ria["evidence_binding_detail"]`，供渲染层与 `check` 使用。
    """
    parts = split_rule_parts(
        ria.get("I_rephrase", ""),
        ria.get("B_not_applicable", ""),
        ria.get("A1_author_case", ""),
        ria.get("R_quote", ""),
    )
    downgraded_boundary, changed = downgrade_boundary(ria.get("B_not_applicable", ""))
    if changed:
        parts["condition"]["text"] = downgraded_boundary
        parts["condition"]["status"] = STATUS_DOWNGRADED
        parts["condition"]["note"] = ("原文未明确支持该绝对边界，已降级为"
                                       "「案例主要讨论此场景，其他场景需另行验证」")
        parts["condition"]["downgraded_from"] = ria.get("B_not_applicable", "")
    parts["downgraded"] = changed
    return parts


def render_evidence_block(detail: dict) -> str:
    """把证据绑定渲染成产物里的 Markdown 块（读者能直接看到可信程度）。"""
    if not detail:
        return ""
    labels = {
        STATUS_SUPPORTED: "有引文支撑",
        STATUS_PARTIAL: "部分支撑 / 属推论",
        STATUS_UNVERIFIED: "待核验（无引文支撑）",
        STATUS_DOWNGRADED: "已降级（原文未明确支持该绝对表述）",
    }
    lines = ["", "### 结论与证据的绑定", "",
             "| 部分 | 内容 | 证据状态 |", "| --- | --- | --- |"]
    for key, name in (("fact", "来源事实"), ("condition", "适用条件"),
                      ("inference", "生成的推论")):
        part = detail.get(key) or {}
        text = (part.get("text") or "").replace("|", "\\|")
        if len(text) > 160:
            text = text[:157] + "…"
        marker = part.get("marker") or ""
        if marker:
            text = f"{text} {marker}"
        status = part.get("status", "")
        lines.append(f"| {name} | {text} | {labels.get(status, status)} |")
    notes = []
    for key, name in (("fact", "来源事实"), ("condition", "适用条件"),
                      ("inference", "生成的推论")):
        part = detail.get(key) or {}
        if part.get("note"):
            notes.append(f"- **{name}**：{part['note']}")
    if notes:
        lines += ["", *notes]
    return "\n".join(lines) + "\n"
