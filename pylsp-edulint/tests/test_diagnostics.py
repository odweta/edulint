from edulint.linters import Linter
from edulint.linting.problem import Problem

from pylsp_edulint.diagnostics import (
    problem_at,
    problem_range,
    problem_to_diagnostic,
    utf16_offset,
)

LINES = ["import os", "x = 1  # héllo", "def f(): return 1"]


def problem(source, line, column, end_line=None, end_column=None, enabled_by="default"):
    return Problem(source, enabled_by, "a.py", line, column, "X1", "text", end_line, end_column)


def test_flake8_columns_are_one_based():
    rng = problem_range(problem(Linter.FLAKE8, 1, 8, 1, 10), LINES)
    assert rng == {
        "start": {"line": 0, "character": 7},
        "end": {"line": 0, "character": 9},
    }


def test_pylint_columns_are_zero_based():
    rng = problem_range(problem(Linter.PYLINT, 3, 4, 3, 8), LINES)
    assert rng["start"] == {"line": 2, "character": 4}
    assert rng["end"] == {"line": 2, "character": 8}


def test_missing_end_falls_back_to_end_of_line():
    rng = problem_range(problem(Linter.FLAKE8, 2, 5), LINES)
    assert rng["start"] == {"line": 1, "character": 4}
    assert rng["end"] == {"line": 1, "character": len(LINES[1])}


def test_empty_or_inverted_end_falls_back_to_end_of_line():
    rng = problem_range(problem(Linter.PYLINT, 1, 4, 1, 4), LINES)
    assert rng["end"]["character"] == len("import os")


def test_out_of_range_positions_are_clamped():
    rng = problem_range(problem(Linter.PYLINT, 99, 99), LINES)
    assert rng["start"]["line"] == 2
    assert rng["start"]["character"] <= len(LINES[2])


def test_utf16_offsets():
    assert utf16_offset("a😀b", 2) == 3  # the emoji is two UTF-16 code units
    assert utf16_offset("abc", 99) == 3


def test_diagnostic_fields():
    d = problem_to_diagnostic(problem(Linter.FLAKE8, 1, 1, 1, 7), LINES, "ruff")
    assert d["source"] == "edulint/ruff"
    assert d["code"] == "X1"
    assert d["severity"] == 2
    assert d["message"] == "text [default]"
    d = problem_to_diagnostic(problem(Linter.FLAKE8, 1, 1, enabled_by=None), LINES, "worker")
    assert d["message"] == "text"
    assert d["source"] == "edulint/worker"


def test_problem_at_position():
    problems = [problem(Linter.PYLINT, 1, 0, 1, 6), problem(Linter.PYLINT, 3, 0, 3, 3)]
    text = "\n".join(LINES)
    assert problem_at(problems, 0, 3, text) is problems[0]
    assert problem_at(problems, 2, 1, text) is problems[1]
    assert problem_at(problems, 1, 1, text) is None
