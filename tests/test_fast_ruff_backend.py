import shutil

import pytest

from edulint.config.config import get_config_one
from edulint.fast import config_cache
from edulint.fast.ruff_backend import (
    RuffNotFoundError,
    find_ruff,
    lint_buffer,
    ruff_args,
    ruff_to_problems,
)
from edulint.fast.rules import plan_ruff
from edulint.linters import Linter

needs_ruff = pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not installed")


@pytest.fixture(autouse=True)
def _restore_config_module():
    yield
    config_cache.uninstall()


@pytest.fixture
def plan(tmp_path):
    path = tmp_path / "x.py"
    path.write_text("x = 1\n")
    config, _ = get_config_one(str(path), [])
    return plan_ruff(config), config


def diag(code, message, row, col, end_row=None, end_col=None):
    return {
        "code": code,
        "message": message,
        "location": {"row": row, "column": col},
        "end_location": {"row": end_row or row, "column": end_col or col + 1},
    }


def convert(plan_and_config, raw, text=""):
    plan, config = plan_and_config
    return ruff_to_problems(raw, plan, "x.py", config.enablers, text)


def test_flake8_codes_keep_one_based_columns(plan):
    (problem,) = convert(plan, [diag("F401", "`os` imported but unused", 3, 8, 3, 10)])
    assert problem.source == Linter.FLAKE8
    assert (problem.line, problem.column, problem.end_column) == (3, 8, 10)
    assert problem.code == "F401"
    assert problem.text == "'os' imported but unused"  # pyflakes-style quoting
    assert problem.enabled_by == "default"


def test_pylint_messages_use_zero_based_columns(plan):
    (problem,) = convert(plan, [diag("PLE0101", "Explicit return in `__init__`", 4, 9, 4, 17)])
    assert problem.source == Linter.PYLINT
    assert (problem.code, problem.symbol) == ("E0101", "return-in-init")
    assert (problem.column, problem.end_column) == (8, 16)


def test_one_diagnostic_can_be_several_messages(plan):
    problems = convert(plan, [diag("F403", "`from os import *` used", 1, 1)])
    assert {(p.source, p.code) for p in problems} == {
        (Linter.FLAKE8, "F403"),
        (Linter.PYLINT, "W0401"),
    }


def test_unselected_ruff_code_is_ignored(plan):
    assert convert(plan, [diag("D100", "Missing docstring", 1, 1)]) == []


def test_only_first_syntax_error_is_kept_and_nothing_else(plan):
    raw = [
        diag("F401", "`os` imported but unused", 1, 1),
        diag("invalid-syntax", "Expected ':'", 2, 8),
        {**diag(None, "Expected an expression", 3, 1)},
    ]
    (problem,) = convert(plan, raw)
    assert problem.code == "E999"
    assert problem.text == "SyntaxError: Expected ':'"
    assert problem.line == 2


def test_f811_is_split_by_kind_of_redefinition(plan):
    text = "import os\nimport os\n\n\ndef f():\n    pass\n\n\ndef f():\n    pass\n"
    reimport = diag("F811", "Redefinition of unused `os` from line 1", 2, 8)
    redefined = diag("F811", "Redefinition of unused `f` from line 5", 9, 5)
    codes = lambda raw: sorted(p.code for p in convert(plan, raw, text))  # noqa: E731
    assert codes([reimport]) == ["F811", "W0404"]
    assert codes([redefined]) == ["E0102", "F811"]


def test_no_else_return_is_reported_on_the_opening_if(plan):
    text = "def f(a):\n    if a:\n        return 1\n    else:\n        return 2\n"
    problems = convert(plan, [diag("RET505", "Unnecessary `else`", 4, 5, 4, 9)], text)
    (problem,) = problems
    assert (problem.code, problem.line, problem.column) == ("R1705", 2, 4)


def test_redefined_builtin_is_reported_once_per_scope(plan):
    text = "def f():\n    sum = 0\n    sum = sum + 1\n\n\ndef g():\n    sum = 1\n"
    raw = [
        diag("A001", "Variable `sum` is shadowing a Python builtin", 2, 5),
        diag("A001", "Variable `sum` is shadowing a Python builtin", 3, 5),
        diag("A001", "Variable `sum` is shadowing a Python builtin", 7, 5),
    ]
    problems = [p for p in convert(plan, raw, text) if p.code == "W0622"]
    assert [p.line for p in problems] == [2, 7]
    assert problems[0].text == "Redefining built-in 'sum'"


def test_find_ruff_reports_missing_executable():
    with pytest.raises(RuffNotFoundError, match="not found"):
        find_ruff("definitely-not-a-ruff-executable")


def test_ruff_args(plan):
    args = ruff_args(plan[0], "a.py")
    assert args[-3:-1] != []
    assert "--preview" in args
    assert args[args.index("--line-length") + 1] == "79"
    assert args[args.index("--stdin-filename") + 1] == "a.py"
    assert args[-1] == "-"


@needs_ruff
def test_lint_buffer_end_to_end(tmp_path):
    path = tmp_path / "x.py"
    text = "import os\n\n\ndef f(a=[]):\n    if a:\n        return 1\n    else:\n        return 2\n"
    problems = lint_buffer(str(path), text)  # the file does not even need to exist
    assert [(p.line, p.code) for p in problems] == [
        (1, "F401"),
        (4, "W0102"),
        (5, "R1705"),
    ]


@needs_ruff
def test_lint_buffer_honours_in_file_config_of_the_buffer(tmp_path):
    path = tmp_path / "x.py"
    path.write_text("x = 1\n")  # on disk: no options
    text = "# edulint: flake8=--max-line-length=20\nx = 'a' * 30 + 'b' * 30\n"
    assert [(p.line, p.code) for p in lint_buffer(str(path), text)] == [(1, "E501"), (2, "E501")]
    assert lint_buffer(str(path), "x = 'a' * 30 + 'b' * 30\n") == []


@needs_ruff
def test_lint_buffer_e501_matches_pycodestyle(tmp_path):
    long_url = "# https://example.com/" + "a" * 90
    text = f"{long_url}\nx = 1  # {'y' * 90}\ny = 1  # type: ignore" + " " * 0 + "\n"
    problems = lint_buffer(str(tmp_path / "x.py"), text)
    assert [(p.line, p.code, p.column) for p in problems] == [(2, "E501", 80)]
