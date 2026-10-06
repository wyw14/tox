"""Show materialized configuration of tox environments."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal, get_args

from tox.plugin import impl
from tox.report import HandledError
from tox.session.cmd.run.common import env_run_create_flags
from tox.session.env_select import CliEnv, register_env_select_flags

if TYPE_CHECKING:
    from tox.config.cli.parser import ToxParser
    from tox.session.state import State

ConfigFormat = Literal["ini", "json", "toml"]


@impl
def tox_add_option(parser: ToxParser) -> None:
    our = parser.add_command("config", ["c"], "show tox configuration", show_config)
    our.add_argument(
        "-k",
        nargs="+",
        help="list just configuration keys specified",
        dest="list_keys_only",
        default=[],
        metavar="key",
    )
    our.add_argument(
        "--core",
        action="store_true",
        help="show core options (by default is hidden unless -e ALL is passed)",
        dest="show_core",
    )
    our.add_argument(
        "--explain",
        nargs="+",
        default=[],
        dest="explain_keys",
        metavar="key",
        help="explain, without running anything, how the final value of the configuration keys is derived: "
        "the selected definitions, the reference chain and the substituted result",
    )
    our.add_argument(
        "--show-unmatched",
        "--unmatched",
        action="store_true",
        default=False,
        dest="show_unmatched",
        help="with --explain, also list factor conditions that did not match for the current environment",
    )
    our.add_argument(
        "--format",
        choices=get_args(ConfigFormat),
        default="ini",
        help="output format (default: %(default)s)",
        dest="config_format",
    )
    our.add_argument(
        "-o",
        "--output-file",
        of_type=Path,
        default=None,
        help="write output to file instead of stdout",
        dest="output_file",
    )
    register_env_select_flags(our, default=CliEnv())
    env_run_create_flags(our, mode="config")


def show_config(state: State) -> int:
    from .explain import show_config_explain, show_config_explain_json
    from .ini import show_config_ini  # ruff:ignore[import-outside-top-level]
    from .json_format import show_config_json  # ruff:ignore[import-outside-top-level]
    from .toml_format import show_config_toml  # ruff:ignore[import-outside-top-level]

    if state.conf.options.explain_keys:
        fmt: ConfigFormat = state.conf.options.config_format
        if fmt == "json":
            return show_config_explain_json(state)
        if fmt == "toml":
            msg = "--explain is supported with --format ini or --format json"
            raise HandledError(msg)
        return show_config_explain(state)

    fmt = state.conf.options.config_format
    if fmt == "json":
        return show_config_json(state)
    if fmt == "toml":
        return show_config_toml(state)
    return show_config_ini(state)
