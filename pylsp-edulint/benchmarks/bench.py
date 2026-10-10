"""
Benchmark of the EduLint tiers on real code.

    python benchmarks/bench.py [--runs 10] [--warmup 2] [--out benchmarks/results]

Measures (wall time, median and p95 over ``--runs`` repetitions after warm-up):

1. baseline: ``python -m edulint check <file>`` as a cold subprocess
2. full: the warm worker (the original pipeline, flake8 + pylint, in a persistent process)
3. fast: Ruff tier only (``edulint.fast.ruff_backend.lint_buffer``, in-process)
4. hybrid: time to first diagnostics (the fast tier) and time to complete
   (fast tier + the worker restricted to what Ruff cannot check)

It also records worker warm-up time, worker memory (RSS) and, per file, the
number of diagnostics and the (line, code) overlap with the baseline.
Raw results are written as CSV and JSON.
"""

import argparse
import csv
import glob
import importlib.util
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CORPUS = HERE / "corpus"
BASELINE_FLAGS = ["--disable-version-check", "--disable-explanations-update"]


def percentile(values, q):
    values = sorted(values)
    index = min(len(values) - 1, max(0, round(q * (len(values) - 1))))
    return values[index]


def summarize(values):
    return {
        "median_ms": statistics.median(values) * 1000,
        "p95_ms": percentile(values, 0.95) * 1000,
        "min_ms": min(values) * 1000,
    }


def timed(fn, runs, warmup):
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return samples


def oss_modules():
    """A few real small open-source modules from the installed environment (not copied into the repo)."""
    found = []
    for module, relative in (("mccabe", None), ("tomli", "_re.py"), ("zipp", "glob.py")):
        spec = importlib.util.find_spec(module)
        if spec is None or spec.origin is None:
            continue
        path = Path(spec.origin) if relative is None else Path(spec.origin).parent / relative
        if path.is_file():
            found.append(path)
    return found


def collect_files():
    files = sorted(CORPUS.glob("*.py"))
    files += sorted(Path(p) for p in glob.glob(str(REPO / "edulint" / "*.py")))
    files += sorted(Path(p) for p in glob.glob(str(REPO / "edulint" / "linting" / "*.py")))
    files += sorted(Path(p) for p in glob.glob(str(REPO / "tests" / "*.py")))
    files += oss_modules()
    return [f for f in files if f.name != "__init__.py" or f.stat().st_size > 0]


def category(path: Path):
    if path.is_relative_to(CORPUS) if hasattr(path, "is_relative_to") else str(path).startswith(str(CORPUS)):
        return "novice"
    if str(path).startswith(str(REPO)):
        return "repo"
    return "oss"


