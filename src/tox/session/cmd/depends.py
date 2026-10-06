"""Visualize tox environment dependencies."""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, cast

from tox.config.cli.parser import CORE
from tox.config.types import EnvList
from tox.plugin import impl
from tox.session.cmd.run.common import env_run_create_flags, run_order
from tox.session.env_select import CliEnv, register_env_select_flags

if TYPE_CHECKING:
    from tox.config.cli.parser import ToxParser
    from tox.session.state import State
    from tox.tox_env.runner import RunToxEnv

#: declared prerequisite that matches an environment which is not part of the current selection
NOT_SELECTED = "not selected"
#: declared prerequisite that matches no environment after factor/condition expansion
UNDEFINED = "undefined"
#: marks a prerequisite chain looping back to an ancestor
CYCLIC = "cyclic dependency"

_INDENT = "   "


@impl
def tox_add_option(parser: ToxParser) -> None:
    our = parser.add_command(
        "depends",
        ["de"],
        "visualize tox environment dependencies",
        depends,
        inherit=frozenset({CORE}),
    )
    register_env_select_flags(our, default=CliEnv())
    env_run_create_flags(our, mode="depends")


def depends(state: State) -> int:
    if _explicit_selection(state):
        return _selection_plan(state)
    return _full_graph(state)


def _explicit_selection(state: State) -> bool:
    options = state.conf.options
    env = cast("CliEnv | None", getattr(options, "env", None))
    return bool(options.labels or options.factors) or (env is not None and not env.is_default_list)


def _package_names(state: State, env: str) -> list[str]:
    run_env = cast("RunToxEnv", state.envs[env])
    package: list[str] = []
    try:
        for pkg_env in run_env.package_envs:
            package.append(pkg_env.name)  # ruff:ignore[manual-list-comprehension]
    except Exception as exception:  # ruff:ignore[blind-except]
        package.append(f"... ({exception})")
    return package


def _print_env_line(state: State, at: int, env: str) -> None:
    print(f"{_INDENT * at}{env}", end="")  # ruff:ignore[print]
    package = " | ".join(_package_names(state, env))
    if package:  # packaging environments are build/order constraints, not selected run environments
        print(f" ~ {package}", end="")  # ruff:ignore[print]
    print()  # ruff:ignore[print]


def _full_graph(state: State) -> int:
    to_run_list = list(state.envs.iter(only_active=False))
    order, todo = run_order(state, to_run_list)
    print(f"Execution order: {', '.join(order)}")  # ruff:ignore[print]

    deps: dict[str, list[str]] = {k: [o for o in order if o in v] for k, v in todo.items()}
    deps["ALL"] = to_run_list

    def _handle(at: int, env: str) -> None:
        print("   " * at, end="")  # ruff:ignore[print]
        print(env, end="")  # ruff:ignore[print]
        if env != "ALL":
            names = " | ".join(_package_names(state, env))
            if names:
                print(f" ~ {names}", end="")  # ruff:ignore[print]
        print()  # ruff:ignore[print]
        at += 1
        for dep in deps[env]:
            _handle(at, dep)

    _handle(0, "ALL")
    return 0


def _resolve_prerequisites(
    env: str,
    order: list[str],
    defined: list[str],
    declared: dict[str, list[str]],
) -> list[tuple[bool, str]]:
    """Resolve the declared prerequisites of ``env`` to ``(is_active, line)`` pairs.

    Active pairs are real scheduler edges whose environments will execute first. Inactive pairs are rendered as
    annotated leaves, distinguishing an environment that exists but is not selected from a name that matches no
    environment after factor/condition expansion.
    """
    resolved: list[tuple[bool, str]] = []
    seen: set[str] = set()
    for entry in declared.get(env, []):
        matches = [name for name in defined if fnmatchcase(name, entry)]
        matches_self = env in matches  # the scheduler ignores an environment depending on itself
        if matches_self:
            matches.remove(env)
        if not matches:
            if not matches_self and entry not in seen:  # a self-only match is a no-op, not a missing name
                resolved.append((False, f"{entry} ({UNDEFINED})"))
                seen.add(entry)
            continue
        # selected matches follow execution order (they are the real ordering edges), the rest merely resolve
        for name in (n for n in order if n != env and fnmatchcase(n, entry)):
            if name not in seen:
                resolved.append((True, name))
                seen.add(name)
        for name in matches:
            if name not in seen:
                resolved.append((False, f"{name} ({NOT_SELECTED})"))
                seen.add(name)
    return resolved


def _selection_plan(state: State) -> int:
    # use exactly the environments and edges the scheduler would run with - read-only and never widen the selection
    to_run_list = list(state.envs.iter())
    order, _ = run_order(state, to_run_list)
    print(f"Execution order: {', '.join(order)}")  # ruff:ignore[print]

    defined = list(state.envs.iter(only_active=False))
    declared = {name: list(cast("RunToxEnv", state.envs[name]).conf.get("depends", EnvList).envs) for name in defined}

    def render(env: str, at: int, path: frozenset[str]) -> None:
        _print_env_line(state, at, env)
        path |= {env}
        for is_active, label in _resolve_prerequisites(env, order, defined, declared):
            if is_active and label not in path:  # recurse: indirect prerequisites stay traceable inside the selection
                render(label, at + 1, path)
            elif is_active:  # active cycles are reported by run_order; this only guards declaration cycles
                print(f"{_INDENT * (at + 1)}{label} ({CYCLIC})")  # ruff:ignore[print]
            else:
                print(f"{_INDENT * (at + 1)}{label}")  # ruff:ignore[print]

    for env in order:
        render(env, 0, frozenset())
    return 0
