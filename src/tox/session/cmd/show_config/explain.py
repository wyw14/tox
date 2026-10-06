"""Render read-only explanations of configuration values for ``tox config --explain``."""

from __future__ import annotations

import json
from collections.abc import Mapping
from textwrap import indent
from typing import TYPE_CHECKING

from tox.config.explain import explain_key

from .common import write_output

if TYPE_CHECKING:
    from tox.session.state import State
    from tox.util.json_types import JsonValue


def build_explanations(state: State) -> tuple[dict[str, JsonValue], bool]:
    keys: list[str] = state.conf.options.explain_keys
    show_unmatched: bool = state.conf.options.show_unmatched
    result: dict[str, JsonValue] = {}
    has_error = False

    envs: dict[str, JsonValue] = {}
    for name in state.envs.iter(package=True):
        tox_env = state.envs[name]
        per_env: dict[str, JsonValue] = {}
        for key in keys:
            explanation = explain_key(state.conf, tox_env.conf, key, show_unmatched=show_unmatched)
            per_env[key] = explanation
            has_error = has_error or explanation.get("error") is not None
        envs[tox_env.conf.name] = per_env
    result["env"] = envs

    if state.conf.options.env.is_all or state.conf.options.show_core:
        core: dict[str, JsonValue] = {}
        for key in keys:
            explanation = explain_key(state.conf, state.conf.core, key, show_unmatched=show_unmatched)
            core[key] = explanation
            has_error = has_error or explanation.get("error") is not None
        result["tox"] = core

    return result, has_error


def show_config_explain_json(state: State) -> int:
    result, has_error = build_explanations(state)
    output = json.dumps(result, indent=2)
    write_output(output, state.conf.options.output_file, is_colored=False, colorize=lambda text: text)
    return -1 if has_error else 0


def show_config_explain(state: State) -> int:
    result, has_error = build_explanations(state)
    blocks: list[str] = []
    for name, per_env in result.get("env", {}).items():  # type: ignore[union-attr]
        if isinstance(per_env, Mapping):
            for key, explanation in per_env.items():
                if isinstance(explanation, Mapping):
                    blocks.append(_render_explanation(f"[testenv:{name}] {key}", explanation))
    core = result.get("tox")
    if isinstance(core, Mapping):
        for key, explanation in core.items():
            if isinstance(explanation, Mapping):
                blocks.append(_render_explanation(f"[tox] {key}", explanation))
    output = "\n\n".join(blocks)
    write_output(output, state.conf.options.output_file, is_colored=False, colorize=lambda text: text)
    return -1 if has_error else 0


def _render_explanation(header: str, explanation: Mapping[str, JsonValue]) -> str:
    lines = [header, "definitions:"]
    definitions = explanation.get("definitions")
    if isinstance(definitions, list):
        for entry in definitions:
            if not isinstance(entry, Mapping):
                continue
            lines.extend(_render_definition(entry))
        unmatched_count = int(explanation.get("unmatched_count", 0) or 0)
        unmatched = explanation.get("unmatched")
        if isinstance(unmatched, list) and unmatched:
            lines.append("  unmatched conditions:")
            for part in unmatched:
                if isinstance(part, Mapping):
                    lines.append(f"    - {_render_part(part)}")
        elif unmatched_count:
            lines.append(f"  {unmatched_count} unmatched condition(s) hidden (use --show-unmatched)")

    references = explanation.get("references")
    if isinstance(references, list) and references:
        lines.append("reference chain:")
        for event in references:
            if isinstance(event, Mapping):
                lines.extend(_render_reference(event))

    lines.append("result:")
    if explanation.get("error") is not None:
        lines.append("  <unavailable: the value failed to resolve>")
        lines.extend(_render_error(explanation["error"]))
    else:
        rendered = json.dumps(explanation.get("value"), indent=2)
        lines.append(indent(rendered, prefix="  "))
    return "\n".join(lines)


def _render_definition(entry: Mapping[str, JsonValue]) -> list[str]:
    mark = "x" if entry.get("selected") else " "
    source = entry.get("source", "?")
    file_name = entry.get("file")
    location = f"{source} in {file_name}" if isinstance(file_name, str) else str(source)
    lines = [f"  [{mark}] {location}"]
    for part in entry.get("selected_parts", []):  # type: ignore[arg-type]
        if isinstance(part, Mapping):
            lines.append(f"      + {_render_part(part)}")
    raw = entry.get("raw")
    if isinstance(raw, str) and raw and entry.get("kind") in {"override", "constant"}:
        lines.append(indent(raw, prefix="      = "))
    return lines


def _render_part(part: Mapping[str, JsonValue]) -> str:
    prefix = part.get("prefix")
    content = part.get("content", "")
    text = f"{prefix}: {content}" if isinstance(prefix, str) else str(content)
    if part.get("secret"):
        text = f"{text} (secret, provided, content hidden)"
    return text


def _render_reference(event: Mapping[str, JsonValue]) -> list[str]:
    depth = int(event.get("depth", 0) or 0)
    prefix = "  " + "    " * depth
    kind = str(event.get("kind", "ref"))
    head = f"{prefix}- {event.get('expression', '?')} ({kind})"
    target = event.get("target")
    if isinstance(target, str):
        head += f" -> {target}"
    lines = [head]

    detail = prefix + "    "
    if event.get("error") is not None:
        lines.append(f"{detail}error: {event['error']}")
        chain = event.get("chain")
        if isinstance(chain, list) and chain:
            lines.append(f"{detail}chain: {' -> '.join(str(item) for item in chain)}")
        return lines

    if kind == "env":
        if event.get("secret"):
            if event.get("provided") is True:
                source = f"provided by {target}" if isinstance(target, str) else "provided"
                lines.append(f"{detail}{source} (secret, content hidden)")
            elif event.get("provided") is False:
                lines.append(f"{detail}not provided (secret, content hidden)")
            else:
                lines.append(f"{detail}resolved from set_env when used (secret, content hidden)")
        elif event.get("provided") is True:
            source = f"provided by {target}" if isinstance(target, str) else "provided"
            lines.append(f"{detail}{source}")
        elif event.get("provided") is False:
            lines.append(f"{detail}not provided")
    if event.get("missing") and kind != "env":
        lines.append(f"{detail}missing reference")

    default = event.get("default")
    if isinstance(default, str) and default:
        lines.append(f"{detail}default: {default}")
    resolved = event.get("resolved")
    if isinstance(resolved, str) and resolved and not event.get("secret"):
        lines.append(f"{detail}resolved: {resolved}")
    return lines


def _render_error(error: object) -> list[str]:
    if not isinstance(error, Mapping):
        return []
    lines = ["error:"]
    lines.append(f"  {error.get('error', '')}")
    cause = error.get("cause")
    if isinstance(cause, str):
        lines.append(f"  cause: {cause}")
    chain = error.get("chain")
    if isinstance(chain, list) and chain:
        lines.append("  chain:")
        for item in chain:
            lines.append(f"    {item}")
    return lines


__all__ = [
    "build_explanations",
    "show_config_explain",
    "show_config_explain_json",
]
