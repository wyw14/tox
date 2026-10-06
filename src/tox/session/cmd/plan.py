"""Preview the execution plan of tox environments without running any command.

The plan is built from configuration only: it shows the setup activity (environment creation and installation) and
the ``commands_pre``/``commands``/``commands_post`` command sets of every selected environment, together with the
effect a failure has at each stage. No command is executed and command exit codes are never assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from tox.config.types import Command
from tox.plugin import impl
from tox.session.cmd.run.common import env_run_create_flags, run_order
from tox.session.env_select import CliEnv, register_env_select_flags
from tox.tox_env.python.pip.req_file import PythonDeps

if TYPE_CHECKING:
    from tox.config.cli.parser import Parsed, ToxParser
    from tox.config.sets import EnvConfigSet
    from tox.session.state import State
    from tox.tox_env.runner import RunToxEnv

#: command stages executed after environment setup, in order
PRE = "commands_pre"
MAIN = "commands"
POST = "commands_post"
STAGES: tuple[str, ...] = (PRE, MAIN, POST)

#: failure propagation explanation per stage (when ``ignore_errors`` is not set)
STAGE_FAILURE_NOTE = {
    PRE: "a non-ignored failure here skips the remaining commands_pre and all commands; commands_post always runs",
    MAIN: "a non-ignored failure here skips the remaining commands; commands_post always runs",
    POST: "a non-ignored failure here skips the remaining commands_post",
}

FOOTER = "preview only: no command is executed and command exit codes are not known until tox runs them"
IGNORE_ERRORS_NOTE = (
    "ignore_errors is set: every command runs even after a failure; the first non-zero exit code is reported"
)
EXTRA_SETUP_FAILURE_NOTE = (
    "a non-ignored failure here aborts environment setup; commands_pre, commands and commands_post do not run"
)


@dataclass(frozen=True)
class SetupStep:
    """A single environment setup activity (environment creation or installation)."""

    text: str
    skipped: bool = False
    skip_reason: str = ""
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class EnvPlan:
    """The execution plan of a single tox environment."""

    name: str
    setup_steps: list[SetupStep]
    extra_setup: list[Command]
    stages: dict[str, list[Command]] = field(default_factory=dict)
    ignore_errors: bool = False
    ignore_outcome: bool = False
    retry_count: int = 0
    commands_run: bool = True
    commands_skip_reason: str = ""


@impl
def tox_add_option(parser: ToxParser) -> None:
    our = parser.add_command(
        "plan",
        ["pl"],
        "preview the execution plan without running any command",
        plan,
        inherit=frozenset({"core"}),
    )
    register_env_select_flags(our, default=CliEnv())
    env_run_create_flags(our, mode="run")


def plan(state: State) -> int:
    to_run_list = list(state.envs.iter())
    if not to_run_list:
        print("No environments selected for this run.")  # ruff:ignore[print]
        print(FOOTER)  # ruff:ignore[print]
        return 0

    order, _todo = run_order(state, to_run_list)
    print(render_plan(state, order))  # ruff:ignore[print]
    return 0


def render_plan(state: State, order: list[str]) -> str:
    """Render the execution plan for the given environments, in execution order."""
    options = state.conf.options
    lines: list[str] = [f"Execution order: {', '.join(order)}"]
    lines.extend(_option_notes(state, order))

    unavailable = [name for name in state.envs.unavailable_envs() if name not in order]
    for name in order:
        tox_env = cast("RunToxEnv", state.envs[name])
        lines.extend(("", f"[testenv:{name}]"))
        lines.extend(render_env_plan(build_env_plan(tox_env, options)))
    if unavailable:
        lines.extend(("", f"unavailable environments (runner not installed): {', '.join(unavailable)}"))
    lines.extend(("", FOOTER))
    return "\n".join(lines)


def _option_notes(state: State, order: list[str]) -> list[str]:
    options = state.conf.options
    notes: list[str] = []
    if getattr(options, "no_test", False):
        notes.append(
            "options: --notest - environments are prepared; commands_pre, commands and commands_post do not run"
        )
    if getattr(options, "package_only", False):
        notes.append(
            "options: --pkg-only - only packaging is performed; the package is built but not installed and "
            "commands do not run"
        )
    if getattr(options, "skip_pkg_install", False):
        notes.append("options: --skip-pkg-install - the package is neither built nor installed")
    if getattr(options, "skip_env_install", False):
        notes.append("options: --skip-env-install - dependencies and packages are not installed")
    install_pkg = getattr(options, "install_pkg", None)
    if install_pkg is not None:
        notes.append(f"options: --installpkg {install_pkg} - this package is installed instead of building the project")
    fail_fast = getattr(options, "fail_fast", False) or any(
        cast("RunToxEnv", state.envs[env]).conf.get("fail_fast", bool) for env in order
    )
    if fail_fast:
        notes.append("options: --fail-fast - after the first failing environment the remaining ones are not started")
    return notes


def build_env_plan(tox_env: RunToxEnv, options: Parsed) -> EnvPlan:
    """Build the execution plan for one environment from its configuration (no command is executed)."""
    conf = tox_env.conf
    no_test = getattr(options, "no_test", False)
    package_only = getattr(options, "package_only", False)
    skip_env_install = getattr(options, "skip_env_install", False)
    skip_pkg_install = getattr(options, "skip_pkg_install", False) or skip_env_install

    if package_only:
        commands_skip_reason = "--pkg-only"
        commands_run = False
    elif no_test:
        commands_skip_reason = "--notest"
        commands_run = False
    else:
        commands_skip_reason = ""
        commands_run = True

    setup_steps = [SetupStep("create/reuse the environment")]
    setup_steps.extend(_dependency_steps(conf, skip_env_install))
    setup_steps.append(_package_step(tox_env, options, package_only, skip_pkg_install))

    extra_setup = conf.get("extra_setup_commands", list[Command]) if "extra_setup_commands" in conf else []
    stages = {stage: conf.get(stage, list[Command]) for stage in STAGES}

    return EnvPlan(
        name=conf.name,
        setup_steps=setup_steps,
        extra_setup=extra_setup,
        stages=stages,
        ignore_errors=conf.get("ignore_errors", bool),
        ignore_outcome=conf.get("ignore_outcome", bool),
        retry_count=conf.get("commands_retry", int),
        commands_run=commands_run,
        commands_skip_reason=commands_skip_reason,
    )


def _dependency_steps(
    conf: EnvConfigSet,
    skip_env_install: bool,  # ruff:ignore[boolean-type-hint-positional-argument]
) -> list[SetupStep]:
    steps: list[SetupStep] = []
    if "pylock" in conf and conf.get("pylock", str):
        pylock = conf.get("pylock", str)
        step = SetupStep(
            f"install locked dependencies from {pylock}",
            skipped=skip_env_install,
            skip_reason="--skip-env-install",
        )
        steps.append(step)
    elif "deps" in conf:
        deps = conf.get_optional("deps", PythonDeps)
        if deps is not None and deps.lines():
            steps.append(
                SetupStep(
                    "install dependencies",
                    skipped=skip_env_install,
                    skip_reason="--skip-env-install",
                    details=tuple(deps.lines()),
                )
            )
    if "dependency_groups" in conf:
        groups = sorted(conf.get("dependency_groups", set[str]))
        if groups:
            steps.append(
                SetupStep(
                    f"install dependency groups: {', '.join(groups)}",
                    skipped=skip_env_install,
                    skip_reason="--skip-env-install",
                )
            )
    return steps


def _package_step(
    tox_env: RunToxEnv,
    options: Parsed,
    package_only: bool,  # ruff:ignore[boolean-type-hint-positional-argument]
    skip_pkg_install: bool,  # ruff:ignore[boolean-type-hint-positional-argument]
) -> SetupStep:
    conf = tox_env.conf
    package_type = conf.get_optional("package", str) if "package" in conf else None

    if package_type is None or package_type == "skip":
        return SetupStep("no package is built or installed (package = skip)")

    if package_type == "external" or getattr(options, "install_pkg", None) is not None:
        install_pkg = getattr(options, "install_pkg", None)
        text = (
            f"install the package provided with --installpkg: {install_pkg}"
            if install_pkg is not None
            else "install an externally provided package"
        )
        return SetupStep(text, skipped=skip_pkg_install, skip_reason=_package_skip_reason(options))

    try:
        package_envs = ", ".join(env.name for env in tox_env.package_envs)
    except Exception:  # a broken packaging setup must not break the preview  # ruff:ignore[blind-except]
        package_envs = ""
    package_envs = package_envs or "the package environment"
    if package_type == "deps-only":
        text = f"install only the package dependencies via {package_envs}"
        return SetupStep(text, skipped=package_only or skip_pkg_install, skip_reason=_package_skip_reason(options))

    action = "install it into the environment" if not package_only else "do not install it (--pkg-only)"
    text = f"build {package_type} package via {package_envs} and {action}"
    return SetupStep(text, skipped=skip_pkg_install, skip_reason=_package_skip_reason(options))


def _package_skip_reason(options: Parsed) -> str:
    if getattr(options, "skip_env_install", False):
        return "--skip-env-install"
    if getattr(options, "skip_pkg_install", False):
        return "--skip-pkg-install"
    return ""


def render_env_plan(env_plan: EnvPlan) -> list[str]:
    """Render one environment plan as text lines."""
    lines: list[str] = ["  setup:"]
    for at, step in enumerate(env_plan.setup_steps, start=1):
        suffix = (f" (skipped: {step.skip_reason})" if step.skip_reason else " (skipped)") if step.skipped else ""
        lines.append(f"    {at}. {step.text}{suffix}")
        if step.details and not step.skipped:
            lines.extend(f"       - {detail}" for detail in step.details)

    if env_plan.extra_setup:
        lines.append("")
        lines.extend(_render_command_set("extra_setup_commands", env_plan.extra_setup, env_plan, setup_stage=True))

    if env_plan.ignore_errors:
        lines.extend(("", f"  {IGNORE_ERRORS_NOTE}"))
    for stage in STAGES:
        lines.append("")
        lines.extend(_render_command_set(stage, env_plan.stages.get(stage, []), env_plan))

    if env_plan.retry_count:
        lines.extend(("", f"  commands_retry: a failed command is retried up to {env_plan.retry_count} time(s)"))
    if env_plan.ignore_outcome:
        lines.extend(("", "  ignore_outcome: a failure of this environment is reported as a warning only"))
    return lines


def _render_command_set(
    stage: str, commands: list[Command], env_plan: EnvPlan, *, setup_stage: bool = False
) -> list[str]:
    title = "extra_setup_commands" if stage == "extra_setup_commands" else stage
    if not commands:
        return [f"  {title}: (none)"]

    suffix = f" [not run: {env_plan.commands_skip_reason}]" if not setup_stage and not env_plan.commands_run else ""
    lines = [f"  {title} ({len(commands)}){suffix}:"]
    for at, command in enumerate(commands, start=1):
        marker = f"  {_command_marker(command)}" if _command_marker(command) else ""
        lines.append(f"    {at}. {command.shell}{marker}")
    if setup_stage:
        lines.append(f"       {IGNORE_ERRORS_NOTE if env_plan.ignore_errors else EXTRA_SETUP_FAILURE_NOTE}")
    elif env_plan.commands_run and not env_plan.ignore_errors:
        lines.append(f"       {STAGE_FAILURE_NOTE[stage]}")
    return lines


def _command_marker(command: Command) -> str:
    if command.ignore_exit_code:
        return "[failure ignored: treated as success]"
    if command.invert_exit_code:
        return "[failure expected: non-zero exit code is success]"
    return ""


__all__ = (
    "STAGES",
    "EnvPlan",
    "SetupStep",
    "build_env_plan",
    "plan",
    "render_env_plan",
    "render_plan",
)
