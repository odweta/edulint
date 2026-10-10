"""
Mapping between the checks EduLint enables (flake8 codes and pylint messages)
and Ruff rules.

Everything here is plain data plus a few pure functions, so importing it is
cheap. The tables are verified against the installed Ruff and Pylint in
``tests/test_fast_rules.py``.
"""

from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from edulint.config.config import ImmutableConfig
from edulint.linters import Linter
from edulint.options import Option

SYNTAX_ERROR_RUFF_CODE = "invalid-syntax"
"""Ruff reports syntax errors with this pseudo-code; flake8 reports them as E999."""


# %% flake8 -> Ruff

_SAME_CODE = """
E101 E111 E112 E113 E114 E115 E116 E117 E201 E202 E203 E211 E221 E222 E223 E224
E225 E226 E227 E228 E231 E241 E242 E251 E252 E261 E262 E265 E266 E271 E272 E273
E274 E275 E301 E302 E303 E304 E305 E306 E401 E402 E501 E502 E701 E702 E703 E711
E712 E713 E714 E721 E722 E731 E741 E742 E743 E902
F401 F402 F404 F405 F403 F406 F407 F501 F502 F503 F504 F505 F506 F507 F508 F509
F521 F522 F523 F524 F525 F541 F601 F602 F621 F622 F631 F632 F633 F634 F701 F702
F704 F706 F707 F722 F811 F821 F822 F823 F841 F901
W191 W291 W292 W293 W391 W505 W605
C901
"""

FLAKE8_TO_RUFF: Dict[str, str] = {code: code for code in _SAME_CODE.split()}
FLAKE8_TO_RUFF["E999"] = SYNTAX_ERROR_RUFF_CODE

FLAKE8_UNMAPPED: Dict[str, str] = {
    **{
        code: "continuation-line indentation (pycodestyle E12x/E13x) is not implemented in Ruff"
        for code in "E121 E122 E123 E124 E125 E126 E127 E128 E129 E131 E133".split()
    },
    "E704": "not implemented in Ruff",
    "E901": "syntax errors are reported as E999",
    "F703": "removed from pyflakes; not implemented in Ruff",
    "F705": "not implemented in Ruff",
    "F721": "doctest checking is not implemented in Ruff",
    "F723": "type comments are not supported by Ruff",
    "F831": "duplicate argument is reported by Ruff as a syntax error (E999)",
    "W503": "not implemented in Ruff",
    "W504": "not implemented in Ruff",
    **{
        code: "python 2 era check removed from pycodestyle; not implemented in Ruff"
        for code in "W601 W602 W603 W604 W606".split()
    },
}

FLAKE8_CHECKED_IN_PYTHON: FrozenSet[str] = frozenset({"E501"})
"""
Codes that are in ``FLAKE8_TO_RUFF`` but are computed by EduLint itself, because Ruff's
rule differs from pycodestyle's (Ruff skips lines ending in a long URL or pragma comment).
"""

FLAKE8_PREVIEW_ONLY: FrozenSet[str] = frozenset(
    """
E111 E112 E113 E114 E115 E116 E117 E201 E202 E203 E211 E221 E222 E223 E224
E225 E226 E227 E228 E231 E241 E242 E251 E252 E261 E262 E265 E266 E271 E272
E273 E274 E275 E301 E302 E303 E304 E305 E306 E502 W391
""".split()
)
"""Ruff rules that require ``--preview`` (checked against Ruff by the tests)."""

FLAKE8_DEFAULT_SELECT = ("E", "F", "W", "C90")
FLAKE8_DEFAULT_IGNORE = ("E121", "E123", "E126", "E226", "E24", "E704", "W503", "W504")
FLAKE8_DEFAULT_MAX_LINE_LENGTH = 79


# %% pylint -> Ruff


@dataclass(frozen=True)
class PylintEquivalent:
    symbol: str
    msgid: str
    ruff: Tuple[str, ...]
    exact: bool = True
    """False when Ruff's rule is only an approximation of the pylint check."""
    note: str = ""


