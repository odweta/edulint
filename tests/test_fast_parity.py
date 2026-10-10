"""
Parity of the hybrid mode (Ruff + EduLint-only checks) with ``edulint check``.

For each snippet the set of ``(line, code)`` findings of the original EduLint
pipeline is compared with the hybrid result. Every difference has to be listed
in ``KNOWN_DIFFERENCES`` so that it is documented (see pylsp-edulint/README.md).
"""

import shutil
from pathlib import Path

import pytest
from loguru import logger

from edulint import check_code
from edulint.fast import config_cache
from edulint.fast.hybrid import lint_hybrid

pytestmark = pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not installed")

SNIPPETS = {
    "unused_and_undefined": "import os\nimport sys\nprint(sys.argv, undefined_name)\n",
    "unused_variable": "def f():\n    x = 1\n    y = 2\n    return y\n",
    "no_else_return": "def f(a):\n    if a:\n        return 1\n    else:\n        return 2\n",
    "no_else_break": (
        "def f(items):\n    for i in items:\n        if i:\n            break\n"
        "        else:\n            print(i)\n"
    ),
    "no_else_break_module_level": (
        "for i in range(3):\n    if i:\n        break\n    else:\n        print(i)\n"
    ),
    "default_mutable": "def f(a=[], b={}):\n    return a, b\n",
    "builtin_shadowing": "def f(list, id):\n    max = 1\n    return max\n\n\nsum = 1\n",
    "wildcard": "from os.path import *\n\nprint(join('a', 'b'))\n",
    "import_outside_toplevel": "def f():\n    import os\n    return os\n",
    "from_import": "import os.path as path\n\nprint(path)\n",
    "reimport": "import os\nimport os\n\nprint(os)\n",
    "function_redefined": "def f():\n    pass\n\n\ndef f():\n    pass\n",
    "comparison_with_itself": "x = 1\nprint(x == x)\n",
    "self_assign": "x = 1\nx = x\nprint(x)\n",
    "trailing_comma": "x = 1,\nprint(x)\n",
    "unnecessary_pass": "def f():\n    print(1)\n    pass\n",
    "return_in_init": "class A:\n    def __init__(self):\n        return 1\n",
    "redefined_argument": "def f(a):\n    for a in range(3):\n        print(a)\n",
    "dict_index_lookup": "d = {1: 2}\nfor k, v in d.items():\n    print(d[k], v)\n",
    "not_in_loop": "def f():\n    break\n",
    "pointless_statement": "x = 1\nx == 2\n",
    "bare_except": "try:\n    pass\nexcept:\n    pass\n",
    "singleton_comparison": "x = None\nif x == None or x == True:\n    pass\n",
    "whitespace": "x = 1   \ny=2\nprint( x ,y )\n",
    "blank_lines": "def f():\n    pass\ndef g():\n    pass\nx = 1\n",
    "indentation": "def f():\n  return 1\n",
    "long_line": "x = '" + "a" * 100 + "'\n",
    "string_formatting": "print('%s %s' % (1,))\nprint('{} {}'.format(1))\nprint(f'abc')\n",
    "lambda_and_l": "f = lambda: 0\nl = 1\nprint(f, l)\n",
    "syntax_error": "def f(:\n    pass\n",
    "while_true_and_global": "x = 0\nwhile True:\n    x += 1\n    if x > 3:\n        break\n",
    "simplifiable_if": "def f(a):\n    if a > 1:\n        return True\n    else:\n        return False\n",
}

# (line, code) -> why the hybrid mode differs from edulint check
KNOWN_DIFFERENCES = {
    # Ruff's flake8-return rules only look inside functions
    "no_else_break_module_level": {"missing": {(2, "R1723")}},
}


@pytest.fixture(autouse=True, scope="module")
def _quiet_and_isolated():
    logger.remove()
    yield
    config_cache.uninstall()


def findings(problems):
    return {(p.line, p.code) for p in problems}


def compare(path: Path):
    text = path.read_text()
    _configs, baseline = check_code([str(path)])
    hybrid = lint_hybrid(str(path), text)
    return findings(baseline), findings(hybrid)


@pytest.mark.parametrize("name", sorted(SNIPPETS))
def test_snippet_parity(name, tmp_path):
    path = tmp_path / f"{name}.py"
    path.write_text(SNIPPETS[name])
    baseline, hybrid = compare(path)
    known = KNOWN_DIFFERENCES.get(name, {})
    missing = {f for f in baseline - hybrid}
    extra = {f for f in hybrid - baseline}
    assert (missing, extra) == (set(known.get("missing", ())), set(known.get("extra", ()))), (
        f"missing={sorted(missing)} extra={sorted(extra)}"
    )


CORPUS = Path(__file__).resolve().parents[1] / "pylsp-edulint" / "benchmarks" / "corpus"
CORPUS_KNOWN = {
    "01_grades.py": {"missing": {(27, "E712")}},  # pycodestyle flags `a > b == True`, Ruff does not
    "03_shopping.py": {"missing": {(1, "F401"), (1, "W0622")}},  # `from math import *`
}


@pytest.mark.skipif(not CORPUS.is_dir(), reason="benchmark corpus is not available")
@pytest.mark.parametrize("name", sorted(p.name for p in CORPUS.glob("*.py")))
def test_novice_corpus_parity(name):
    baseline, hybrid = compare(CORPUS / name)
    known = CORPUS_KNOWN.get(name, {})
    assert (baseline - hybrid, hybrid - baseline) == (
        set(known.get("missing", ())),
        set(known.get("extra", ())),
    )
