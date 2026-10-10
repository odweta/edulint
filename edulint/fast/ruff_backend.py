"""
Lints the text of a buffer with Ruff (``ruff check --output-format json
--stdin-filename <path> -``) and converts the result to EduLint problems.

Ruff is only invoked as a subprocess; no temporary files, no network.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from edulint.config.config import ImmutableConfig, get_cmd_args, get_config_many
from edulint.config.language_translations import LangTranslations
from edulint.fast import config_cache
from edulint.fast.rules import RuffPlan, RuffTarget, SYNTAX_ERROR_RUFF_CODE, plan_ruff
from edulint.linters import Linter
from edulint.linting.linting import apply_overrides, apply_tweaks, get_proper_path, translate
from edulint.linting.overrides import get_overriders
from edulint.linting.problem import Problem
from edulint.linting.tweakers import get_tweakers
from edulint.options import Option

INSTALL_HINT = "install it with `pip install ruff` or set the `ruff_executable` option"


class RuffError(RuntimeError):
    pass


class RuffNotFoundError(RuffError):
    pass


def find_ruff(executable: Optional[str] = None) -> List[str]:
    """Returns the command prefix to run Ruff; raises RuffNotFoundError if there is none."""
    if executable:
        found = shutil.which(executable)
        if found is None:
            raise RuffNotFoundError(f"Ruff executable '{executable}' not found; {INSTALL_HINT}")
        return [found]

    found = shutil.which("ruff")
    if found is None:
        scripts = os.path.join(os.path.dirname(sys.executable), "ruff")
        found = shutil.which(scripts)
    if found is not None:
        return [found]

    import importlib.util

    if importlib.util.find_spec("ruff") is not None:
        return [sys.executable, "-m", "ruff"]
    raise RuffNotFoundError(f"Ruff not found; {INSTALL_HINT}")


def ruff_args(plan: RuffPlan, path: str) -> List[str]:
    args = [
        "check",
        "--isolated",
        "--no-cache",
        "--output-format",
        "json",
        "--exit-zero",
        "--line-length",
        str(plan.line_length),
        "--stdin-filename",
        path,
    ]
    if plan.preview:
        args.append("--preview")
    # pyflakes only exempts `_` from unused-variable reports
    args += ["--config", 'lint.dummy-variable-rgx = "^_$"']
    if plan.max_complexity is not None:
        args += ["--config", f"lint.mccabe.max-complexity = {plan.max_complexity}"]
    # always selecting something keeps Ruff from running its (huge) default rule set
    args += ["--select", ",".join(plan.select) if plan.select else "E999"]
    args.append("-")
    return args


def run_ruff(
    plan: RuffPlan, path: str, text: str, executable: Optional[str] = None, timeout: float = 10.0
) -> List[Dict[str, Any]]:
    """Runs Ruff on ``text`` and returns the raw JSON diagnostics."""
    command = find_ruff(executable) + ruff_args(plan, path)
    try:
        completed = subprocess.run(
            command,
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RuffError(f"Ruff timed out after {timeout}s") from e
    except OSError as e:
        raise RuffNotFoundError(f"cannot run Ruff ({e}); {INSTALL_HINT}") from e

    out = completed.stdout.decode("utf-8", errors="replace").strip()
    if completed.returncode not in (0, 1) or not out:
        err = completed.stderr.decode("utf-8", errors="replace").strip()
        if completed.returncode in (0, 1) and not out:
            return []
        raise RuffError(f"Ruff failed with code {completed.returncode}: {err}")
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise RuffError(f"cannot parse Ruff output: {e}") from e


# %% conversion

_BACKTICKS = re.compile(r"`([^`]*)`")
_TRUE_FALSE = re.compile(r"`(True|False)`")


def _reword(target_linter: Linter, code: str, text: str) -> str:
    """Makes Ruff's text look like what the emulated linter says, where tweakers rely on it."""
    if target_linter == Linter.FLAKE8 and code.startswith("F"):
        return _BACKTICKS.sub(r"'\1'", text)
    if target_linter == Linter.FLAKE8 and code == "E712":
        m = _TRUE_FALSE.search(text)
        if m:
            return f"comparison to {m.group(1)} should be 'if cond is {m.group(1)}:' or 'if cond:'"
    if target_linter == Linter.PYLINT and code == "W0622":
        m = _BACKTICKS.search(text)
        if m:
            return f"Redefining built-in '{m.group(1)}'"
    return text


