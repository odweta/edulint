"""Combining the fast (Ruff) and slow (EduLint worker) tiers."""

from typing import Callable, List, Optional, Sequence, Tuple

from edulint.linting.linting import apply_overrides
from edulint.linting.overrides import get_overriders
from edulint.linting.problem import Problem


def merge(
    fast: Sequence[Problem], slow: Sequence[Problem], fast_tool: str = "ruff"
) -> List[Tuple[Problem, str]]:
    """
    Merges the problems of both tiers, tagging each with the tier it came from.
    EduLint's overrides are applied across tiers (an override may need a
    problem found by the other tier) and duplicates (same path, line and code)
    are dropped.
    """
    tagged = [(p, fast_tool) for p in fast] + [(p, "worker") for p in slow]
    kept_ids = {id(p) for p in apply_overrides([p for p, _t in tagged], get_overriders())}
    seen = set()
    result = []
    for problem, tool in tagged:
        key = (problem.path, problem.line, problem.code)
        if id(problem) in kept_ids and key not in seen:
            seen.add(key)
            result.append((problem, tool))
    result.sort(key=lambda pt: (pt[0].line, pt[0].column))
    return result


def lint_hybrid(
    path: str,
    text: str,
    options: Sequence[str] = (),
    ruff_executable: Optional[str] = None,
    slow: Optional[Callable[..., List[Problem]]] = None,
) -> List[Problem]:
    """
    Synchronous hybrid lint, mostly for tests and benchmarks: Ruff first, then
    ``slow(path, text, options, restricted=True)`` (e.g. ``LintWorker().lint`` or
    :func:`edulint.fast.worker.lint_text`).
    """
    from edulint.fast.ruff_backend import lint_buffer
    from edulint.fast.worker import lint_text

    fast = lint_buffer(path, text, options, ruff_executable)
    slow_problems = (slow or lint_text)(path, text, options, restricted=True)
    return [p for p, _tool in merge(fast, slow_problems)]
