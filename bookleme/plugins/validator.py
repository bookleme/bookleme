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
            states = set(machine["states"])
            reachable = {machine.get("initial")}
            for tr in machine.get("transitions", []):
                if tr.get("from") in reachable:
                    reachable.add(tr.get("to"))
            if not set(machine.get("terminal", [])) & reachable:
                errors.append("state_machine 的 terminal 状态不可达")

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