PYLINT_TO_RUFF: Tuple[PylintEquivalent, ...] = (
    PylintEquivalent("comparison-with-itself", "R0124", ("PLR0124",)),
    PylintEquivalent("dangerous-default-value", "W0102", ("B006",), False, "pylint also flags some calls"),
    PylintEquivalent("function-redefined", "E0102", ("F811",), False, "F811 also covers imports/variables"),
    PylintEquivalent("import-outside-toplevel", "C0415", ("PLC0415",)),
    PylintEquivalent("no-else-break", "R1723", ("RET508",)),
    PylintEquivalent("no-else-continue", "R1724", ("RET507",)),
    PylintEquivalent("no-else-raise", "R1720", ("RET506",)),
    PylintEquivalent("no-else-return", "R1705", ("RET505",)),
    PylintEquivalent("non-ascii-name", "C2401", ("PLC2401",)),
    PylintEquivalent("not-in-loop", "E0103", ("F701", "F702"), True, "break/continue outside loop"),
    PylintEquivalent("pointless-statement", "W0104", ("B018", "B015"), False, "B018 is broader; B015 covers comparisons"),
    PylintEquivalent("redefined-argument-from-local", "R1704", ("PLR1704",)),
    PylintEquivalent("redefined-builtin", "W0622", ("A001", "A002"), False, "no class attributes"),
    PylintEquivalent("return-in-init", "E0101", ("PLE0101",)),
    PylintEquivalent("self-assigning-variable", "W0127", ("PLW0127",)),
    PylintEquivalent("trailing-comma-tuple", "R1707", ("COM818",)),
    PylintEquivalent("unnecessary-dict-index-lookup", "R1733", ("PLR1733",)),
    PylintEquivalent("unnecessary-pass", "W0107", ("PIE790",)),
    PylintEquivalent("wildcard-import", "W0401", ("F403",)),
    PylintEquivalent("consider-using-from-import", "R0402", ("PLR0402",)),
    PylintEquivalent("reimported", "W0404", ("F811",), False, "F811 also covers redefinitions"),
    PylintEquivalent("unused-import", "W0611", ("F401",)),
    PylintEquivalent("unused-variable", "W0612", ("F841",)),
    PylintEquivalent("undefined-variable", "E0602", ("F821",)),
    PylintEquivalent("global-statement", "W0603", ("PLW0603",)),
    PylintEquivalent("bare-except", "W0702", ("E722",)),
    PylintEquivalent("consider-using-in", "R1714", ("PLR1714",)),
)

PYLINT_UNMAPPED_NOTES: Dict[str, str] = {
    "no-method-argument": "N805 checks the name of the first argument, not its absence",
    "no-self-argument": "N805 checks the name, pylint checks the absence of an argument",
    "unreachable": "Ruff has no unreachable-code rule",
    "used-before-assignment": "no equivalent for pylint's control-flow based check",
    "unnecessary-negation": "SIM201/SIM202/E713/E714 only cover subsets",
    "disallowed-name": "EduLint-specific configuration of disallowed names",
    "invalid-name": "EduLint-specific naming checker",
    "use-augmented-assign": "EduLint's R6609 has different semantics from PLR6104 (preview)",
}

_BY_NAME: Dict[str, PylintEquivalent] = {}
for _eq in PYLINT_TO_RUFF:
    _BY_NAME[_eq.symbol] = _eq
    _BY_NAME[_eq.msgid] = _eq


def pylint_equivalent(name: str) -> Optional[PylintEquivalent]:
    """Looks up a pylint message by symbol or message id."""
    return _BY_NAME.get(name)


# %% selection from the configuration


def _opt_values(args: Iterable[str], name: str) -> Optional[List[str]]:
    result: Optional[List[str]] = None
    prefix = name + "="
    for arg in args:
        if arg.startswith(prefix):
            result = (result or []) + [v.strip() for v in arg[len(prefix) :].split(",") if v.strip()]
    return result


def _last_opt(args: Iterable[str], name: str) -> Optional[str]:
    result = None
    prefix = name + "="
    for arg in args:
        if arg.startswith(prefix):
            result = arg[len(prefix) :].strip()
    return result


def _longest_prefix(code: str, prefixes: Iterable[str]) -> int:
    return max((len(p) for p in prefixes if code.startswith(p)), default=-1)


@dataclass(frozen=True)
class Flake8Plan:
    selected: FrozenSet[str]
    """flake8 codes that are enabled and that Ruff can check."""
    unmapped: FrozenSet[str]
    """flake8 codes that are enabled but that Ruff cannot check."""
    line_length: int
    max_complexity: Optional[int]


def plan_flake8(flake8_args: Iterable[str]) -> Flake8Plan:
    """Resolves flake8 ``--select``/``--ignore`` options like flake8 does."""
    args = list(flake8_args)
    explicit_select = _opt_values(args, "--select")
    select = list(explicit_select) if explicit_select is not None else list(FLAKE8_DEFAULT_SELECT)
    select += _opt_values(args, "--extend-select") or []

    explicit_ignore = _opt_values(args, "--ignore")
    if explicit_ignore is not None:
        ignore = list(explicit_ignore)
    elif explicit_select is not None:
        ignore = []
    else:
        ignore = list(FLAKE8_DEFAULT_IGNORE)
    ignore += _opt_values(args, "--extend-ignore") or []

    max_line = _last_opt(args, "--max-line-length")
    max_complexity = _last_opt(args, "--max-complexity")

    def to_int(val: Optional[str], default: Optional[int]) -> Optional[int]:
        try:
            return int(val) if val is not None else default
        except ValueError:
            return default

    complexity = to_int(max_complexity, None)
    if complexity is not None and complexity < 0:
        complexity = None

    selected: Set[str] = set()
    unmapped: Set[str] = set()
    for code in list(FLAKE8_TO_RUFF) + list(FLAKE8_UNMAPPED):
        sel, ign = _longest_prefix(code, select), _longest_prefix(code, ignore)
        if sel < 0 or ign >= sel:
            continue
        if code == "C901" and complexity is None:
            continue
        (selected if code in FLAKE8_TO_RUFF else unmapped).add(code)

    return Flake8Plan(
        frozenset(selected),
        frozenset(unmapped),
        to_int(max_line, FLAKE8_DEFAULT_MAX_LINE_LENGTH) or FLAKE8_DEFAULT_MAX_LINE_LENGTH,
        complexity,
    )


