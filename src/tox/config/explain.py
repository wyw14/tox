"""Read-only explanation of how a single configuration value is derived.

The explanation never materializes environments or mutates configuration: it re-runs value resolution for the
requested key with a :class:`~tox.config.trace.ConfigTrace` attached, and reports:

* the candidate **definitions** (environment section, shared base section, default or override) with the one selected
  marked, including which conditional (factor) lines were selected and which were not;
* the **reference chain** used while substituting the value (environment variables, other config keys, ...);
* the **final value** tox uses;
* the original error together with the active chain for circular or missing references.

Secret-looking environment variables are reported by name and presence only; their content is never recorded.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

from tox.config.loader.api import ConfigLoadArgs
from tox.config.loader.native import to_native
from tox.config.of_type import ConfigConstantDefinition, ConfigDynamicDefinition
from tox.config.set_env import SetEnv
from tox.config.trace import ConfigTrace, TraceEvent
from tox.util.redact import is_secret_name

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from tox.config.loader.api import Loader
    from tox.config.main import Config
    from tox.config.sets import ConfigSet
    from tox.util.json_types import JsonValue

_SET_ENV_KEYS = {"set_env", "setenv"}
_SECRET_LINE = re.compile(r"(^|:\s+)([A-Za-z_][\w]*)\s*=.*$")


def explain_key(
    conf: Config,
    conf_set: ConfigSet,
    key: str,
    *,
    show_unmatched: bool = False,
) -> dict[str, JsonValue]:
    """Explain how ``key`` resolves inside the configuration set ``conf_set``.

    :param conf: the global tox configuration
    :param conf_set: the core or per-environment configuration set the key belongs to
    :param key: the configuration key to explain (an alias is accepted)
    :param show_unmatched: include factor conditions that did not match

    :returns: a JSON-serializable explanation with ``definitions``, ``references``, ``unmatched``, ``value`` and
        ``error`` entries

    """
    scope = "tox" if conf_set.env_name is None else conf_set.env_name
    if key not in conf_set:
        return _unknown(scope, key)

    primary = conf_set.primary_key(key)
    definition = conf_set._defined[primary]  # ruff:ignore[private-member-access] - read-only report, same package
    trace = ConfigTrace()

    if isinstance(definition, ConfigConstantDefinition):
        definitions: list[dict[str, JsonValue]] = [{"kind": "constant", "source": "constant", "selected": True}]
    else:
        definitions, supplier, supplier_alias = _section_definitions(
            conf, conf_set, definition, primary, tuple(str(k) for k in definition.keys)
        )

    args = ConfigLoadArgs([], conf_set.name, conf_set.env_name, trace)
    value: Any = None
    error: dict[str, JsonValue] | None = None
    try:
        # call the definition directly (instead of ConfigSet.load) to bypass the value cache and capture a fresh trace
        value = definition(conf, conf_set.loaders, args)
    except Exception as exception:  # keep the original error (and its cause) plus the active chain
        error = {
            "type": type(exception).__name__,
            "error": repr(exception),
            "cause": repr(exception.__cause__) if exception.__cause__ is not None else None,
            "chain": trace.failure_chain(),
        }

    native: JsonValue = None if error is not None else _to_native(value, primary, conf_set, trace)
    if error is None:
        # a secret used through substitution must not surface inside the final value either
        secrets = _provided_secret_values(conf, conf_set.env_name, trace)
        if secrets:
            native = _mask_secrets(native, secrets)

    matched_conditions: list[dict[str, JsonValue]] = []
    unmatched: list[dict[str, JsonValue]] = []
    for event in trace.events:
        if event.kind != "if":
            continue
        part = {"prefix": f"if {event.condition}" if event.condition is not None else "if", "content": event.expression}
        if event.matched:
            matched_conditions.append(part)
        else:
            unmatched.append(part)
    if matched_conditions and definitions:
        selected = next((entry for entry in definitions if entry.get("selected")), None)
        if selected is not None and isinstance(selected.get("selected_parts"), list):
            selected["selected_parts"] = [*selected["selected_parts"], *matched_conditions]  # type: ignore[list-item]

    if isinstance(definition, ConfigDynamicDefinition):
        default_selected = not any(bool(entry.get("selected")) for entry in definitions)
        definitions.append(
            {
                "kind": "default",
                "source": "default value",
                "selected": default_selected,
                "raw": _stringify_default(value) if default_selected and error is None else None,
            }
        )

    if not isinstance(definition, ConfigConstantDefinition):
        unmatched.extend(_section_unmatched(definitions))

    return {
        "scope": scope,
        "key": primary,
        "definitions": definitions,
        "references": [_event_dict(event) for event in trace.events if event.kind != "if"],
        "unmatched": unmatched if show_unmatched else [],
        "unmatched_count": len(unmatched),
        "value": native,
        "error": error,
    }


def _unknown(scope: str, key: str) -> dict[str, JsonValue]:
    return {
        "scope": scope,
        "key": key,
        "definitions": [],
        "references": [],
        "unmatched": [],
        "unmatched_count": 0,
        "value": None,
        "error": {"type": "KeyError", "error": f"unknown configuration key {key!r}", "cause": None, "chain": []},
    }


def _section_definitions(
    conf: Config,
    conf_set: ConfigSet,
    definition: ConfigDynamicDefinition[Any],
    primary: str,
    aliases: Sequence[str],
) -> tuple[list[dict[str, JsonValue]], Loader[Any] | None, str | None]:
    loaders: list[Loader[Any]] = []
    seen_ids: set[int] = set()
    for loader in conf_set.loaders:  # env-specific section first, shared base sections (its parents) next
        if id(loader) in seen_ids:
            continue
        seen_ids.add(id(loader))
        loaders.append(loader)
    supplier: Loader[Any] | None = None
    supplier_alias: str | None = None

    candidates: list[tuple[Loader[Any], str | None, list[Any]]] = []
    for loader in loaders:
        raw_alias: str | None = None
        for alias in aliases:
            try:
                loader.load_raw(alias, conf, conf_set.env_name)
            except KeyError:
                continue
            raw_alias = alias
            break
        overrides = [entry for alias in aliases for entry in loader.overrides.get(alias, [])]
        if supplier is None and (raw_alias is not None or overrides):
            supplier = loader
            supplier_alias = raw_alias
        candidates.append((loader, raw_alias, overrides))

    definitions: list[dict[str, JsonValue]] = []
    for loader, raw_alias, overrides in candidates:
        selected = loader is supplier
        entry: dict[str, JsonValue] = {
            "kind": "section",
            "source": f"[{loader.section.key}]",
            "file": conf.src_path.name,
            "selected": selected,
            "raw": None,
            "selected_parts": [],
            "unmatched_parts": [],
        }
        if selected and raw_alias is not None:
            explain_raw = getattr(loader, "explain_raw", None)
            if callable(explain_raw):
                details = explain_raw(raw_alias, conf, conf_set.env_name)
                entry["raw"] = _redact_set_env_text(str(details.get("raw", "")), primary)
                entry["selected_parts"] = _redact_parts(list(details.get("selected_parts", [])), primary)
                entry["unmatched_parts"] = _redact_parts(list(details.get("unmatched_parts", [])), primary)
        definitions.append(entry)
        for override in overrides:
            definitions.append(
                {
                    "kind": "override",
                    "source": "command line override",
                    "selected": selected,
                    "raw": _redact_override(str(override), primary, aliases),
                    "selected_parts": [],
                    "unmatched_parts": [],
                }
            )
    return definitions, supplier, supplier_alias


def _section_unmatched(definitions: Sequence[dict[str, JsonValue]]) -> list[dict[str, JsonValue]]:
    for entry in definitions:
        if entry.get("selected") and isinstance(entry.get("unmatched_parts"), list):
            return [
                {"prefix": part.get("prefix"), "content": part.get("content")}
                for part in entry["unmatched_parts"]  # type: ignore[union-attr]
            ]
    return []


def _redact_parts(parts: list[dict[str, object]], primary: str) -> list[dict[str, JsonValue]]:
    result: list[dict[str, JsonValue]] = []
    for part in parts:
        item: dict[str, JsonValue] = {"prefix": part.get("prefix"), "content": part.get("content")}  # type: ignore[dict-item]
        if primary in _SET_ENV_KEYS and isinstance(item["content"], str):
            name, sep, _rest = item["content"].partition("=")
            if sep and is_secret_name(name.strip()):
                item["content"] = name.strip()
                item["secret"] = True
                item["provided"] = True
        result.append(item)
    return result


def _redact_set_env_text(text: str, primary: str) -> str:
    if primary not in _SET_ENV_KEYS:
        return text
    return "\n".join(
        _SECRET_LINE.sub(lambda m: f"{m.group(1) or ''}{m.group(2)}=<provided>", line) for line in text.split("\n")
    )


def _redact_override(text: str, primary: str, aliases: Sequence[str]) -> str:
    if primary not in _SET_ENV_KEYS:
        return text
    # overrides targeting a secret set_env variable look like ``namespace.set_env.TOKEN=value`` or ``TOKEN=value``
    for alias in aliases:
        prefix = f"{alias}."
        if prefix in text:
            name = text.split(prefix, 1)[1].split("=", 1)[0]
            if is_secret_name(name):
                head, _sep, _value = text.partition("=")
                return f"{head}=<provided>"
    return text


def _stringify_default(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, str):
        return value
    from tox.config.loader.stringify import stringify  # ruff:ignore[import-outside-top-level]

    return stringify(value)[0]


def _provided_secret_values(conf: Config, env_name: str | None, trace: ConfigTrace) -> dict[str, str]:
    """Collect the actual values of secret variables used by the explained value, for output masking only."""
    secrets: dict[str, str] = {}
    for event in trace.events:
        if event.kind != "env" or not event.secret or not event.provided or not event.name:
            continue
        name = event.name
        if name in secrets:
            continue
        if event.target == "os.environ":
            secrets[name] = os.environ.get(name, "")
        elif env_name is not None:
            try:
                set_env = conf.get_env(env_name)["set_env"]
                secrets[name] = set_env.load(name, ConfigLoadArgs([], "set_env", env_name))
            except Exception:  # pragma: no cover - masking must never break the explanation
                continue
    return secrets


def _mask_secrets(value: JsonValue, secrets: Mapping[str, str]) -> JsonValue:
    if isinstance(value, str):
        for name, secret in secrets.items():
            if secret and secret in value:
                value = value.replace(secret, f"<secret:{name}>")
        return value
    if isinstance(value, list):
        return [_mask_secrets(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _mask_secrets(item, secrets) for key, item in value.items()}
    return value


def _to_native(value: Any, primary: str, conf_set: ConfigSet, trace: ConfigTrace | None = None) -> JsonValue:
    if isinstance(value, SetEnv):
        result: dict[str, JsonValue] = {}
        for name in sorted(value):
            if is_secret_name(name):
                # only report the name and that it is provided, never the content
                result[name] = {"secret": True, "provided": True}
            else:
                args = ConfigLoadArgs([], conf_set.name, conf_set.env_name, trace)
                result[name] = to_native(value.load(name, args))
        return result
    return to_native(value)


def _event_dict(event: TraceEvent) -> dict[str, JsonValue]:
    return {
        "expression": event.expression,
        "kind": event.kind,
        "depth": event.depth,
        "name": event.name,
        "target": event.target,
        "resolved": event.resolved,
        "secret": event.secret,
        "provided": event.provided,
        "missing": event.missing,
        "default": event.default,
        "error": event.error,
        "chain": event.chain,
    }


__all__ = ("explain_key",)
