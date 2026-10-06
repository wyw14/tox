from __future__ import annotations

import sys
from textwrap import dedent
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.conftest import PatchPrevPy
    from tox.pytest import ToxProjectCreator


def test_depends_wheel(tox_project: ToxProjectCreator, patch_prev_py: PatchPrevPy) -> None:
    prev_ver, impl, _ = patch_prev_py(True)  # has previous python
    ver = sys.version_info[0:2]
    py = f"py{''.join(str(i) for i in ver)}"
    prev_py = f"py{prev_ver}"
    ini = f"""
    [tox]
    env_list = py,{py},{prev_py},py31,cov2,cov
    [testenv]
    package = wheel
    [testenv:cov]
    depends = py,{py},{prev_py},py31
    skip_install = true
    [testenv:cov2]
    depends = cov
    skip_install = true
    """
    project = tox_project({"tox.ini": ini, "pyproject.toml": ""})
    outcome = project.run("de")
    outcome.assert_success()

    expected = f"""
    Execution order: py, {py}, {prev_py}, py31, cov, cov2
    ALL
       py ~ .pkg
       {py} ~ .pkg
       {prev_py} ~ .pkg | .pkg-{impl}{prev_ver}
       py31 ~ .pkg
       cov2
          cov
             py ~ .pkg
             {py} ~ .pkg
             {prev_py} ~ .pkg | .pkg-{impl}{prev_ver}
             py31 ~ .pkg
       cov
          py ~ .pkg
          {py} ~ .pkg
          {prev_py} ~ .pkg | .pkg-{impl}{prev_ver}
          py31 ~ .pkg
    """
    assert outcome.out == dedent(expected).lstrip()


def test_depends_sdist(tox_project: ToxProjectCreator, patch_prev_py: PatchPrevPy) -> None:
    prev_ver, _impl, _ = patch_prev_py(True)  # has previous python
    ver = sys.version_info[0:2]
    py = f"py{''.join(str(i) for i in ver)}"
    prev_py = f"py{prev_ver}"
    ini = f"""
    [tox]
    env_list = py,{py},{prev_py},py31,cov2,cov
    [testenv]
    package = sdist
    [testenv:cov]
    depends = py,{py},{prev_py},py31
    skip_install = true
    [testenv:cov2]
    depends = cov
    skip_install = true
    """
    project = tox_project({"tox.ini": ini, "pyproject.toml": ""})
    outcome = project.run("de")
    outcome.assert_success()

    expected = f"""
    Execution order: py, {py}, {prev_py}, py31, cov, cov2
    ALL
       py ~ .pkg
       {py} ~ .pkg
       {prev_py} ~ .pkg
       py31 ~ .pkg
       cov2
          cov
             py ~ .pkg
             {py} ~ .pkg
             {prev_py} ~ .pkg
             py31 ~ .pkg
       cov
          py ~ .pkg
          {py} ~ .pkg
          {prev_py} ~ .pkg
          py31 ~ .pkg
    """
    assert outcome.out == dedent(expected).lstrip()


def test_depends_glob_star(tox_project: ToxProjectCreator) -> None:
    toml = """
    env_list = ["3.12", "3.13", "3.14", "lint", "cov"]
    [env_run_base]
    package = "skip"
    [env.cov]
    depends = ["3.*"]
    """
    project = tox_project({"tox.toml": toml})
    outcome = project.run("de")
    outcome.assert_success()
    expected = dedent("""\
    Execution order: 3.12, 3.13, 3.14, lint, cov
    ALL
       3.12
       3.13
       3.14
       lint
       cov
          3.12
          3.13
          3.14
    """)
    assert outcome.out == expected


def test_depends_glob_question_mark(tox_project: ToxProjectCreator) -> None:
    toml = """
    env_list = ["a1", "a2", "ab", "cov"]
    [env_run_base]
    package = "skip"
    [env.cov]
    depends = ["a?"]
    """
    project = tox_project({"tox.toml": toml})
    outcome = project.run("de")
    outcome.assert_success()
    expected = dedent("""\
    Execution order: a1, a2, ab, cov
    ALL
       a1
       a2
       ab
       cov
          a1
          a2
          ab
    """)
    assert outcome.out == expected