def enabled_pylint_messages(pylint_args: Iterable[str]) -> Set[str]:
    """
    Names (symbols or ids, as written in the arguments) of messages enabled by
    ``--enable``/``--disable`` options, evaluated in order. Only explicitly
    named messages are returned (plus ``all`` when everything is enabled).
    """
    enabled: Set[str] = set()
    for arg in pylint_args:
        if arg.startswith("--enable="):
            enabled |= {v.strip() for v in arg[len("--enable=") :].split(",") if v.strip()}
        elif arg.startswith("--disable="):
            for v in (v.strip() for v in arg[len("--disable=") :].split(",")):
                if v == "all":
                    enabled.clear()
                else:
                    enabled.discard(v)
                    eq = pylint_equivalent(v)
                    if eq is not None:
                        enabled.discard(eq.symbol)
                        enabled.discard(eq.msgid)
    return enabled


def pylint_targets(pylint_args: Iterable[str]) -> List[PylintEquivalent]:
    """Pylint messages with a Ruff equivalent that are enabled by the options."""
    enabled = enabled_pylint_messages(pylint_args)
    return [eq for eq in PYLINT_TO_RUFF if eq.symbol in enabled or eq.msgid in enabled]


@dataclass(frozen=True)
class RuffTarget:
    """An EduLint message a Ruff diagnostic is reported as."""

    linter: Linter
    code: str
    symbol: Optional[str] = None


@dataclass(frozen=True)
class RuffPlan:
    targets: Dict[str, Tuple[RuffTarget, ...]]
    """Ruff code -> EduLint messages that the diagnostic should be reported as."""
    select: Tuple[str, ...]
    """Ruff codes to pass to ``--select`` (excluding the syntax-error pseudo-code)."""
    preview: bool
    line_length: int
    max_complexity: Optional[int]
    unmapped_flake8: FrozenSet[str]
    own_flake8: FrozenSet[str] = frozenset()
    """flake8 codes in ``FLAKE8_CHECKED_IN_PYTHON`` that are enabled."""


def plan_ruff(config: ImmutableConfig) -> RuffPlan:
    """Decides which Ruff rules to run, and how to report them, for a configuration."""
    targets: Dict[str, List[RuffTarget]] = {}
    flake8_plan = plan_flake8(config[Option.FLAKE8])
    preview = False

    if config[Option.NO_FLAKE8]:
        flake8_codes: FrozenSet[str] = frozenset()
        unmapped_flake8: FrozenSet[str] = frozenset()
    else:
        flake8_codes, unmapped_flake8 = flake8_plan.selected, flake8_plan.unmapped

    own_flake8 = flake8_codes & FLAKE8_CHECKED_IN_PYTHON
    for code in sorted(flake8_codes - own_flake8):
        ruff_code = FLAKE8_TO_RUFF[code]
        targets.setdefault(ruff_code, []).append(RuffTarget(Linter.FLAKE8, code))
        preview = preview or code in FLAKE8_PREVIEW_ONLY

    for eq in pylint_targets(config[Option.PYLINT]):
        for ruff_code in eq.ruff:
            targets.setdefault(ruff_code, []).append(RuffTarget(Linter.PYLINT, eq.msgid, eq.symbol))

    select = tuple(sorted(c for c in targets if c != SYNTAX_ERROR_RUFF_CODE))
    return RuffPlan(
        {k: tuple(v) for k, v in targets.items()},
        select,
        preview,
        flake8_plan.line_length,
        flake8_plan.max_complexity,
        unmapped_flake8,
        own_flake8,
    )


# %% restricting the slow tier


def _covered_by_ruff(name: str) -> bool:
    return name in _BY_NAME


def restrict_config_to_uncovered(config: ImmutableConfig) -> ImmutableConfig:
    """
    Returns a configuration for the slow tier of the hybrid mode: flake8 is
    off and pylint only runs messages Ruff does not cover (EduLint's custom
    checkers and pylint messages without an equivalent).
    """
    from edulint.config.arg import ImmutableArg

    def restrict_pylint(args: Tuple[str, ...]) -> Tuple[str, ...]:
        result: List[str] = []
        for arg in args:
            if arg.startswith("--enable="):
                kept = [
                    v
                    for v in (v.strip() for v in arg[len("--enable=") :].split(","))
                    if v and not _covered_by_ruff(v)
                ]
                if kept:
                    result.append("--enable=" + ",".join(kept))
            else:
                result.append(arg)
        return tuple(result)

    new_args = []
    for arg in config.config:
        if arg.option == Option.NO_FLAKE8:
            new_args.append(ImmutableArg(Option.NO_FLAKE8, True))
        elif arg.option == Option.PYLINT:
            new_args.append(ImmutableArg(Option.PYLINT, restrict_pylint(arg.val)))  # type: ignore
        else:
            new_args.append(arg)
    return ImmutableConfig(tuple(new_args), config.enablers)
