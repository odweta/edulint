# pylsp-edulint

[EduLint](https://github.com/GiraffeReversed/edulint) diagnostics for [python-lsp-server](https://github.com/python-lsp/python-lsp-server) (pylsp), e.g. in Neovim.
`edulint check` starts a new interpreter and imports pylint/astroid/flake8/z3 every time (~0.5-1.5 s per file), so this plugin uses two tiers:

1. **fast tier**: [Ruff](https://docs.astral.sh/ruff/) over stdin (a few ms). The flake8 codes and pylint messages enabled by the active EduLint config are mapped to Ruff rules and reported under their EduLint ids.
2. **full tier**: a persistent, warm EduLint worker process (`multiprocessing` `spawn`, started and warmed up at `pylsp_initialize`) that runs only what Ruff cannot cover (EduLint's custom checkers R6xxx etc. and unmapped pylint messages). Results are merged in when ready.

EduLint itself is never run inside the pylsp process (flake8/pylint swap `sys.stdout`/`sys.stderr`, which would corrupt the LSP stdio stream).

## Install

Install into the **same environment as pylsp**:

```sh
# from a checkout of this repository
pip install -e . -e ./pylsp-edulint     # edulint + the plugin (pulls in ruff and python-lsp-server)

# pipx
pipx install python-lsp-server
pipx inject python-lsp-server /path/to/edulint /path/to/edulint/pylsp-edulint

# Mason (Neovim)
:PylspInstall pylsp-edulint edulint ruff
```

## Neovim (0.11+) `init.lua`

```lua
-- python lsp
vim.lsp.config("pylsp", {
  cmd = { "pylsp" },
  capabilities = capabilities,
  settings = {
    pylsp = {
      plugins = {
        pylsp_edulint = {
          enabled = true,
          live_mode = true,
          mode = "hybrid",       -- "fast" | "hybrid" | "full"
          full_check = "save",   -- "save" | "live" | "off"
          options = { "config-file=cs1" }, -- like `edulint check -o`
        },
        -- avoid duplicate diagnostics
        pyflakes = { enabled = false },
        pycodestyle = { enabled = false },
        mccabe = { enabled = false },
        pylint = { enabled = false },
        flake8 = { enabled = false },
      },
    },
  },
})

vim.lsp.enable("pylsp")
```

Verify with `:LspInfo` (pylsp attached) and `:LspLog` (look for `pylsp_edulint`); diagnostics have source `edulint/ruff` or `edulint/pylint`/`edulint/flake8`.

## Settings

| setting | default | meaning |
|---|---|---|
| `enabled` | `true` | |
| `live_mode` | `true` | lint on every change; if `false`, only saved documents are linted (unsaved edits keep the previous diagnostics) |
| `mode` | `"hybrid"` | see below |
| `full_check` | `"save"` | when the slow tier runs in hybrid mode: on save, on every (debounced) change, or never |
| `options` | `[]` | EduLint options, as for `edulint check -o` |
| `timeout` | `60` | seconds before the worker is killed and respawned |
| `ruff_executable` | auto | path to `ruff` |
| `debounce` | `0.5` | seconds before the slow tier starts after a change |

| mode | speed | fidelity |
|---|---|---|
| `fast` | ~5 ms | Ruff only: no EduLint-specific checks (R6xxx), approximate pylint equivalents |
| `hybrid` | first diagnostics ~5 ms, complete after tens to hundreds of ms | everything EduLint reports, except the known differences below; Ruff text for mapped pylint rules |
| `full` | warm worker, ~0.1-0.3 s/file | identical to `edulint check` (no Ruff) |

## What Ruff covers

The mapping tables live in `edulint/fast/rules.py` (`FLAKE8_TO_RUFF`, `FLAKE8_UNMAPPED`, `FLAKE8_PREVIEW_ONLY`, `PYLINT_TO_RUFF`) and are verified in `tests/test_fast_rules.py` against the installed Ruff and pylint.

* flake8 E/W/F codes: mostly 1:1. Not available in Ruff (left to the worker or dropped): E12x/E13x continuation-line checks, E704, E901, F703/F705/F721/F723/F831, W503/W504, W601-W606. E501 is computed in Python (pycodestyle-faithful). Many pycodestyle rules need Ruff `--preview`, which is passed only when needed.
* pylint messages with a Ruff equivalent: comparison-with-itself, dangerous-default-value, function-redefined, import-outside-toplevel, no-else-break/continue/raise/return, non-ascii-name, not-in-loop, pointless-statement, redefined-argument-from-local, redefined-builtin, return-in-init, self-assigning-variable, trailing-comma-tuple, unnecessary-dict-index-lookup, unnecessary-pass, wildcard-import, consider-using-from-import, reimported, unused-import, unused-variable, undefined-variable, global-statement, bare-except, consider-using-in. Some are approximations.
* **Not reproducible by Ruff**: EduLint's custom checkers (no-global-vars R6401, long code R6701/R6702, duplication, simplifiable-if, unsuited-loop, local defects, ...). They need CFG/z3 analyses and are run only by the worker.

Known differences (hybrid vs `edulint check`): RET505-508 only fire inside functions (module-level no-else-break missing); E712 is missed for chained comparisons (`a > b == True`); `from X import *` yields no F401/W0622 in Ruff; message text of mapped pylint rules is Ruff's; R1705/E0101/F811/A001/B018/B006 positions are relocated heuristically. In `hybrid` mode these gaps exist only until/unless the slow tier covers them (it does not re-run Ruff-covered rules). Use `mode = "full"` for exact parity.

## Benchmark

`python pylsp-edulint/benchmarks/bench.py` (raw data in `benchmarks/results/`: `results.json`, `results.csv`, `summary.md`). Measured on a 4-CPU Linux VM, Python 3.12.3, Ruff 0.17.0, **20 files** (12 novice-style scripts of 6-38 lines in `benchmarks/corpus/` and 8 files from `edulint/` and `edulint/linting/`, up to 315 lines), **5 timed runs after 1 warm-up** (3 for the cold `edulint check` baseline). This is a reduced run (small sample, no tests/ or third-party modules); numbers are indicative only. Cells: median / p95 in ms (median of per-file values).

| group | files | `edulint check` (cold) | worker, full | Ruff only | hybrid first | hybrid complete |
|---|---|---|---|---|---|---|
| novice | 12 | 535 / 563 | 76 / 151 | 4 / 5 | 4 / 5 | 74 / 156 |
| repo | 8 | 1222 / 1266 | 275 / 707 | 4 / 5 | 4 / 5 | 285 / 1102 |
| all | 20 | 584 / 644 | 85 / 209 | 4 / 5 | 4 / 5 | 82 / 199 |

* Worker spawn-to-ready (including warm-up): 0.35 s. Worker RSS: 70 MB after warm-up, 243 MB after linting all files.
* Hybrid complete = Ruff time + restricted worker time (sequential sum).
* Parity vs `edulint check` (per file, set of line:code): the full worker matched on 20/20 files; hybrid on 18/20 (128 baseline diagnostics, 125 hybrid, 108 Ruff-only). Differences: `01_grades.py` misses `27:E712` (chained comparison), `03_shopping.py` misses `1:F401` and `1:W0622` (star import).
* Ruff-only reports 108 of 128 diagnostics: the remainder are EduLint-specific checks.

## Troubleshooting

* **Duplicate diagnostics**: disable pylsp's pyflakes/pycodestyle/mccabe/pylint/flake8 plugins (see above). The slow tier publishes diagnostics for the whole document, which can replace other plugins' diagnostics until their next run.
* **Relative `config-file=...`** is resolved relative to the linted file; for unsaved/temp buffers use an absolute path.
* **Ruff missing**: a single error diagnostic is shown; `pip install ruff` into pylsp's environment or set `ruff_executable`.
* **Stale diagnostics after closing a document**: pylsp has no `did_close` hook spec, so the cache is pruned by an LRU of 64 documents.
* Columns are converted to LSP UTF-16 offsets; flake8 columns are 1-based, pylint 0-based.

## Tests

```sh
pytest tests/test_fast_*.py pylsp-edulint/tests
pytest -m "not worker" pylsp-edulint/tests   # skip tests that spawn the worker
```

GPL-3.0, like EduLint.
