Python 3.12.3, Linux-6.17.0-1022-azure-x86_64-with-glibc2.39, 4 CPUs, ruff 0.17.0
20 files, 5 runs (+1 warm-up), baseline 3 runs
worker: spawn->ready 0.35s, RSS after warm-up 70460 kB, at end 243440 kB

| group | files | edulint check (cold) | worker, full | Ruff only | hybrid first | hybrid complete |
|---|---|---|---|---|---|---|
| novice | 12 | 535 / 563 | 76 / 151 | 4 / 5 | 4 / 5 | 74 / 156 |
| repo | 8 | 1222 / 1266 | 275 / 707 | 4 / 5 | 4 / 5 | 285 / 1102 |
| all | 20 | 584 / 644 | 85 / 209 | 4 / 5 | 4 / 5 | 82 / 199 |

(cells: median of per-file medians / median of per-file p95, in ms)

hybrid findings identical to baseline for 18/20 files; worker (full) identical for 20/20
diagnostics: baseline 128, hybrid 125, Ruff only 108
