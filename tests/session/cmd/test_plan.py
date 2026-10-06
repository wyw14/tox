from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tox.pytest import ToxProjectCreator

FOOTER = "preview only: no command is executed and command exit codes are not known until tox runs them"
PRE_NOTE = "a non-ignored failure here skips the remaining commands_pre and all commands; commands_post always runs"
MAIN_NOTE = "a non-ignored failure here skips the remaining commands; commands_post always runs"
POST_NOTE = "a non-ignored failure here skips the remaining commands_post"
IGNORE_ERRORS_NOTE = (
    "ignore_errors is set: every command runs even after a failure; the first non-zero exit code is reported"
)
EXTRA_SETUP_NOTE = (
    "a non-ignored failure here aborts environment setup; commands_pre, commands and commands_post do not run"
)


def test_plan_commands_failure_flow(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    package = skip
    commands_pre = python prepare.py
    commands =
        pytest
        - flaky.sh
    commands_post = cleanup.sh
    """
    outcome = tox_project({"tox.ini": ini}).run("plan")
    outcome.assert_success()
    expected = f"""
    Execution order: py

    [testenv:py]
      setup:
        1. create/reuse the environment
        2. no package is built or installed (package = skip)

      commands_pre (1):
        1. python prepare.py
           {PRE_NOTE}

      commands (2):
        1. pytest
        2. flaky.sh  [failure ignored: treated as success]
           {MAIN_NOTE}

      commands_post (1):
        1. cleanup.sh
           {POST_NOTE}

    {FOOTER}
    """
    outcome.assert_out_err(expected, "")


def test_plan_invert_exit_code_marker(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    package = skip
    commands = ! may-fail
    """
    outcome = tox_project({"tox.ini": ini}).run("pl")
    outcome.assert_success()
    assert "1. may-fail  [failure expected: non-zero exit code is success]" in outcome.out
    assert MAIN_NOTE in outcome.out


def test_plan_ignore_errors_runs_everything(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    package = skip
    ignore_errors = true
    commands = pytest
    commands_post = cleanup.sh
    """
    outcome = tox_project({"tox.ini": ini}).run("plan")
    outcome.assert_success()
    assert IGNORE_ERRORS_NOTE in outcome.out
    # when ignore_errors is set no per-stage skipping note is printed
    assert PRE_NOTE not in outcome.out
    assert MAIN_NOTE not in outcome.out
    assert POST_NOTE not in outcome.out


def test_plan_empty_command_sets(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    package = skip
    """
    outcome = tox_project({"tox.ini": ini}).run("plan")
    outcome.assert_success()
    assert "  commands_pre: (none)" in outcome.out
    assert "  commands: (none)" in outcome.out
    assert "  commands_post: (none)" in outcome.out


def test_plan_notest_skips_command_stages(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    package = skip
    extra_setup_commands = python setup_extra.py
    commands_pre = python prepare.py
    commands = pytest
    commands_post = cleanup.sh
    """
    outcome = tox_project({"tox.ini": ini}).run("plan", "--notest")
    outcome.assert_success()
    assert (
        "options: --notest - environments are prepared; commands_pre, commands and commands_post do not run"
        in outcome.out
    )
    assert "  commands_pre (1) [not run: --notest]:" in outcome.out
    assert "  commands (1) [not run: --notest]:" in outcome.out
    assert "  commands_post (1) [not run: --notest]:" in outcome.out
    # extra setup commands are part of environment setup, so they still run under --notest
    assert "  extra_setup_commands (1):" in outcome.out
    assert "  extra_setup_commands (1) [not run:" not in outcome.out
    assert EXTRA_SETUP_NOTE in outcome.out
    # no failure propagation note for stages that do not run
    assert PRE_NOTE not in outcome.out
    assert MAIN_NOTE not in outcome.out
    assert POST_NOTE not in outcome.out


def test_plan_extra_setup_commands_failure_aborts(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    package = skip
    extra_setup_commands = python setup_extra.py
    commands = pytest
    """
    outcome = tox_project({"tox.ini": ini}).run("plan")
    outcome.assert_success()
    assert "  extra_setup_commands (1):" in outcome.out
    assert "    1. python setup_extra.py" in outcome.out
    assert EXTRA_SETUP_NOTE in outcome.out


def test_plan_skip_env_install(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    package = skip
    deps = pytest
    commands = pytest
    """
    outcome = tox_project({"tox.ini": ini}).run("plan", "--skip-env-install")
    outcome.assert_success()
    assert "options: --skip-env-install - dependencies and packages are not installed" in outcome.out
    assert "    2. install dependencies (skipped: --skip-env-install)" in outcome.out
    # commands are still planned to run
    assert "  commands (1):" in outcome.out
    assert MAIN_NOTE in outcome.out


def test_plan_deps_listed(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    package = skip
    deps =
        pytest
        coverage
    commands = pytest
    """
    outcome = tox_project({"tox.ini": ini}).run("plan")
    outcome.assert_success()
    assert "    2. install dependencies\n" in outcome.out
    assert "       - pytest" in outcome.out
    assert "       - coverage" in outcome.out
    assert "(skipped" not in outcome.out


@pytest.mark.parametrize("flag", ["--skip-pkg-install", "--skip-env-install"])
def test_plan_package_install_skipped(tox_project: ToxProjectCreator, flag: str) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    package = wheel
    commands = pytest
    """
    project = tox_project({"tox.ini": ini, "pyproject.toml": ""})
    outcome = project.run("plan", flag)
    outcome.assert_success()
    assert f"    2. build wheel package via .pkg and install it into the environment (skipped: {flag})" in outcome.out
    assert "  commands (1):" in outcome.out


def test_plan_pkg_only_builds_without_install(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    package = wheel
    deps = pytest
    commands = pytest
    """
    outcome = tox_project({"tox.ini": ini, "pyproject.toml": ""}).run("plan", "--pkg-only")
    outcome.assert_success()
    assert (
        "options: --pkg-only - only packaging is performed; the package is built but not installed and "
        "commands do not run"
    ) in outcome.out
    assert "    3. build wheel package via .pkg and do not install it (--pkg-only)" in outcome.out
    # dependencies are still installed, commands do not run
    assert "    2. install dependencies\n" in outcome.out
    assert "  commands (1) [not run: --pkg-only]:" in outcome.out


def test_plan_skip_install_config(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    skip_install = true
    commands = pytest
    """
    outcome = tox_project({"tox.ini": ini}).run("plan")
    outcome.assert_success()
    assert "    2. no package is built or installed (package = skip)" in outcome.out
    assert "  commands (1):" in outcome.out


def test_plan_retry_and_ignore_outcome(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    package = skip
    commands_retry = 3
    ignore_outcome = true
    commands = pytest
    """
    outcome = tox_project({"tox.ini": ini}).run("plan")
    outcome.assert_success()
    assert "  commands_retry: a failed command is retried up to 3 time(s)" in outcome.out
    assert "  ignore_outcome: a failure of this environment is reported as a warning only" in outcome.out


def test_plan_fail_fast_note(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = a,b
    [testenv]
    package = skip
    commands = pytest
    """
    outcome = tox_project({"tox.ini": ini}).run("plan", "--fail-fast")
    outcome.assert_success()
    assert (
        "options: --fail-fast - after the first failing environment the remaining ones are not started" in outcome.out
    )


def test_plan_no_environments(tox_project: ToxProjectCreator) -> None:
    outcome = tox_project({"tox.ini": "[tox]\nenv_list = py\n[testenv]\npackage = skip\n"}).run(
        "plan", "--skip-env", ".*"
    )
    outcome.assert_success()
    expected = f"""
    ROOT: skip environment py, matches filter '.*'
    No environments selected for this run.
    {FOOTER}
    """
    outcome.assert_out_err(expected, "")


def test_plan_env_selection(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = a,b
    [testenv]
    package = skip
    commands = pytest
    """
    outcome = tox_project({"tox.ini": ini}).run("plan", "-e", "b")
    outcome.assert_success()
    assert "Execution order: b" in outcome.out
    assert "[testenv:b]" in outcome.out
    assert "[testenv:a]" not in outcome.out


def test_plan_does_not_execute_commands(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    package = skip
    commands_pre = python prepare.py
    commands = pytest
    commands_post = cleanup.sh
    """
    project = tox_project({"tox.ini": ini})
    executed: list[str] = []
    project.patch_execute(lambda request: executed.append(request.shell_cmd) or 0)
    outcome = project.run("plan")
    outcome.assert_success()
    assert executed == []
    # the preview never claims an exit code
    assert "exit code 0" not in outcome.out
    assert " OK" not in outcome.out


def test_plan_does_not_create_run_environment(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py
    [testenv]
    package = skip
    commands = pytest
    """
    project = tox_project({"tox.ini": ini})
    outcome = project.run("plan")
    outcome.assert_success()
    assert not (project.path / ".tox" / "py" / "pyvenv.cfg").exists()


def test_plan_help(tox_project: ToxProjectCreator) -> None:
    outcome = tox_project({"tox.ini": ""}).run("-h")
    outcome.assert_success()
    assert "plan" in outcome.out
    assert "preview the execution plan without running any command" in outcome.out


def test_plan_shows_depends_order(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = a,b
    [testenv]
    package = skip
    commands = pytest
    [testenv:b]
    depends = a
    """
    outcome = tox_project({"tox.ini": ini}).run("plan")
    outcome.assert_success()
    assert (
        dedent(
            """\
        Execution order: a, b
        """
        )
        in outcome.out
    )