_FROM_LINE = re.compile(r"from line (\d+)")
_IMPORT_LINE = re.compile(r"\s*(import|from)\s")
_DEF_LINE = re.compile(r"\s*(async\s+def|def|class)\s")


def _applies(target: RuffTarget, diag: Dict[str, Any], lines: Sequence[str]) -> bool:
    """F811 stands for several pylint messages; pick the ones that fit the code at hand."""
    if diag.get("code") != "F811" or target.linter != Linter.PYLINT:
        return True

    def line_at(row: int) -> str:
        return lines[row - 1] if 0 < row <= len(lines) else ""

    if target.code == "W0404":  # reimported: the earlier binding was an import
        m = _FROM_LINE.search(diag["message"])
        return m is not None and _IMPORT_LINE.match(line_at(int(m.group(1)))) is not None
    if target.code == "E0102":  # function-redefined: a def or class is redefined
        return _DEF_LINE.match(line_at(diag["location"]["row"])) is not None
    return True


_NO_ELSE_CODES = {"R1705", "R1720", "R1723", "R1724"}
_DEF_START = re.compile(r"(\s*)(async\s+def|def|class)\s")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _chain_start_row(lines: Sequence[str], row: int) -> Optional[int]:
    """Row of the ``if`` that opens the if/elif/else chain containing the else/elif at ``row``."""
    if not 0 < row <= len(lines):
        return None
    indent = _indent(lines[row - 1])
    for i in range(row - 2, -1, -1):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or _indent(line) > indent:
            continue
        if _indent(line) < indent:
            return None
        if re.match(r"if[\s(]", stripped):
            return i + 1
        if not re.match(r"(elif|else)\b", stripped):
            return None
    return None


def _scope_row(lines: Sequence[str], row: int) -> int:
    """Row of the enclosing def/class of ``row`` (0 for module level)."""
    if not 0 < row <= len(lines):
        return 0
    indent = _indent(lines[row - 1])
    for i in range(row - 2, -1, -1):
        line = lines[i]
        if line.strip() and _indent(line) < indent and _DEF_START.match(line):
            return i + 1
    return 0


def ruff_to_problems(
    raw: Sequence[Dict[str, Any]],
    plan: RuffPlan,
    path: str,
    enablers: Dict[str, str],
    text: str = "",
) -> List[Problem]:
    """
    Converts Ruff's JSON diagnostics. One diagnostic yields one problem per
    EduLint message it stands for. Columns follow the emulated linter: 1-based
    for flake8 codes, 0-based for pylint messages.
    """
    proper_path = get_proper_path(path)
    lines = text.splitlines()
    problems: List[Problem] = []

    syntax_errors = [d for d in raw if d.get("code") in (None, SYNTAX_ERROR_RUFF_CODE)]
    if syntax_errors:
        # like flake8, report only the (first) syntax error of a broken file
        raw = [{**syntax_errors[0], "code": SYNTAX_ERROR_RUFF_CODE}]

    seen_builtins = set()
    for diag in raw:
        ruff_code = diag["code"]
        targets = plan.targets.get(ruff_code, ())
        loc, end = diag["location"], diag.get("end_location")
        for target in targets:
            if not _applies(target, diag, lines):
                continue
            row, column, end_row, end_column = loc["row"], loc["column"], None, None
            if end:
                end_row, end_column = end["row"], end["column"]
            shift = 0 if target.linter == Linter.FLAKE8 else 1
            text = diag["message"]
            if ruff_code == SYNTAX_ERROR_RUFF_CODE:
                text = f"SyntaxError: {text}"

            if target.code in _NO_ELSE_CODES:
                # pylint reports on the ``if`` opening the chain, Ruff on the else/elif
                start = _chain_start_row(lines, row)
                if start is not None:
                    row, column = start, _indent(lines[start - 1]) + 1
                    end_row, end_column = start, len(lines[start - 1]) + 1
            elif target.code == "E0101":
                # pylint reports on the __init__ definition, Ruff on the return
                scope = _scope_row(lines, row)
                if scope:
                    row, column = scope, _indent(lines[scope - 1]) + 1
                    end_row, end_column = scope, len(lines[scope - 1]) + 1
            elif target.code == "W0622":
                # pylint reports a builtin only where it is first defined in a scope
                match = _BACKTICKS.search(text)
                key = (match.group(1) if match else text, _scope_row(lines, row))
                if key in seen_builtins:
                    continue
                seen_builtins.add(key)

            problems.append(
                Problem(
                    target.linter,
                    enablers.get(target.code)
                    or (enablers.get(target.symbol) if target.symbol else None),
                    proper_path,
                    row,
                    column - shift,
                    target.code,
                    _reword(target.linter, target.code, text),
                    end_row,
                    end_column - shift if end_column is not None else None,
                    target.symbol,
                )
            )
    return problems


