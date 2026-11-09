"""A small, dependency-free subset of JSON Schema validation.

Supports: type, required, properties, items, additionalProperties(schema),
enum, minimum/maximum, minItems/maxItems. The schema files themselves remain
standard draft-07 JSON Schema, so `jsonschema` can validate them when available.
"""

from __future__ import annotations

from typing import Any

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def validate(instance: Any, schema: dict, path: str = "$") -> list[str]:
    errors: list[str] = []
    expected = schema.get("type")
    if expected:
        alternatives = expected if isinstance(expected, list) else [expected]
        matched = False
        type_errors = []
        for one in alternatives:
            py = _TYPES.get(one)
            if py is None:
                type_errors.append(f"unsupported schema type {one!r}")
                continue
            if one == "integer" and isinstance(instance, bool):
                continue
            if one == "number" and isinstance(instance, bool):
                continue
            if isinstance(instance, py):
                matched = True
                break
        if not matched:
            errors.append(f"{path}: expected {expected}, got {type(instance).__name__}"
                          + (f" ({'; '.join(type_errors)})" if type_errors else ""))

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']!r}")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required key {key!r}")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in instance:
                errors.extend(validate(instance[key], sub, f"{path}.{key}"))
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            for key, value in instance.items():
                if key not in props:
                    errors.extend(validate(value, extra, f"{path}.{key}"))

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, value in enumerate(instance):
                errors.extend(validate(value, item_schema, f"{path}[{i}]"))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} above maximum {schema['maximum']}")

    return errors


def validate_file(instance: Any, schema_path) -> list[str]:
    from .config import load_json
    from pathlib import Path

    return validate(instance, load_json(Path(schema_path)))
