import json
import shutil
import subprocess

import pytest

from edulint.config.config import get_config_one
from edulint.fast import rules
from edulint.fast.rules import (
    FLAKE8_PREVIEW_ONLY,
    FLAKE8_TO_RUFF,
    FLAKE8_UNMAPPED,
    PYLINT_TO_RUFF,
    plan_flake8,
    plan_ruff,
    pylint_equivalent,
    restrict_config_to_uncovered,
)
from edulint.linters import Linter
from edulint.options import Option

needs_ruff = pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not installed")


@pytest.fixture(scope="module")
def default_config(tmp_path_factory):
    path = tmp_path_factory.mktemp("cfg") / "x.py"
    path.write_text("x = 1\n")
    config, _translations = get_config_one(str(path), [])
    return config


def test_flake8_tables_do_not_overlap():
    assert not set(FLAKE8_TO_RUFF) & set(FLAKE8_UNMAPPED)


def test_default_config_flake8_plan(default_config):
    plan = plan_flake8(default_config[Option.FLAKE8])
    assert {"E501", "F401", "E111", "E999"} <= plan.selected
    assert {"E127", "E128", "F703", "W601"} <= plan.unmapped
    assert "E226" not in plan.selected  # not selected by the config
    assert plan.line_length == 79


def test_flake8_default_selection_and_ignore():
    plan = plan_flake8([])
    assert "E501" in plan.selected and "W291" in plan.selected
    assert "E226" not in plan.selected  # ignored by default
    assert "E121" not in plan.unmapped  # ignored by default
    assert "C901" not in plan.selected  # needs --max-complexity


def test_flake8_select_ignore_longest_prefix_wins():
    plan = plan_flake8(["--select=E", "--ignore=E5", "--extend-ignore=E111"])
    assert "E501" not in plan.selected
    assert "E111" not in plan.selected
    assert "E225" in plan.selected
    plan = plan_flake8(["--ignore=E", "--select=E501"])
    assert plan.selected == {"E501"}


def test_flake8_options():
    plan = plan_flake8(["--select=C901,E501", "--max-line-length=100", "--max-complexity=7"])
    assert plan.selected == {"C901", "E501"}
    assert plan.line_length == 100
    assert plan.max_complexity == 7


def test_ruff_plan_default_config(default_config):
    plan = plan_ruff(default_config)
    assert plan.preview  # E1xx/E2xx/E3xx are preview rules in Ruff
    assert "E501" not in plan.select  # computed by EduLint itself
    assert "E501" in plan.own_flake8
    assert {"F401", "RET505", "RET508", "A001", "A002", "B006", "PLC0415"} <= set(plan.select)
    targets = {(t.linter, t.code) for ts in plan.targets.values() for t in ts}
    assert (Linter.PYLINT, "R1705") in targets
    assert (Linter.FLAKE8, "F401") in targets
    assert (Linter.PYLINT, "R6401") not in targets  # EduLint's own checkers are not mapped


def test_ruff_plan_without_flake8(default_config):
    from edulint.config.arg import ImmutableArg
    from edulint.config.config import ImmutableConfig

    args = tuple(
        ImmutableArg(a.option, True) if a.option == Option.NO_FLAKE8 else a
        for a in default_config.config
    )
    plan = plan_ruff(ImmutableConfig(args, default_config.enablers))
    assert not plan.preview
    assert all(t.linter == Linter.PYLINT for ts in plan.targets.values() for t in ts)


def test_pylint_disable_removes_target():
    targets = rules.pylint_targets(
        ["--disable=all", "--enable=no-else-return,reimported", "--disable=R1705"]
    )
    assert [t.symbol for t in targets] == ["reimported"]


def test_restrict_config_keeps_only_uncovered(default_config):
    restricted = restrict_config_to_uncovered(default_config)
    assert restricted[Option.NO_FLAKE8] is True
    enabled = rules.enabled_pylint_messages(restricted[Option.PYLINT])
    assert "no-global-variables" in enabled
    assert "invalid-name" in enabled
    assert "no-else-return" not in enabled
    assert "reimported" not in enabled
    assert default_config[Option.NO_FLAKE8] is False  # original untouched


# %% the tables agree with Ruff and Pylint


@pytest.fixture(scope="module")
def ruff_rules():
    out = subprocess.run(
        ["ruff", "rule", "--all", "--output-format", "json"], stdout=subprocess.PIPE, check=True
    ).stdout
    return {r["code"]: r for r in json.loads(out)}


@needs_ruff
def test_mapped_flake8_codes_exist_in_ruff(ruff_rules):
    for code, ruff_code in FLAKE8_TO_RUFF.items():
        if ruff_code != rules.SYNTAX_ERROR_RUFF_CODE:
            assert ruff_code in ruff_rules, code


@needs_ruff
def test_unmapped_flake8_codes_are_missing_from_ruff(ruff_rules):
    assert [code for code in FLAKE8_UNMAPPED if code in ruff_rules] == []


@needs_ruff
def test_preview_table_matches_ruff(ruff_rules):
    for code, ruff_code in FLAKE8_TO_RUFF.items():
        if ruff_code in ruff_rules:
            assert (code in FLAKE8_PREVIEW_ONLY) == ruff_rules[ruff_code]["preview"], code


@needs_ruff
def test_mapped_pylint_rules_exist_and_are_stable(ruff_rules):
    for eq in PYLINT_TO_RUFF:
        for ruff_code in eq.ruff:
            assert ruff_code in ruff_rules, eq.symbol
            assert not ruff_rules[ruff_code]["preview"], eq.symbol


def test_pylint_ids_match_pylint():
    from pylint.lint import PyLinter

    linter = PyLinter()
    linter.load_default_plugins()
    for eq in PYLINT_TO_RUFF:
        definition = linter.msgs_store.get_message_definitions(eq.symbol)[0]
        assert definition.msgid == eq.msgid, eq.symbol


def test_lookup_by_symbol_and_id():
    assert pylint_equivalent("no-else-return") is pylint_equivalent("R1705")
    assert pylint_equivalent("invalid-name") is None
