"""Conversion of EduLint problems to LSP diagnostics (no pylsp imports; easy to test)."""

from typing import Any, Dict, List, Optional, Sequence

from edulint.linters import Linter
from edulint.linting.problem import Problem

WARNING = 2


def one_based_columns(problem: Problem) -> bool:
    """flake8 (and Ruff acting as flake8) report 1-based columns, pylint 0-based."""
    return problem.source == Linter.FLAKE8


def utf16_offset(line: str, column: int) -> int:
    """Converts a character offset in ``line`` to an LSP (UTF-16) offset."""
    column = max(0, min(column, len(line)))
    return len(line[:column].encode("utf-16-le")) // 2


def problem_range(problem: Problem, lines: Sequence[str]) -> Dict[str, Dict[str, int]]:
    """0-based LSP range; falls back to the rest of the line when there is no usable end."""
    shift = 1 if one_based_columns(problem) else 0
    last = max(len(lines) - 1, 0)

    start_line = min(max(problem.line - 1, 0), last)
    text = lines[start_line] if lines else ""
    start_col = max(problem.column - shift, 0)

    end_line, end_col = None, None
    if problem.end_line is not None and problem.end_column is not None:
        end_line = min(max(problem.end_line - 1, 0), last)
        end_col = max(problem.end_column - shift, 0)
        if (end_line, end_col) <= (start_line, start_col):
            end_line = end_col = None

    if end_line is None:
        end_line, end_col = start_line, len(text)
        start_col = min(start_col, len(text))

    end_text = lines[end_line] if lines else ""
    return {
        "start": {"line": start_line, "character": utf16_offset(text, start_col)},
        "end": {"line": end_line, "character": utf16_offset(end_text, end_col or 0)},
    }


def problem_message(problem: Problem) -> str:
    enabler = f" [{problem.enabled_by}]" if problem.enabled_by is not None else ""
    return f"{problem.text}{enabler}"


def problem_to_diagnostic(
    problem: Problem, lines: Sequence[str], tool: str = "edulint"
) -> Dict[str, Any]:
    """``tool`` is e.g. ``ruff`` or ``worker``; the diagnostic source becomes ``edulint/<tool>``."""
    return {
        "source": f"edulint/{tool}" if tool != "edulint" else "edulint",
        "range": problem_range(problem, lines),
        "message": problem_message(problem),
        "code": problem.code,
        "severity": WARNING,
    }


def problems_to_diagnostics(
    problems: Sequence[Problem], text: str, tool: str = "edulint"
) -> List[Dict[str, Any]]:
    lines = text.splitlines()
    return [problem_to_diagnostic(p, lines, tool) for p in problems]


def problem_at(
    problems: Sequence[Problem], line0: int, character: int, text: str
) -> Optional[Problem]:
    """First problem whose range contains the (0-based) position."""
    lines = text.splitlines()
    for problem in problems:
        rng = problem_range(problem, lines)
        start, end = rng["start"], rng["end"]
        if (start["line"], start["character"]) <= (line0, character) <= (end["line"], end["character"]):
            return problem
    return None
