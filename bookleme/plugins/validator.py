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


def _code_only(src: str) -> str:
    """把注释与文档字符串挖空，只留可执行代码。

    为什么：作者在注释里写「不要用 eval / 绝不 requests.get」也会被扫出来——
    那不是风险，是说明书。早先版本因此对自家内置插件误报。
    """
    import ast
    import io
    import tokenize

    lines = src.splitlines(keepends=True)
    spans: list[tuple[int, int, int, int]] = []
    # 1) 文档字符串（模块/类/函数体的第一个字符串常量）
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not body:
                continue
            head = body[0]
            if (isinstance(head, ast.Expr) and isinstance(head.value, ast.Constant)
                    and isinstance(head.value.value, str)):
                spans.append((head.value.lineno, head.value.col_offset,
                              head.value.end_lineno, head.value.end_col_offset))
    except (SyntaxError, ValueError):
        pass
    # 2) 注释
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                spans.append((tok.start[0], tok.start[1], tok.end[0], tok.end[1]))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    out = list(lines)
    for ln0, c0, ln1, c1 in spans:
        for ln in range(ln0, min(ln1, len(out)) + 1):
            if ln - 1 >= len(out):
                break
            line = out[ln - 1]
            a = c0 if ln == ln0 else 0
            b = c1 if ln == ln1 else len(line)
            out[ln - 1] = line[:a] + (" " * max(0, b - a)) + line[b:]
    return "".join(out)


def _scan_unsafe(path: str) -> list[str]:
    """扫描插件源码里的可执行危险形状（只扫代码，不扫注释与文档字符串）。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
    except OSError:
        return []
    try:
        code = _code_only(src)
    except Exception:
        code = src
    hits = _UNSAFE.findall(code)
    # URL 出现在字符串里是合法的（文档、示例链接）
    return [h for h in hits if not h.lower().startswith(("http://", "https://"))]


def _field(plugin, name: str, kind, errors: list[str], default):
    """取字段并做类型闸门：类型不对 → 记一条错误并返回安全默认值（不抛裸异常）。"""
    value = getattr(plugin, name, None)
    if value is None:
        errors.append(f"{name} 不能为 None")
        return default
    if kind is dict and not isinstance(value, dict):
        errors.append(f"{name} 必须是 dict")
        return default
    if kind is list and not isinstance(value, list):
        errors.append(f"{name} 必须是 list")
        return default
    if kind is str and not isinstance(value, str):
        errors.append(f"{name} 必须是字符串")
        return default
    return value


def validate_plugin(plugin, path: str | None = None) -> list[str]:
    errors: list[str] = []
    for name in REQUIRED_FIELDS:
        if not hasattr(plugin, name):
            errors.append(f"缺少必填字段 {name}")

    gid = getattr(plugin, "genre_id", "") or ""
    # 插件 id 必须与 configs/router.json 的体裁键一致（下划线命名）；
    # 生成的 SKILL.md frontmatter `name` 才要求严格 hyphen-case，由渲染层保证。
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", gid):
        errors.append(f"genre_id 不合规: {gid!r}（须 ^[a-z0-9][a-z0-9_-]*$）")
    if path and path.rsplit("/", 1)[-1] != f"{gid}.py":
        errors.append(f"插件文件名应为 {gid}.py，实际 {path}")

    words = _field(plugin, "trigger_words", list, errors, [])
    if not (3 <= len(words) <= 5) or not _all_chinese(words):
        errors.append(f"trigger_words 必须是 3-5 个中文词，实际 {words!r}")

    hard = _field(plugin, "hard_constraints", list, errors, [])
    if len(hard) < 4:
        errors.append("hard_constraints 至少 4 条")
    anti = _field(plugin, "anti_patterns", list, errors, [])
    if len(anti) < 1:
        errors.append("anti_patterns 至少 1 条")

    prompts = _field(plugin, "eval_prompts", list, errors, [])
    if not any(isinstance(p, dict) and p.get("type") == "negative" for p in prompts):
        errors.append("eval_prompts 必须含至少 1 个 type=negative 的负例")

    routing = _field(plugin, "routing_rules", dict, errors, {})
    if routing.get("insufficient_data_policy") != "ask":
        errors.append("routing_rules.insufficient_data_policy 必须为 'ask'（数据不足先追问）")
    if routing.get("unknown_intent_policy") not in ("ask", "decline"):
        errors.append("routing_rules.unknown_intent_policy 必须为 ask 或 decline")

    voice = _field(plugin, "voice_calibration", dict, errors, {})
    for key in ("tone", "address_form", "forbidden_phrases", "verdict_ownership"):
        if key not in voice:
            errors.append(f"voice_calibration 缺少 {key}")

    cp = _field(plugin, "copyright_profile", dict, errors, {})
    if cp.get("quote_char_limit", 999) > 150:
        errors.append("copyright_profile.quote_char_limit 必须 <= 150")
    if cp.get("allow_original_text") is not False:
        errors.append("copyright_profile.allow_original_text 必须为 false")

    engines = set(_field(plugin, "default_engines", list, errors, []))
    if not engines or not engines.issubset(_ENGINES):
        errors.append(f"default_engines 必须是 {sorted(_ENGINES)} 的非空子集")

    contract = _field(plugin, "output_contract", dict, errors, {})
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
        blocked = _scan_unsafe(source)
        if blocked:
            errors.append(f"安全扫描命中可疑动态执行/外传模式: {sorted(set(blocked))[:5]}")

    return errors
