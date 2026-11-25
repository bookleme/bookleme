"""Hard checks for a genre plugin. A plugin that fails here cannot be loaded."""

from __future__ import annotations

import re
from string import Template

REQUIRED_FIELDS = [
    "genre_id", "display_name_zh", "version", "router_rules", "capability_schema",
    "section_template", "skill_template", "hard_constraints", "state_machine",
    "output_contract", "anti_patterns", "eval_prompts", "trigger_words",
    "routing_rules", "voice_calibration", "copyright_profile", "default_engines",
    "engine_kind",
]
_ENGINES = {"knowledge_pack", "behavior_skill"}
_UNSAFE = re.compile(
    r"(?:https?://|/Users/|/etc/|~/\.ssh|AKIA[0-9A-Z]{16}|"
    r"(?:api[_-]?key|password|secret)\s*=|eval\(|exec\(|base64\.b64decode|"
    r"socket\.|subprocess\.|urllib\.request|requests\.(?:get|post))",
    re.I,
)


def _all_chinese(words) -> bool:
    return all(isinstance(w, str) and re.fullmatch(r"[\u4e00-\u9fff]{2,12}", w) for w in words)


def _check_state_machine(machine: dict) -> list[str]:
    """状态机四项检查（PLUGIN_SPEC §2.1）：

    1. `initial` / `terminal` / `transition.from|to` 都必须是 `states[]` 里的合法状态；
    2. 所有**非终态**状态必须从 `initial` 可达（不可达 = 死状态，流程走不到）；
    3. `initial` 到某个 `terminal` 存在路径；
    4. 无孤立状态（既无入边也无出边 = 悬空状态）。
    """
    errors: list[str] = []
    states = set(machine.get("states") or [])
    transitions = machine.get("transitions") or []
    initial = machine.get("initial")
    terminal = set(machine.get("terminal") or [])
    if initial not in states:
        errors.append(f"state_machine.initial {initial!r} 不在 states 中")
    for st in sorted(terminal):
        if st not in states:
            errors.append(f"state_machine.terminal {st!r} 不在 states 中")
    edges: dict[str, set[str]] = {}
    targets: set[str] = set()
    for tr in transitions:
        frm, to = tr.get("from"), tr.get("to")
        if frm not in states:
            errors.append(f"transition.from {frm!r} 不在 states 中")
        if to not in states:
            errors.append(f"transition.to {to!r} 不在 states 中")
        edges.setdefault(frm, set()).add(to)
        targets.add(to)
    reachable: set[str] = set()
    if initial in states:
        stack = [initial]
        while stack:
            cur = stack.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            stack.extend(edges.get(cur, ()))
    for st in sorted(states - terminal):
        if st not in reachable:
            errors.append(f"状态 {st!r} 从 initial 不可达（死状态）")
    if not (terminal & reachable):
        errors.append("state_machine 的 terminal 状态不可达")
    for st in sorted(states):
        if st not in edges and st not in targets:
            errors.append(f"状态 {st!r} 是孤立状态（既无入边也无出边）")
    return errors


def validate_plugin(plugin, path: str | None = None) -> list[str]:
    errors: list[str] = []
    for name in REQUIRED_FIELDS:
        if not hasattr(plugin, name):
            errors.append(f"缺少必填字段 {name}")

    gid = getattr(plugin, "genre_id", "")
    # 插件 id 必须与 configs/router.json 的体裁键一致（下划线命名）；
    # 生成的 SKILL.md frontmatter `name` 才要求严格 hyphen-case，由渲染层保证。
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", gid):
        errors.append(f"genre_id 不合规: {gid!r}（须 ^[a-z0-9][a-z0-9_-]*$）")
    if path and path.rsplit("/", 1)[-1] != f"{gid}.py":
        errors.append(f"插件文件名应为 {gid}.py，实际 {path}")

    words = getattr(plugin, "trigger_words", [])
    if not (3 <= len(words) <= 5) or not _all_chinese(words):
        errors.append(f"trigger_words 必须是 3-5 个中文词，实际 {words!r}")

    if len(getattr(plugin, "hard_constraints", [])) < 4:
        errors.append("hard_constraints 至少 4 条")
    if len(getattr(plugin, "anti_patterns", [])) < 1:
        errors.append("anti_patterns 至少 1 条")

    prompts = getattr(plugin, "eval_prompts", [])
    if not any(p.get("type") == "negative" for p in prompts if isinstance(p, dict)):
        errors.append("eval_prompts 必须含至少 1 个 type=negative 的负例")

    routing = getattr(plugin, "routing_rules", {})
    if routing.get("insufficient_data_policy") != "ask":
        errors.append("routing_rules.insufficient_data_policy 必须为 'ask'（数据不足先追问）")
    if routing.get("unknown_intent_policy") not in ("ask", "decline"):
        errors.append("routing_rules.unknown_intent_policy 必须为 ask 或 decline")

    voice = getattr(plugin, "voice_calibration", {})
    for key in ("tone", "address_form", "forbidden_phrases", "verdict_ownership"):
        if key not in voice:
            errors.append(f"voice_calibration 缺少 {key}")

    cp = getattr(plugin, "copyright_profile", {})
    if cp.get("quote_char_limit", 999) > 150:
        errors.append("copyright_profile.quote_char_limit 必须 <= 150")
    if cp.get("allow_original_text") is not False:
        errors.append("copyright_profile.allow_original_text 必须为 false")

    engines = set(getattr(plugin, "default_engines", []))
    if not engines or not engines.issubset(_ENGINES):
        errors.append(f"default_engines 必须是 {sorted(_ENGINES)} 的非空子集")

    contract = getattr(plugin, "output_contract", {})
    for key in ("artifact", "sections", "required_fields"):
        if key not in contract:
            errors.append(f"output_contract 缺少 {key}")

    for name in ("section_template", "skill_template"):
        value = getattr(plugin, name, "")
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{name} 必须是非空字符串")
        else:
            try:
                Template(value)
            except (ValueError, KeyError) as exc:
                errors.append(f"{name} 模板不合法: {exc}")

    machine = getattr(plugin, "state_machine", None)
    if getattr(plugin, "engine_kind", "") == "behavior":
        if not isinstance(machine, dict) or not machine.get("states"):
            errors.append("behavior 插件必须有非空 state_machine.states")
        else:
            errors.extend(_check_state_machine(machine))

    if not isinstance(getattr(plugin, "capability_schema", {}), dict):
        errors.append("capability_schema 必须是 dict")
    if not isinstance(getattr(plugin, "router_rules", {}), dict):
        errors.append("router_rules 必须是 dict")

    source = getattr(plugin, "source_path", "") or path or ""
    if source:
        try:
            with open(source, "r", encoding="utf-8") as fh:
                head = fh.read()
            hits = _UNSAFE.findall(head)
            # URLs are legitimate in documentation strings; only executable shapes are blocked.
            blocked = [h for h in hits if not h.lower().startswith(("http://", "https://"))]
            if blocked:
                errors.append(f"安全扫描命中可疑动态执行/外传模式: {sorted(set(blocked))[:5]}")
        except OSError:
            pass

    return errors