def baseline_run(path):
    return subprocess.run(
        [sys.executable, "-m", "edulint", "check", *BASELINE_FLAGS, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO,
    )


def parse_baseline(output: str, path: Path):
    findings = set()
    for line in output.splitlines():
        parts = line.split(":", 3)
        if len(parts) >= 4 and parts[1].isdigit():
            findings.add((int(parts[1]), parts[3].split()[0]))
    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--baseline-runs", type=int, default=None, help="defaults to --runs")
    parser.add_argument("--out", default=str(HERE / "results"))
    parser.add_argument("--limit", type=int, default=None, help="only the first N files (smoke test)")
    args = parser.parse_args()
    baseline_runs = args.baseline_runs or args.runs
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from loguru import logger

    logger.remove()
    from edulint.fast.hybrid import merge
    from edulint.fast.ruff_backend import find_ruff, lint_buffer
    from edulint.fast.worker import LintWorker, rss_kb

    files = collect_files()[: args.limit]

    worker = LintWorker()
    start = time.perf_counter()
    worker.start()
    spawn_to_ready = time.perf_counter() - start
    rss_after_warmup = rss_kb(worker.pid)

    rows = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        lines = len(text.splitlines())
        print(f"[{len(rows) + 1}/{len(files)}] {path.name} ({lines} lines)", flush=True)

        base_samples = timed(lambda: baseline_run(path), baseline_runs, 1)
        base = baseline_run(path)
        base_findings = parse_baseline(base.stdout.decode(), path)
        base_count = len(base.stdout.decode().splitlines())

        full_samples = timed(lambda: worker.lint(str(path), None), args.runs, args.warmup)
        full = worker.lint(str(path), None)
        fast_samples = timed(lambda: lint_buffer(str(path), text), args.runs, args.warmup)
        fast = lint_buffer(str(path), text)
        slow_samples = timed(
            lambda: worker.lint(str(path), None, restricted=True), args.runs, args.warmup
        )
        slow = worker.lint(str(path), None, restricted=True)
        hybrid = [p for p, _t in merge(fast, slow)]
        complete_samples = [f + s for f, s in zip(fast_samples, slow_samples)]

        def findings(problems):
            return {(p.line, p.code) for p in problems}

        hybrid_findings, full_findings = findings(hybrid), findings(full)
        rows.append(
            {
                "file": str(path.relative_to(REPO)) if str(path).startswith(str(REPO)) else str(path),
                "category": category(path),
                "lines": lines,
                "baseline": summarize(base_samples),
                "full_worker": summarize(full_samples),
                "ruff_only": summarize(fast_samples),
                "hybrid_first": summarize(fast_samples),
                "hybrid_complete": summarize(complete_samples),
                "baseline_diagnostics": base_count,
                "full_diagnostics": len(full),
                "ruff_only_diagnostics": len(fast),
                "hybrid_diagnostics": len(hybrid),
                "full_matches_baseline": full_findings == base_findings,
                "hybrid_missing_vs_baseline": sorted(f"{l}:{c}" for l, c in base_findings - hybrid_findings),
                "hybrid_extra_vs_baseline": sorted(f"{l}:{c}" for l, c in hybrid_findings - base_findings),
                "raw_s": {
                    "baseline": base_samples,
                    "full_worker": full_samples,
                    "ruff_only": fast_samples,
                    "worker_restricted": slow_samples,
                },
            }
        )

    rss_end = rss_kb(worker.pid)
    worker.stop()

    meta = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "ruff": subprocess.run(find_ruff() + ["--version"], stdout=subprocess.PIPE).stdout.decode().strip(),
        "runs": args.runs,
        "baseline_runs": baseline_runs,
        "warmup": args.warmup,
        "worker_spawn_to_ready_s": spawn_to_ready,
        "worker_internal_warmup_s": worker.warmup_seconds,
        "worker_rss_after_warmup_kb": rss_after_warmup,
        "worker_rss_end_kb": rss_end,
        "files": len(rows),
    }
    (out / "results.json").write_text(json.dumps({"meta": meta, "files": rows}, indent=2))

    columns = ["baseline", "full_worker", "ruff_only", "hybrid_complete"]
    with open(out / "results.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["file", "category", "lines"]
            + [f"{c}_{m}" for c in columns for m in ("median_ms", "p95_ms")]
            + ["baseline_diagnostics", "full_diagnostics", "ruff_only_diagnostics", "hybrid_diagnostics",
               "full_matches_baseline", "hybrid_missing_vs_baseline", "hybrid_extra_vs_baseline"]
        )
        for r in rows:
            writer.writerow(
                [r["file"], r["category"], r["lines"]]
                + [round(r[c][m], 2) for c in columns for m in ("median_ms", "p95_ms")]
                + [r["baseline_diagnostics"], r["full_diagnostics"], r["ruff_only_diagnostics"],
                   r["hybrid_diagnostics"], r["full_matches_baseline"],
                   " ".join(r["hybrid_missing_vs_baseline"]), " ".join(r["hybrid_extra_vs_baseline"])]
            )

    print_summary(meta, rows, out)


def print_summary(meta, rows, out):
    def med(rows_, key, field="median_ms"):
        return statistics.median(r[key][field] for r in rows_) if rows_ else float("nan")

    lines = [
        f"Python {meta['python']}, {meta['platform']}, {meta['cpu_count']} CPUs, {meta['ruff']}",
        f"{meta['files']} files, {meta['runs']} runs (+{meta['warmup']} warm-up), baseline {meta['baseline_runs']} runs",
        f"worker: spawn->ready {meta['worker_spawn_to_ready_s']:.2f}s, "
        f"RSS after warm-up {meta['worker_rss_after_warmup_kb']} kB, at end {meta['worker_rss_end_kb']} kB",
        "",
        "| group | files | edulint check (cold) | worker, full | Ruff only | hybrid first | hybrid complete |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, group in (("novice", [r for r in rows if r["category"] == "novice"]),
                        ("repo", [r for r in rows if r["category"] == "repo"]),
                        ("oss", [r for r in rows if r["category"] == "oss"]),
                        ("all", rows)):
        if not group:
            continue
        cells = []
        for key in ("baseline", "full_worker", "ruff_only", "hybrid_first", "hybrid_complete"):
            cells.append(f"{med(group, key):.0f} / {statistics.median(r[key]['p95_ms'] for r in group):.0f}")
        lines.append(f"| {name} | {len(group)} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("(cells: median of per-file medians / median of per-file p95, in ms)")
    lines.append("")
    same = sum(1 for r in rows if not r["hybrid_missing_vs_baseline"] and not r["hybrid_extra_vs_baseline"])
    full_same = sum(1 for r in rows if r["full_matches_baseline"])
    lines.append(f"hybrid findings identical to baseline for {same}/{len(rows)} files; worker (full) identical for {full_same}/{len(rows)}")
    total_b = sum(r["baseline_diagnostics"] for r in rows)
    total_h = sum(r["hybrid_diagnostics"] for r in rows)
    lines.append(f"diagnostics: baseline {total_b}, hybrid {total_h}, Ruff only {sum(r['ruff_only_diagnostics'] for r in rows)}")
    summary = "\n".join(lines)
    (out / "summary.md").write_text(summary + "\n")
    print(summary)


if __name__ == "__main__":
    main()