def test_depends_glob_no_match(tox_project: ToxProjectCreator) -> None:
    toml = """
    env_list = ["lint", "cov"]
    [env_run_base]
    package = "skip"
    [env.cov]
    depends = ["py*"]
    """
    project = tox_project({"tox.toml": toml})
    outcome = project.run("de")
    outcome.assert_success()
    expected = dedent("""\
    Execution order: lint, cov
    ALL
       lint
       cov
    """)
    assert outcome.out == expected


def test_depends_glob_mixed(tox_project: ToxProjectCreator) -> None:
    toml = """
    env_list = ["3.13", "3.14", "lint", "cov"]
    [env_run_base]
    package = "skip"
    [env.cov]
    depends = ["lint", "3.*"]
    """
    project = tox_project({"tox.toml": toml})
    outcome = project.run("de")
    outcome.assert_success()
    expected = dedent("""\
    Execution order: 3.13, 3.14, lint, cov
    ALL
       3.13
       3.14
       lint
       cov
          3.13
          3.14
          lint
    """)
    assert outcome.out == expected


def test_depends_glob_excludes_self(tox_project: ToxProjectCreator) -> None:
    toml = """
    env_list = ["a", "b", "cov"]
    [env_run_base]
    package = "skip"
    [env.cov]
    depends = ["*"]
    """
    project = tox_project({"tox.toml": toml})
    outcome = project.run("de")
    outcome.assert_success()
    expected = dedent("""\
    Execution order: a, b, cov
    ALL
       a
       b
       cov
          a
          b
    """)
    assert outcome.out == expected


