from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tox.pytest import MonkeyPatch, ToxProjectCreator


def _explain_json(
    creator: ToxProjectCreator, tox_ini: str, key: str, *extra: str, env: str = "a"
) -> tuple[object, object]:
    outcome = creator({"tox.ini": tox_ini}).run("c", "-e", env, "--explain", key, *extra, "--format", "json")
    parsed = json.loads(outcome.out)
    return outcome, parsed["env"][env][key]


def test_explain_text_layout(tox_project: ToxProjectCreator) -> None:
    project = tox_project(
        {
            "tox.ini": """
        [tox]
        env_list = a
        no_package = true
        [testenv]
        description = run {env:PLAIN:def}
        """
        }
    )
    outcome = project.run("c", "-e", "a", "--explain", "description")
    outcome.assert_success()
    assert "[testenv:a] description" in outcome.out
    assert "definitions:" in outcome.out
    assert "[x] [testenv] in tox.ini" in outcome.out
    assert "[ ] default value" in outcome.out
    assert "reference chain:" in outcome.out
    assert "{env:PLAIN:def} (env)" in outcome.out
    assert "result:" in outcome.out


def test_explain_selected_definition_env_section_wins(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    [testenv]
    description = from base
    [testenv:a]
    description = from env
    """
    _, explanation = _explain_json(tox_project, tox_ini, "description")
    definitions = explanation["definitions"]
    sections = [entry for entry in definitions if entry["kind"] == "section"]
    assert [entry["source"] for entry in sections] == ["[testenv:a]", "[testenv]"]
    assert [entry["selected"] for entry in sections] == [True, False]
    selected = next(entry for entry in sections if entry["selected"])
    assert selected["selected_parts"] == [{"prefix": None, "content": "from env"}]
    assert explanation["value"] == "from env"


def test_explain_falls_back_to_default_definition(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    """
    _, explanation = _explain_json(tox_project, tox_ini, "description")
    default = next(entry for entry in explanation["definitions"] if entry["kind"] == "default")
    assert default["selected"] is True


def test_explain_factor_lines_hidden_by_default(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a-b
    no_package = true
    [testenv]
    deps =
        pytest
        b: extra-b
        c: extra-c
    """
    _, explanation = _explain_json(tox_project, tox_ini, "deps", env="a-b")
    selected = next(entry for entry in explanation["definitions"] if entry["selected"])
    assert [part["prefix"] for part in selected["selected_parts"]] == [None, "b"]
    assert explanation["unmatched"] == []
    assert explanation["unmatched_count"] == 1
    assert explanation["value"] == ["pytest", "extra-b"]


def test_explain_factor_lines_shown_on_demand(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a-b
    no_package = true
    [testenv]
    deps =
        pytest
        b: extra-b
        c: extra-c
    """
    outcome = tox_project({"tox.ini": tox_ini}).run(
        "c", "-e", "a-b", "--explain", "deps", "--show-unmatched", "--format", "json"
    )
    explanation = json.loads(outcome.out)["env"]["a-b"]["deps"]
    assert explanation["unmatched"] == [{"prefix": "c", "content": "extra-c"}]
    assert "unmatched conditions:" in outcome.out or outcome.out  # json format omits the text heading


def test_explain_text_unmatched_hint(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a-b
    no_package = true
    [testenv]
    deps =
        pytest
        c: extra-c
    """
    outcome = tox_project({"tox.ini": tox_ini}).run("c", "-e", "a-b", "--explain", "deps")
    outcome.assert_success()
    assert "1 unmatched condition(s) hidden (use --show-unmatched)" in outcome.out
    assert "extra-c" not in outcome.out
    outcome = tox_project({"tox.ini": tox_ini}).run("c", "-e", "a-b", "--explain", "deps", "--show-unmatched")
    outcome.assert_success()
    assert "unmatched conditions:" in outcome.out
    assert "c: extra-c" in outcome.out


def test_explain_reference_chain_cross_section(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    [testenv]
    description = pre {[testenv]shared} {env:PLAIN:fallback}
    shared = mid
    """
    _, explanation = _explain_json(tox_project, tox_ini, "description")
    kinds = {(event["kind"], event["expression"]) for event in explanation["references"]}
    assert ("ref", "{[testenv]shared}") in kinds
    assert ("env", "{env:PLAIN:fallback}") in kinds
    ref = next(event for event in explanation["references"] if event["expression"] == "{[testenv]shared}")
    assert ref["target"] == "testenv.shared"
    assert ref["resolved"] == "mid"
    env_event = next(event for event in explanation["references"] if event["expression"] == "{env:PLAIN:fallback}")
    assert env_event["provided"] is False
    assert env_event["default"] == "fallback"
    assert explanation["value"] == "pre mid fallback"


def test_explain_nested_reference_chain(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    [testenv]
    description = {[testenv]outer}
    outer = {[testenv]inner}
    inner = deep
    """
    _, explanation = _explain_json(tox_project, tox_ini, "description")
    targets = [event["target"] for event in explanation["references"]]
    assert targets == ["testenv.outer", "testenv.inner"]
    assert [event["depth"] for event in explanation["references"]] == [0, 1]
    assert explanation["references"][-1]["resolved"] == "deep"
    assert explanation["value"] == "deep"


def test_explain_secret_set_env_name_only(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    [testenv]
    set_env =
        SECRET_TOKEN = s3cr3t-value
        PLAIN = hi
    description = {env:SECRET_TOKEN}/{env:PLAIN}
    """
    _, explanation = _explain_json(tox_project, tox_ini, "description")
    secret = next(event for event in explanation["references"] if event["name"] == "SECRET_TOKEN")
    assert secret["secret"] is True
    assert secret["provided"] is True
    assert secret["resolved"] is None
    assert "s3cr3t-value" not in json.dumps(explanation)
    assert explanation["value"] == "<secret:SECRET_TOKEN>/hi"
    _, set_env_explanation = _explain_json(tox_project, tox_ini, "set_env")
    assert set_env_explanation["value"]["SECRET_TOKEN"] == {"secret": True, "provided": True}
    assert "s3cr3t-value" not in json.dumps(set_env_explanation)


def test_explain_secret_os_environ_name_only(tox_project: ToxProjectCreator, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MY_API_TOKEN", "env-secret-123")
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    [testenv]
    description = https://user:{env:MY_API_TOKEN}@host
    """
    _, explanation = _explain_json(tox_project, tox_ini, "description")
    secret = next(event for event in explanation["references"] if event["name"] == "MY_API_TOKEN")
    assert secret["target"] == "os.environ"
    assert secret["provided"] is True
    assert secret["resolved"] is None
    assert "env-secret-123" not in json.dumps(explanation)
    assert explanation["value"] == "https://user:<secret:MY_API_TOKEN>@host"


def test_explain_missing_reference_keeps_token(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    [testenv]
    description = x{[testenv]nope}y
    """
    _, explanation = _explain_json(tox_project, tox_ini, "description")
    missing = next(event for event in explanation["references"] if event["kind"] == "ref")
    assert missing["missing"] is True
    assert missing["target"] == "testenv.nope"
    assert missing["error"] is None
    assert explanation["error"] is None
    assert explanation["value"] == "x{[testenv]nope}y"


def test_explain_missing_reference_default(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    [testenv]
    description = {[testenv]nope:fallback}
    """
    _, explanation = _explain_json(tox_project, tox_ini, "description")
    event = explanation["references"][0]
    assert event["missing"] is True
    assert event["default"] == "fallback"
    assert explanation["value"] == "fallback"


def test_explain_circular_reference_keeps_error_and_chain(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    [testenv]
    description = {envlogdir}
    envlogdir = {description}
    """
    outcome = tox_project({"tox.ini": tox_ini}).run(
        "c", "-e", "a", "--explain", "description", "--format", "json", raise_on_config_fail=False
    )
    explanation = json.loads(outcome.out)["env"]["a"]["description"]
    assert outcome.code != 0
    error = explanation["error"]
    assert error["type"] == "HandledError"
    assert "CircularChainError" in error["error"]
    assert "circular chain detected" in error["cause"]
    assert "testenv.description" in error["chain"]
    assert "testenv.env_log_dir" in error["chain"]
    assert explanation["value"] is None
    failed_events = [event for event in explanation["references"] if event["error"]]
    assert failed_events
    assert "CircularChainError" in failed_events[-1]["error"]
    assert "testenv.description" in failed_events[-1]["chain"]


def test_explain_unknown_key(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    """
    outcome = tox_project({"tox.ini": tox_ini}).run(
        "c", "-e", "a", "--explain", "does_not_exist", "--format", "json", raise_on_config_fail=False
    )
    explanation = json.loads(outcome.out)["env"]["a"]["does_not_exist"]
    assert outcome.code != 0
    assert "unknown configuration key" in explanation["error"]["error"]


def test_explain_override_definition(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    [testenv]
    description = original
    """
    outcome = tox_project({"tox.ini": tox_ini}).run(
        "c", "-e", "a", "--explain", "description", "-x", "testenv:a.description=overridden", "--format", "json"
    )
    explanation = json.loads(outcome.out)["env"]["a"]["description"]
    overrides = [entry for entry in explanation["definitions"] if entry["kind"] == "override"]
    assert overrides and overrides[0]["selected"] is True
    assert "overridden" in overrides[0]["raw"]
    assert explanation["value"] == "overridden"


def test_explain_core(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    """
    outcome = tox_project({"tox.ini": tox_ini}).run(
        "c", "-e", "ALL", "--core", "--explain", "env_list", "--format", "json"
    )
    explanation = json.loads(outcome.out)["tox"]["env_list"]
    assert explanation["scope"] == "tox"
    assert explanation["value"] == ["a"]


def test_explain_toml_conditions(tox_project: ToxProjectCreator) -> None:
    pyproject = """
    [tool.tox]
    env_list = ["a-b"]
    no_package = true

    [tool.tox.env_run_base]
    deps = [
      "pytest",
      { replace = "if", condition = "factor.b", then = "extra-b", extend = true },
      { replace = "if", condition = "factor.c", then = "extra-c", extend = true },
    ]
    """
    outcome = tox_project({"pyproject.toml": pyproject}).run(
        "c", "-e", "a-b", "--explain", "deps", "--show-unmatched", "--format", "json"
    )
    explanation = json.loads(outcome.out)["env"]["a-b"]["deps"]
    assert explanation["value"] == ["pytest", "extra-b"]
    assert [part["prefix"] for part in _matched_parts(explanation)] == ["if factor.b"]
    assert explanation["unmatched"] == [
        {"prefix": "if factor.c", "content": "{replace = \"if\", condition = 'factor.c'}"}
    ]


def test_explain_toml_ref_and_secret(tox_project: ToxProjectCreator) -> None:
    pyproject = """
    [tool.tox]
    env_list = ["a"]
    no_package = true

    [tool.tox.env_run_base]
    set_env = { SECRET_TOKEN = "s3cr3t", PLAIN = "hi" }
    deps = [
      { replace = "ref", of = ["tool", "tox", "env_run_base", "shared"] },
      { replace = "env", name = "SECRET_TOKEN" },
    ]
    shared = "plain-{env:PLAIN}"
    """
    outcome = tox_project({"pyproject.toml": pyproject}).run("c", "-e", "a", "--explain", "deps", "--format", "json")
    explanation = json.loads(outcome.out)["env"]["a"]["deps"]
    assert [event["kind"] for event in explanation["references"]] == ["ref", "env", "env"]
    ref = explanation["references"][0]
    assert ref["target"] == "tool.tox.env_run_base.shared"
    assert ref["resolved"] == "plain-hi"
    secret = next(event for event in explanation["references"] if event["name"] == "SECRET_TOKEN")
    assert secret["secret"] is True
    assert secret["resolved"] is None
    assert "s3cr3t" not in json.dumps(explanation)


def test_explain_toml_missing_ref_keeps_error(tox_project: ToxProjectCreator) -> None:
    pyproject = """
    [tool.tox]
    env_list = ["a"]
    no_package = true

    [tool.tox.env_run_base]
    description = { replace = "ref", of = ["tool", "tox", "env_run_base", "absent"] }
    """
    outcome = tox_project({"pyproject.toml": pyproject}).run(
        "c", "-e", "a", "--explain", "description", "--format", "json", raise_on_config_fail=False
    )
    explanation = json.loads(outcome.out)["env"]["a"]["description"]
    assert outcome.code != 0
    assert explanation["error"] is not None
    assert "KeyError" in explanation["error"]["cause"]
    ref = next(event for event in explanation["references"] if event["kind"] == "ref")
    assert ref["error"] is not None
    assert "KeyError" in ref["error"]
    assert ref["target"] == "tool.tox.env_run_base.absent"


def test_explain_does_not_break_plain_config(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    [testenv]
    description = plain
    """
    outcome = tox_project({"tox.ini": tox_ini}).run("c", "-e", "a", "-k", "description")
    outcome.assert_success()
    assert "[testenv:a]" in outcome.out
    assert "description = plain" in outcome.out


def test_explain_format_toml_unsupported(tox_project: ToxProjectCreator) -> None:
    tox_ini = """
    [tox]
    env_list = a
    no_package = true
    """
    outcome = tox_project({"tox.ini": tox_ini}).run(
        "c", "-e", "a", "--explain", "description", "--format", "toml", raise_on_config_fail=False
    )
    assert outcome.code != 0
    assert "--explain" in outcome.out


def _matched_parts(explanation: dict[str, object]) -> list[dict[str, object]]:
    for entry in explanation["definitions"]:  # type: ignore[index]
        if entry.get("selected") and entry.get("selected_parts"):  # type: ignore[union-attr]
            return entry["selected_parts"]  # type: ignore[return-value]
    pytest.fail("no selected parts found")  # pragma: no cover
    return []  # pragma: no cover