_NOQA = re.compile(r"#\s*noqa(?::[\s]?(?P<codes>[A-Z][0-9]+(?:[,\s]+)?)+)?", re.IGNORECASE)


def line_length_problems(
    text: str, plan: RuffPlan, path: str, enablers: Dict[str, str]
) -> List[Problem]:
    """E501 the way pycodestyle computes it (Ruff's rule exempts more lines)."""
    if "E501" not in plan.own_flake8:
        return []
    limit = plan.line_length
    proper_path = get_proper_path(path)
    result = []
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.rstrip()
        length = len(line)
        if length <= limit:
            continue
        noqa = _NOQA.search(line)
        if noqa and (noqa.group("codes") is None or "E501" in line[noqa.start() :].upper()):
            continue
        chunks = line.split()
        if len(chunks) == 2 and chunks[0] == "#" and length - len(chunks[-1]) < limit - 7:
            continue  # a long URL in a comment
        result.append(
            Problem(
                Linter.FLAKE8,
                enablers.get("E501"),
                proper_path,
                number,
                limit + 1,
                "E501",
                f"line too long ({length} > {limit} characters)",
            )
        )
    return result


def finish(
    problems: List[Problem], config: ImmutableConfig, lang_translations: LangTranslations
) -> List[Problem]:
    """Applies overrides, tweaks and translations like ``lint_many`` does."""
    problems = apply_overrides(problems, get_overriders())
    tweakers = get_tweakers()
    result: List[Problem] = []
    for problem in problems:
        original = problem.text
        try:
            result.extend(apply_tweaks([problem], tweakers, config))
        except AssertionError:  # Ruff's text did not match the pattern the tweaker expects
            problem.text = original
            result.append(problem)
    result = [translate(lang_translations, problem) for problem in result]
    result.sort(key=lambda p: (p.line, p.column))
    return result


def get_buffer_config(
    path: str, text: Optional[str], options: Sequence[str]
) -> Optional[Tuple[ImmutableConfig, LangTranslations]]:
    """Resolves the configuration for a buffer (in-file options come from ``text``)."""
    with config_cache.buffer_override(path, text):
        configs = get_config_many([path], get_cmd_args(list(options)))
    if not configs:
        return None
    _paths, config, lang_translations = configs[0]
    return config, lang_translations


def lint_buffer(
    path: str,
    text: str,
    options: Sequence[str] = (),
    ruff_executable: Optional[str] = None,
    timeout: float = 10.0,
) -> List[Problem]:
    """Fast tier: lints ``text`` as if it was the content of ``path``."""
    resolved = get_buffer_config(path, text, options)
    if resolved is None:
        return []
    config, lang_translations = resolved
    plan = plan_ruff(config)
    raw = run_ruff(plan, path, text, ruff_executable, timeout)
    problems = ruff_to_problems(raw, plan, path, config.enablers, text)
    if not any(p.code == "E999" for p in problems):
        problems += line_length_problems(text, plan, path, config.enablers)
    return finish(problems, config, lang_translations)
