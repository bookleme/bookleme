"""Genre plugin contract. Adding a new genre = adding one file that defines PLUGIN."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenrePlugin:
    genre_id: str
    display_name_zh: str
    version: str
    router_rules: dict
    capability_schema: dict
    section_template: str
    skill_template: str
    hard_constraints: list[str]
    state_machine: dict | None
    output_contract: dict
    anti_patterns: list[str]
    eval_prompts: list[dict]
    trigger_words: list[str]
    routing_rules: dict
    voice_calibration: dict
    copyright_profile: dict
    default_engines: list[str]
    engine_kind: str = "behavior"          # behavior | knowledge
    extra_sections: dict[str, str] = field(default_factory=dict)
    source_path: str = ""

    def render(self, ctx: dict[str, Any]) -> dict[str, str]:
        from ..render.skill import render_skill
        return render_skill(self, ctx)

    def validate(self) -> list[str]:
        from .validator import validate_plugin
        return validate_plugin(self)
