"""忠实度 judge：groundedness（多角色投票）+ V2 预测力 + V3 独特性。

口径来源 `docs/FIDELITY.md` §7：

| 校验 | 分类 | 本模块实现 |
| --- | --- | --- |
| V1 跨域佐证（≥2 个不同 segment 的佐证） | measured | 确定性 shingle 计数，见 `v1_cross_domain()` |
| V2 预测力（fresh-context judge 回答书里没明说的新问题） | heuristic | **独立一次调用，只给框架卡、不给原文上下文** |
| V3 独特性（denylist 过滤 + judge 打分） | heuristic | 确定性 denylist 前置过滤 + judge 判定 |
| groundedness（多 judge 多数投票） | heuristic | 若干不同角色的 judge 投票 |

诚实约定：

1. 未配置 LLM → 不发起任何调用，指标值保持 `null`（绝不用启发式假装有 judge 结果）；
2. judge 结论依赖模型主观判断，`metric_type` 恒为 `heuristic`——分类依据是「是否依赖
   主观判断」，与是否已接入无关；
3. `model_fingerprint = sha256(model + prompt_version)` 必须与数值一同出现，换模型/换
   prompt 即漂移；
4. 投票失败（网络/解析错误）不计入票数；全部失败时判定为 `None`（未知），**不得记为
   `False`**——「没判出来」和「判为不成立」是两件事。
"""

from __future__ import annotations

import re
from pathlib import Path

from .overlap import shingle_set

DENYLIST_PATH = Path(__file__).with_name("common_sense_denylist.txt")

#: judge 角色：不同视角的独立判断，比同角色多次采样更接近「多 judge」
PERSONAS: tuple[tuple[str, str], ...] = (
    ("考据员", "你只认字面证据：引文与上下文里没有写明的要素，一律判为不支持。"),
    ("事实核查员", "你逐条核对断言中的每个要素是否都能在引文与上下文里找到出处。"),
    ("逆向怀疑者", "你默认怀疑该断言是编的，先去找证据推翻它，找不到才判支持。"),
)


def load_denylist(path: Path | None = None) -> list[str]:
    """加载常识短语表（V3 前置过滤，确定性部分）。"""
    p = Path(path) if path else DENYLIST_PATH
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def common_sense_hits(text: str, denylist: list[str]) -> list[str]:
    """文本命中的常识短语（确定性；V3 的前置淘汰条件）。"""
    return [d for d in denylist if d and d in text]


