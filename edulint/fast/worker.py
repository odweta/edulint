"""
A persistent, warm EduLint worker process.

EduLint's full pipeline (flake8 + pylint + custom checkers) spends most of a
run importing and initialising libraries. The worker imports everything once,
warms up on a dummy snippet, and then serves lint requests over a pipe. It is
started with the ``spawn`` method (never ``fork``) so that it is safe to use
from a multi-threaded language server.

It runs ``get_config_many`` -> ``lint_many`` -> ``sort`` and skips ``main()``,
so there is no version check and no explanation update.
"""

import multiprocessing
import os
import sys
import tempfile
import threading
import time
from typing import Any, List, Optional, Sequence

from edulint.linting.problem import Problem

WARMUP_SOURCE = "def f(x):\n    if x:\n        return 1\n    else:\n        return 2\n\n\nprint(f(1))\n"


class WorkerError(RuntimeError):
    pass


class WorkerTimeout(WorkerError):
    pass


def lint_text(
    path: str, text: Optional[str], options: Sequence[str] = (), restricted: bool = False
) -> List[Problem]:
    """
    Runs the original EduLint pipeline on a file. If ``text`` differs from the
    content on disk, a temporary copy is linted (configuration is still
    resolved for ``path``) and problem paths are mapped back to ``path``.

    :param restricted: only run what Ruff cannot cover (flake8 off, pylint
      without messages Ruff has an equivalent for)
    """
    from edulint.config.config import get_cmd_args, get_config_many
    from edulint.fast import config_cache
    from edulint.fast.rules import restrict_config_to_uncovered
    from edulint.linting.linting import get_proper_path, lint_many, sort

    real = os.path.abspath(path)
    on_disk = None
    if text is not None:
        try:
            with open(real, encoding="utf-8") as f:
                on_disk = f.read()
        except OSError:
            pass

    with config_cache.buffer_override(real, text):
        configs = get_config_many([path], get_cmd_args(list(options)))

    partition = []
    for _paths, config, translations in configs:
        if restricted:
            config = restrict_config_to_uncovered(config)
        partition.append((_paths, config, translations))

    if text is None or text == on_disk:
        problems = lint_many(partition)
        return sort([path], problems) if problems else []

    with tempfile.TemporaryDirectory(prefix="edulint-") as tmp:
        tmp_path = os.path.join(tmp, os.path.basename(real))
        with open(tmp_path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        problems = lint_many([([tmp_path], c, t) for _p, c, t in partition])
        shown = get_proper_path(path)
        for problem in problems:
            problem.path = shown
        return sort([shown], problems) if problems else []


def _silence_loguru() -> None:
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="WARNING", format="<level>{name}</level>: {message}")


def _worker_main(conn: Any) -> None:
    # the parent may speak a protocol on stdio (language server): never touch it
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    sys.stdout = sys.stderr

    _silence_loguru()
    from edulint.fast import config_cache

    config_cache.install()

    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="edulint-warmup-") as tmp:
            warm_path = os.path.join(tmp, "warmup.py")
            with open(warm_path, "w", encoding="utf-8") as f:
                f.write(WARMUP_SOURCE)
            lint_text(warm_path, WARMUP_SOURCE)
            lint_text(warm_path, WARMUP_SOURCE, restricted=True)
    except Exception as e:  # warm-up failures show up on first real request
        print(f"edulint worker warm-up failed: {e!r}", file=sys.stderr)
    conn.send(("ready", os.getpid(), time.perf_counter() - started))

    while True:
        try:
            message = conn.recv()
        except EOFError:
            return
        if message is None:
            return
        request_id, kwargs = message
        try:
            conn.send(("ok", request_id, lint_text(**kwargs)))
        except BaseException as e:  # keep serving after any single failure
            conn.send(("error", request_id, f"{type(e).__name__}: {e}"))


def rss_kb(pid: int) -> Optional[int]:
    """Resident set size of a process in kB (Linux only), or None."""
    try:
        with open(f"/proc/{pid}/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


class LintWorker:
    """Client for the worker process. Thread-safe; requests are serialised."""

    def __init__(self, timeout: float = 60.0, startup_timeout: float = 120.0) -> None:
        self.timeout = timeout
        self.startup_timeout = startup_timeout
        self.warmup_seconds: Optional[float] = None
        self._lock = threading.RLock()
        self._process: Any = None
        self._conn: Any = None
        self._next_id = 0

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self._process is not None else None

    def start(self) -> None:
        """Spawns the worker and blocks until it is warm."""
        with self._lock:
            if self._process is not None and self._process.is_alive():
                return
            self._kill()
            ctx = multiprocessing.get_context("spawn")
            parent, child = ctx.Pipe()
            process = ctx.Process(target=_worker_main, args=(child,), daemon=True)
            process.start()
            child.close()
            self._process, self._conn = process, parent
            if not parent.poll(self.startup_timeout):
                self._kill()
                raise WorkerTimeout("EduLint worker did not start in time")
            try:
                _kind, _pid, self.warmup_seconds = parent.recv()
            except EOFError as e:
                self._kill()
                raise WorkerError("EduLint worker died during start-up") from e

    def lint(
        self,
        path: str,
        text: Optional[str] = None,
        options: Sequence[str] = (),
        restricted: bool = False,
        timeout: Optional[float] = None,
    ) -> List[Problem]:
        timeout = self.timeout if timeout is None else timeout
        with self._lock:
            self.start()
            self._next_id += 1
            request_id = self._next_id
            try:
                self._conn.send(
                    (
                        request_id,
                        {
                            "path": path,
                            "text": text,
                            "options": list(options),
                            "restricted": restricted,
                        },
                    )
                )
                while True:
                    if not self._conn.poll(timeout):
                        self._kill()
                        raise WorkerTimeout(f"EduLint worker timed out after {timeout}s")
                    kind, reply_id, payload = self._conn.recv()
                    if reply_id == request_id:
                        break
            except (EOFError, BrokenPipeError, OSError) as e:
                self._kill()
                raise WorkerError(f"EduLint worker died: {e!r}") from e
            if kind == "error":
                raise WorkerError(payload)
            return payload

    def _kill(self) -> None:
        process, conn = self._process, self._conn
        self._process = self._conn = None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        if process is not None and process.is_alive():
            process.kill()
            process.join(5)

    def stop(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.send(None)
                except (OSError, ValueError):
                    pass
            if self._process is not None:
                self._process.join(2)
            self._kill()