def test_depends_ini_glob_star(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = 3.12,3.13,3.14,lint,cov
    [testenv]
    skip_install = true
    [testenv:cov]
    depends = 3.*
    """
    project = tox_project({"tox.ini": ini})
    outcome = project.run("de")
    outcome.assert_success()
    expected = dedent("""\
    Execution order: 3.12, 3.13, 3.14, lint, cov
    ALL
       3.12
       3.13
       3.14
       lint
       cov
          3.12
          3.13
          3.14
    """)
    assert outcome.out == expected


def test_depends_ini_glob_question_mark(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = a1,a2,ab,cov
    [testenv]
    skip_install = true
    [testenv:cov]
    depends = a?
    """
    project = tox_project({"tox.ini": ini})
    outcome = project.run("de")
    outcome.assert_success()
    expected = dedent("""\
    Execution order: a1, a2, ab, cov
    ALL
       a1
       a2
       ab
       cov
          a1
          a2
          ab
    """)
    assert outcome.out == expected


def test_depends_ini_glob_no_match(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = lint,cov
    [testenv]
    skip_install = true
    [testenv:cov]
    depends = py*
    """
    project = tox_project({"tox.ini": ini})
    outcome = project.run("de")
    outcome.assert_success()
    expected = dedent("""\
    Execution order: lint, cov
    ALL
       lint
       cov
    """)
    assert outcome.out == expected


def test_depends_ini_glob_mixed(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = 3.13,3.14,lint,cov
    [testenv]
    skip_install = true
    [testenv:cov]
    depends = lint,3.*
    """
    project = tox_project({"tox.ini": ini})
    outcome = project.run("de")
    outcome.assert_success()
    expected = dedent("""\
    Execution order: 3.13, 3.14, lint, cov
    ALL
       3.13
       3.14
       lint
       cov
          3.13
          3.14
          lint
    """)
    assert outcome.out == expected


def test_depends_ini_glob_excludes_self(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = a,b,cov
    [testenv]
    skip_install = true
    [testenv:cov]
    depends = *
    """
    project = tox_project({"tox.ini": ini})
    outcome = project.run("de")
    outcome.assert_success()
    expected = dedent("""\
    Execution order: a, b, cov
    ALL
       a
       b
       cov
          a
          b
    """)
    assert outcome.out == expected


def test_depends_help(tox_project: ToxProjectCreator) -> None:
    outcome = tox_project({"tox.ini": ""}).run("de", "-h")
    outcome.assert_success()


def test_depends_circular(tox_project: ToxProjectCreator) -> None:
    ini = "[tox]\nenv_list = a,b\n[testenv]\npackage = skip\n[testenv:a]\ndepends = b\n[testenv:b]\ndepends = a\n"
    project = tox_project({"tox.ini": ini})

    outcome = project.run("de")

    outcome.assert_failed(code=-2)
    assert "circular dependency detected between environments: a | b" in outcome.out, outcome.out


def test_depends_circular_run(tox_project: ToxProjectCreator) -> None:
    ini = "[tox]\nenv_list = a,b\n[testenv]\npackage = skip\n[testenv:a]\ndepends = b\n[testenv:b]\ndepends = a\n"
    project = tox_project({"tox.ini": ini})

    outcome = project.run("r", "--notest")

    outcome.assert_failed(code=-2)
    assert "circular dependency detected between environments: a | b" in outcome.out, outcome.out
    assert "Traceback" not in outcome.err, outcome.err


_PLAN_INI = """
[tox]
env_list = a,b,c,cov,lint
[testenv]
package = skip
[testenv:cov]
depends = a,b,ghost
[testenv:b]
depends = c
"""


def test_depends_plan_subset(tox_project: ToxProjectCreator) -> None:
    # only selected environments execute; declared prerequisites are annotated, nothing is pulled into the run
    project = tox_project({"tox.ini": _PLAN_INI})

    outcome = project.run("de", "-e", "cov,b")

    outcome.assert_success()
    expected = dedent("""\
    Execution order: b, cov
    b
       c (not selected)
    cov
       a (not selected)
       b
          c (not selected)
       ghost (undefined)
    """)
    assert outcome.out == expected


def test_depends_plan_indirect_active(tox_project: ToxProjectCreator) -> None:
    # the whole selected chain is active: c is an indirect prerequisite of cov and visible through b
    project = tox_project({"tox.ini": _PLAN_INI})

    outcome = project.run("de", "-e", "cov,b,c")

    outcome.assert_success()
    expected = dedent("""\
    Execution order: c, b, cov
    c
    b
       c
    cov
       a (not selected)
       b
          c
       ghost (undefined)
    """)
    assert outcome.out == expected


def test_depends_plan_only_target(tox_project: ToxProjectCreator) -> None:
    # a single selected environment never pulls its prerequisites into the execution order
    project = tox_project({"tox.ini": _PLAN_INI})

    outcome = project.run("de", "-e", "cov")

    outcome.assert_success()
    expected = dedent("""\
    Execution order: cov
    cov
       a (not selected)
       b (not selected)
       ghost (undefined)
    """)
    assert outcome.out == expected


def test_depends_plan_glob_partial_match(tox_project: ToxProjectCreator) -> None:
    toml = """
    env_list = ["py311", "py312", "lint", "cov"]
    [env_run_base]
    package = "skip"
    [env.cov]
    depends = ["py*", "ghost"]
    """
    project = tox_project({"tox.toml": toml})

    outcome = project.run("de", "-e", "cov,py311")

    outcome.assert_success()
    expected = dedent("""\
    Execution order: py311, cov
    py311
    cov
       py311
       py312 (not selected)
       ghost (undefined)
    """)
    assert outcome.out == expected


def test_depends_plan_expanded_missing_vs_unselected(tox_project: ToxProjectCreator) -> None:
    # after factor expansion py311 names an existing unselected env, py313 names no environment at all
    ini = """
    [tox]
    env_list = py311,py312,cov
    [testenv]
    package = skip
    [testenv:cov]
    depends = py3{11,13}
    """
    project = tox_project({"tox.ini": ini})

    outcome = project.run("de", "-e", "cov")

    outcome.assert_success()
    expected = dedent("""\
    Execution order: cov
    cov
       py311 (not selected)
       py313 (undefined)
    """)
    assert outcome.out == expected


def test_depends_plan_glob_no_match_is_undefined(tox_project: ToxProjectCreator) -> None:
    toml = """
    env_list = ["lint", "cov"]
    [env_run_base]
    package = "skip"
    [env.cov]
    depends = ["py*"]
    """
    project = tox_project({"tox.toml": toml})

    outcome = project.run("de", "-e", "ALL")

    outcome.assert_success()
    expected = dedent("""\
    Execution order: lint, cov
    lint
    cov
       py* (undefined)
    """)
    assert outcome.out == expected


def test_depends_plan_factor_selection(tox_project: ToxProjectCreator) -> None:
    toml = """
    env_list = ["py311", "py312", "cov"]
    [env_run_base]
    package = "skip"
    [env.cov]
    depends = ["py311"]
    """
    project = tox_project({"tox.toml": toml})

    outcome = project.run("de", "-f", "cov")

    outcome.assert_success()
    expected = dedent("""\
    Execution order: cov
    cov
       py311 (not selected)
    """)
    assert outcome.out == expected


def test_depends_plan_empty_selection(tox_project: ToxProjectCreator) -> None:
    project = tox_project({"tox.ini": _PLAN_INI})

    outcome = project.run("de", "-f", "no-such-factor")

    outcome.assert_success()
    assert outcome.out == "Execution order: \n"


def test_depends_plan_deduplicates_declarations(tox_project: ToxProjectCreator) -> None:
    toml = """
    env_list = ["b", "cov"]
    [env_run_base]
    package = "skip"
    [env.cov]
    depends = ["b", "b*"]
    """
    project = tox_project({"tox.toml": toml})

    outcome = project.run("de", "-e", "cov,b")

    outcome.assert_success()
    expected = dedent("""\
    Execution order: b, cov
    b
    cov
       b
    """)
    assert outcome.out == expected


def test_depends_plan_package_environments(tox_project: ToxProjectCreator) -> None:
    ini = """
    [tox]
    env_list = py,cov
    [testenv]
    package = wheel
    [testenv:cov]
    skip_install = true
    depends = py,ghost
    """
    project = tox_project({"tox.ini": ini, "pyproject.toml": ""})

    outcome = project.run("de", "-e", "cov,py")

    outcome.assert_success()
    expected = dedent("""\
    Execution order: py, cov
    py ~ .pkg
    cov
       py ~ .pkg
       ghost (undefined)
    """)
    assert outcome.out == expected


_CYCLE_INI = """
[tox]
env_list = a,b,cov
[testenv]
package = skip
[testenv:a]
depends = b
[testenv:b]
depends = a
[testenv:cov]
depends = a
"""


def test_depends_plan_circular_active(tox_project: ToxProjectCreator) -> None:
    project = tox_project({"tox.ini": _CYCLE_INI})

    outcome = project.run("de", "-e", "cov,a,b")

    outcome.assert_failed(code=-2)
    assert "circular dependency detected between environments: cov | a | b" in outcome.out, outcome.out


def test_depends_plan_self_dependency_ignored(tox_project: ToxProjectCreator) -> None:
    # a declaration matching only the environment itself is a scheduler no-op, not an undefined prerequisite
    toml = """
    env_list = ["a", "cov"]
    [env_run_base]
    package = "skip"
    [env.cov]
    depends = ["cov*", "ghost"]
    """
    project = tox_project({"tox.toml": toml})

    outcome = project.run("de", "-e", "ALL")

    outcome.assert_success()
    expected = dedent("""\
    Execution order: a, cov
    a
    cov
       ghost (undefined)
    """)
    assert outcome.out == expected


def test_depends_plan_circular_inactive(tox_project: ToxProjectCreator) -> None:
    # a cycle living entirely outside the selection neither errors nor is traversed as an execution edge
    project = tox_project({"tox.ini": _CYCLE_INI})

    outcome = project.run("de", "-e", "cov")

    outcome.assert_success()
    expected = dedent("""\
    Execution order: cov
    cov
       a (not selected)
    """)
    assert outcome.out == expected