def v1_cross_domain(caps: dict, segments: dict, *, n: int = 13,
                    min_hits: int | None = None) -> dict[str, list[str]]:
    """V1 跨域佐证（measured）：同一断言在其他 segment 是否也有近似表述。

    确定性计数：引文的 shingle 有多少落在别的 segment 文本里。

    引文常常短于 13 字（能力卡的 R_quote 允许 8-24 字），此时固定用 13 字 shingle
    会让短引文永远命中不到（shingle 比引文还长 → 集合为空）。因此 shingle 长度取
    `min(n, len(quote))`，命中门槛取「引文 shingle 的一半（至少 1 个）」——短引文
    要求原文里出现同一句表述，长引文要求约一半内容重复，都属「同一断言在别处也
    出现过」的合理判据。返回 {capability_id: [segment_id...]}。
    """
    seg_texts = [(seg.get("segment_id", ""), seg.get("text") or "")
                 for seg in segments.get("segments", [])]
    cache: dict[int, list[tuple[str, set[str]]]] = {}
    out: dict[str, list[str]] = {}
    for cap in caps.get("capabilities", []):
        quote = (cap.get("ria") or {}).get("R_quote", "")
        own = cap.get("span", {}).get("segment_id", "")
        hits: list[str] = []
        if quote:
            sn = min(n, len(quote))
            if sn >= 4:
                if sn not in cache:
                    cache[sn] = [(sid, shingle_set(text, sn)) for sid, text in seg_texts]
                qs = shingle_set(quote, sn)
                need = min_hits if min_hits is not None else max(1, len(qs) // 2)
                for sid, ss in cache[sn]:
                    if sid == own or not ss:
                        continue
                    if len(qs & ss) >= need:
                        hits.append(sid)
        out[cap.get("capability_id", "")] = hits
    return out


def _context(full_text: str, quote: str, radius: int, anchor: int | None = None) -> str:
    """取引文附近的原文作为 judge 的判据上下文。

    优先用能力卡自带的权威锚点（读图卡来自 figures.json）；否则退回 find。
    find 返回的是引文**第一次出现**的位置——引文在目录/正文重复时会取错段，
    judge 就会拿目录页当判据。
    """
    pos = -1
    if isinstance(anchor, int) and anchor >= 0 \
            and full_text[anchor:anchor + len(quote)] == quote:
        pos = anchor
    else:
        pos = full_text.find(quote)
    if pos < 0:
        return ""
    lo = max(0, pos - radius)
    hi = min(len(full_text), pos + len(quote) + radius)
    return full_text[lo:hi]


def _majority(values: list[bool]) -> bool | None:
    """多数票；**平票返回 None（未知）**——平票与全失败一样是「没判出来」。

    不能把平票记成 False：3 票里 1 票因网络失败、剩 2 票各执一词（三个 persona
    本就刻意对立，平票很常见）——若记成 False，unsupported_claim_rate 会直接变成
    1.0，凭空宣称「这本书的方法论全是编的」。
    """
    if not values:
        return None
    yes = sum(1 for v in values if v)
    if yes * 2 == len(values):
        return None          # 平票 = 未决
    return yes * 2 > len(values)


def _default_call(prompt_name: str, values: dict) -> dict:
    """默认调用实现：加载版本化 prompt、渲染占位符、调用 chat_json。

    占位符**一次性**替换（正则回调）：先逐个 replace 再清理剩余占位符的做法会二次
    替换——原文里出现 `${context}` 这类字面量时，会被后续轮次当成真占位符替换掉
    （书稿里出现 `${...}` 很常见：Markdown 模板、代码示例、LaTeX、shell 变量）。
    """
    from ..llm import chat_json, load_prompt, split_prompt
    text = load_prompt(prompt_name)
    sys_part, user_part = split_prompt(text)

    def render(t: str) -> str:
        return re.sub(r"\$\{(\w+)\}",
                      lambda m: "" if values.get(m.group(1)) is None
                      else str(values[m.group(1)]),
                      t)

    return chat_json(render(user_part), system=render(sys_part))


def judge_capabilities(caps: dict, full_text: str, config: dict, *, votes: int = 3,
                       call=None, context_radius: int = 600) -> dict:
    """对每张能力卡跑 judge，产出 groundedness / V2 / V3 判定。

    `call(prompt_name, values) -> dict` 为可注入的调用接口（测试用假实现）。
    返回 {enabled, model_fingerprint, prompt_version, votes, results, summary, errors}。
    """
    from ..llm import model_fingerprint

    call = call or _default_call
    jcfg = config.get("llm_judge") or {}
    denylist = load_denylist()
    # 有效票数 = 请求的票数与可用的 persona 数取小；报告里写**实际用了多少票**，
    # 不能写「5 票多数」而实际只有 3 个角色在投票。
    effective_votes = max(1, min(int(votes), len(PERSONAS)))
    results: dict[str, dict] = {}
    errors: list[str] = []
    for cap in caps.get("capabilities", []):
        cid = cap.get("capability_id", "")
        ria = cap.get("ria") or {}
        quote = ria.get("R_quote", "")
        ctx = _context(full_text, quote, context_radius,
                       (cap.get("span") or {}).get("char_start"))
        grounded_votes: list[bool] = []
        v3_votes: list[bool] = []
        supports: list[str] = []
        v3_reasons: list[str] = []
        for role, persona in PERSONAS[:effective_votes]:
            try:
                obj = call("judge_v1", {
                    "persona_role": f"你是{role}。{persona}",
                    "title": cap.get("title", ""),
                    "quote": quote,
                    "context": ctx,
                    "rephrase": ria.get("I_rephrase", ""),
                })
            except Exception as exc:  # 单票失败不中断流水线
                errors.append(f"{cid}/{role}: {type(exc).__name__}: {exc}")
                continue
            if isinstance(obj.get("grounded"), bool):
                grounded_votes.append(obj["grounded"])
            if isinstance(obj.get("v3_pass"), bool):
                v3_votes.append(obj["v3_pass"])
            if obj.get("support"):
                supports.append(str(obj["support"])[:200])
            if obj.get("v3_reason"):
                v3_reasons.append(str(obj["v3_reason"])[:200])
        v2: dict = {}
        if jcfg.get("v2", True):
            try:
                v2 = call("judge_v2_v1", {
                    "title": cap.get("title", ""),
                    "rephrase": ria.get("I_rephrase", ""),
                    "steps": " / ".join(str(s) for s in (ria.get("A3_steps") or [])),
                    "not_applicable": ria.get("B_not_applicable", ""),
                })
            except Exception as exc:
                errors.append(f"{cid}/v2: {type(exc).__name__}: {exc}")
                v2 = {}
        hits = common_sense_hits(ria.get("I_rephrase", ""), denylist)
        results[cid] = {
            "judged": bool(grounded_votes) or bool(v2) or bool(v3_votes),
            "grounded": _majority(grounded_votes),
            "grounded_votes": grounded_votes,
            "support": supports[0] if supports else "",
            "v2_pass": v2.get("v2_pass") if isinstance(v2.get("v2_pass"), bool) else None,
            "v2_question": str(v2.get("v2_question", ""))[:300],
            "v2_answer": str(v2.get("v2_answer", ""))[:300],
            "v3_pass": _majority(v3_votes),
            "v3_votes": v3_votes,
            "v3_reason": v3_reasons[0] if v3_reasons else "",
            "denylist_hits": hits,
        }
    judged = [r for r in results.values() if r["judged"]]
    error_types: dict[str, int] = {}
    for e in errors:
        name = e.split(":")[0].split("/")[-1].strip() or "unknown"
        error_types[name] = error_types.get(name, 0) + 1
    summary = {
        "capabilities": len(results),
        "judged": len(judged),
        "grounded": sum(1 for r in judged if r["grounded"] is True),
        "grounded_unknown": sum(1 for r in judged if r["grounded"] is None),
        "v2_pass": sum(1 for r in judged if r["v2_pass"] is True),
        "v2_unknown": sum(1 for r in judged if r["v2_pass"] is None),
        "v3_pass": sum(1 for r in judged if r["v3_pass"] is True),
        "v3_unknown": sum(1 for r in judged if r["v3_pass"] is None),
        "denylist_flagged": sum(1 for r in results.values() if r["denylist_hits"]),
        "failed_calls": len(errors),
        "error_types": error_types,
    }
    return {
        "enabled": True,
        # 指纹绑定**两个** prompt：judge_v1 与 judge_v2_v1 都要算进来，
        # 否则只换 V2 的 prompt 而指纹不变，指标会被误当成同一次实验。
        "model_fingerprint": model_fingerprint("judge_v1+judge_v2_v1"),
        "prompt_version": "judge_v1+judge_v2_v1",
        "votes": effective_votes,
        "votes_requested": int(votes),
        "results": results,
        "summary": summary,
        "errors": errors[:20],
        "errors_truncated": len(errors) > 20,
    }
