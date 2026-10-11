import pytest

from edulint.fast.worker import LintWorker, WorkerTimeout, lint_text, rss_kb

SOURCE = "import os\n\n\ndef f(a):\n    if a:\n        return 1\n    else:\n        return 2\n\n\nx = 1\n"


def codes(problems):
    return sorted((p.line, p.code) for p in problems)


def test_lint_text_of_unsaved_buffer_maps_back_to_the_real_path(tmp_path):
    path = tmp_path / "a.py"
    path.write_text("x = 1\n")
    problems = lint_text(str(path), SOURCE)
    assert (1, "F401") in codes(problems)
    assert {p.path for p in problems} == {str(path)}


def test_restricted_lint_skips_what_ruff_covers(tmp_path):
    path = tmp_path / "a.py"
    path.write_text(SOURCE)
    found = {code for _line, code in codes(lint_text(str(path), SOURCE, restricted=True))}
    assert "C0103" in found  # invalid-name: no Ruff equivalent
    assert not found & {"F401", "R1705", "E302"}


@pytest.mark.worker
def test_worker_process_roundtrip_and_timeout(tmp_path):
    path = tmp_path / "a.py"
    worker = LintWorker(timeout=60)
    try:
        worker.start()
        assert worker.warmup_seconds is not None and worker.pid
        assert rss_kb(worker.pid) is None or rss_kb(worker.pid) > 0
        problems = worker.lint(str(path), SOURCE)
        assert (1, "F401") in codes(problems)

        old_pid = worker.pid
        with pytest.raises(WorkerTimeout):
            worker.lint(str(path), SOURCE, timeout=0.0)
        assert worker.pid is None  # killed
        assert (1, "F401") in codes(worker.lint(str(path), SOURCE))  # respawned
        assert worker.pid != old_pid
    finally:
        worker.stop()
