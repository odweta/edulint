"""
python-lsp-server plugin that reports EduLint diagnostics.

Tiers
-----
* fast: Ruff over stdin, mapped to EduLint messages (milliseconds)
* slow: a persistent warm EduLint worker process, restricted to what Ruff
  cannot check (EduLint's own checkers and unmapped pylint messages)

EduLint itself (flake8/pylint in-process) is never run in the language server
process because it swaps ``sys.stdout``/``sys.stderr``, which would corrupt the
stdio protocol; it only runs in the ``spawn``-ed worker.
"""

import hashlib
import logging
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from edulint.fast.hybrid import merge
from pylsp import hookimpl

from pylsp_edulint.diagnostics import problem_at, problem_to_diagnostic

log = logging.getLogger(__name__)

PLUGIN = "pylsp_edulint"
MODES = ("fast", "hybrid", "full")
FULL_CHECKS = ("save", "live", "off")
MAX_CACHED_DOCUMENTS = 64

DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "live_mode": True,
    "mode": "hybrid",
    "full_check": "save",
    "options": [],
    "timeout": 60,
    "ruff_executable": None,
    "debounce": 0.5,
}


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()


class _DocState:
    def __init__(self) -> None:
        self.text = ""
        """Text that ``fast_problems`` were computed for."""
        self.fast_tool = "ruff"
        self.fast_problems: List[Any] = []
        self.slow_digest: Optional[str] = None
        self.slow_problems: List[Any] = []
        self.timer: Optional[threading.Timer] = None
        self.generation = 0


class _State:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.worker: Any = None
        self.documents: "OrderedDict[str, _DocState]" = OrderedDict()
        self.ruff_error_reported = False

    def doc(self, uri: str) -> _DocState:
        with self.lock:
            state = self.documents.get(uri)
            if state is None:
                state = self.documents[uri] = _DocState()
            self.documents.move_to_end(uri)
            while len(self.documents) > MAX_CACHED_DOCUMENTS:
                _uri, old = self.documents.popitem(last=False)
                if old.timer is not None:
                    old.timer.cancel()
            return state

    def drop(self, uri: str) -> None:
        with self.lock:
            state = self.documents.pop(uri, None)
        if state is not None and state.timer is not None:
            state.timer.cancel()

    def get_worker(self, timeout: float) -> Any:
        from edulint.fast.worker import LintWorker

        with self.lock:
            if self.worker is None:
                self.worker = LintWorker(timeout=timeout)
            return self.worker


_STATE = _State()


def _settings(config: Any, document_path: Optional[str] = None) -> Dict[str, Any]:
    settings = dict(DEFAULTS)
    settings.update(config.plugin_settings(PLUGIN, document_path=document_path) or {})
    if settings["mode"] not in MODES:
        log.warning("unknown mode %r, using 'hybrid'", settings["mode"])
        settings["mode"] = "hybrid"
    if settings["full_check"] not in FULL_CHECKS:
        log.warning("unknown full_check %r, using 'save'", settings["full_check"])
        settings["full_check"] = "save"
    return settings


def _uses_worker(settings: Dict[str, Any]) -> bool:
    return settings["mode"] == "full" or (
        settings["mode"] == "hybrid" and settings["full_check"] != "off"
    )


@hookimpl
def pylsp_settings() -> Dict[str, Any]:
    return {"plugins": {PLUGIN: dict(DEFAULTS)}}


@hookimpl
def pylsp_initialize(config: Any, workspace: Any) -> None:
    settings = _settings(config)
    if not settings["enabled"] or not _uses_worker(settings):
        return
    worker = _STATE.get_worker(settings["timeout"])

    def warm() -> None:
        try:
            worker.start()
        except Exception as e:  # reported again on first use
            log.warning("EduLint worker did not start: %s", e)

    threading.Thread(target=warm, name="edulint-warmup", daemon=True).start()


@hookimpl
def pylsp_document_did_close(config: Any = None, workspace: Any = None, document: Any = None) -> None:
    """Drops cached results. (python-lsp-server has no such hook yet; pruning also happens in lint.)"""
    if document is not None:
        _STATE.drop(document.uri)


@hookimpl
def pylsp_shutdown(config: Any = None, workspace: Any = None) -> None:
    with _STATE.lock:
        for state in _STATE.documents.values():
            if state.timer is not None:
                state.timer.cancel()
        _STATE.documents.clear()
        worker, _STATE.worker = _STATE.worker, None
    if worker is not None:
        worker.stop()


def _diagnostics(state: _DocState) -> List[Dict[str, Any]]:
    text = state.text
    slow = state.slow_problems if state.slow_digest == _digest(text) else []
    lines = text.splitlines()
    return [
        problem_to_diagnostic(problem, lines, tool)
        for problem, tool in merge(state.fast_problems, slow, state.fast_tool)
    ]


def _error_diagnostic(message: str) -> Dict[str, Any]:
    zero = {"line": 0, "character": 0}
    return {
        "source": "edulint",
        "range": {"start": zero, "end": zero},
        "message": message,
        "severity": 1,
    }


def _schedule_slow(
    config: Any, workspace: Any, document: Any, settings: Dict[str, Any], text: str
) -> None:
    uri, path = document.uri, document.path
    state = _STATE.doc(uri)
    digest = _digest(text)
    with _STATE.lock:
        state.generation += 1
        generation = state.generation
        if state.timer is not None:
            state.timer.cancel()

    def run() -> None:
        from edulint.fast.worker import WorkerError

        worker = _STATE.get_worker(settings["timeout"])
        try:
            problems = worker.lint(
                path, text, settings["options"], restricted=True, timeout=settings["timeout"]
            )
        except WorkerError as e:
            log.warning("EduLint worker failed: %s", e)
            return
        with _STATE.lock:
            if state.generation != generation or uri not in _STATE.documents:
                return  # a newer lint was scheduled or the document was closed
        current = workspace.get_document(uri) if hasattr(workspace, "get_document") else document
        if _digest(current.source) != digest:
            return  # stale: the buffer changed while the worker was running
        state.slow_digest, state.slow_problems = digest, problems
        workspace.publish_diagnostics(uri, _diagnostics(state), getattr(current, "version", None))

    timer = threading.Timer(settings["debounce"], run)
    timer.daemon = True
    state.timer = timer
    timer.start()


@hookimpl
def pylsp_lint(config: Any, workspace: Any, document: Any, is_saved: bool) -> List[Dict[str, Any]]:
    settings = _settings(config, document.path)
    if not settings["enabled"]:
        return []

    state = _STATE.doc(document.uri)
    text = document.source
    if not settings["live_mode"] and not is_saved:
        return _diagnostics(state)

    if settings["mode"] == "full":
        from edulint.fast.worker import WorkerError

        try:
            worker = _STATE.get_worker(settings["timeout"])
            problems = worker.lint(document.path, text, settings["options"], timeout=settings["timeout"])
        except WorkerError as e:
            log.error("EduLint worker failed: %s", e)
            return [_error_diagnostic(f"EduLint worker failed: {e}")]
        except Exception as e:  # pluggy would swallow it and the editor would show nothing
            log.exception("EduLint failed")
            return [_error_diagnostic(f"EduLint failed: {type(e).__name__}: {e}")]
        state.fast_problems, state.fast_tool, state.text = problems, "worker", text
        state.slow_problems = []
        return _diagnostics(state)

    from edulint.fast.ruff_backend import RuffError, RuffNotFoundError, lint_buffer

    try:
        problems = lint_buffer(
            document.path,
            text,
            settings["options"],
            settings["ruff_executable"],
            timeout=settings["timeout"],
        )
    except RuffNotFoundError as e:
        log.error("%s", e)
        if _STATE.ruff_error_reported:
            return []
        _STATE.ruff_error_reported = True
        return [_error_diagnostic(f"EduLint: {e}")]
    except RuffError as e:
        log.error("Ruff failed: %s", e)
        return [_error_diagnostic(f"EduLint: {e}")]
    except Exception as e:
        log.exception("EduLint failed")
        return [_error_diagnostic(f"EduLint failed: {type(e).__name__}: {e}")]
    state.fast_problems, state.fast_tool, state.text = problems, "ruff", text

    if settings["mode"] == "hybrid" and (
        (settings["full_check"] == "live") or (settings["full_check"] == "save" and is_saved)
    ):
        _schedule_slow(config, workspace, document, settings, text)

    return _diagnostics(state)


@hookimpl
def pylsp_hover(config: Any, workspace: Any, document: Any, position: Dict[str, int]) -> Optional[Dict[str, Any]]:
    """Shows EduLint's explanation of the message under the cursor, if there is one."""
    settings = _settings(config, document.path)
    state = _STATE.documents.get(document.uri)
    if not settings["enabled"] or state is None:
        return None
    problems = state.fast_problems + (state.slow_problems if state.slow_digest == _digest(document.source) else [])
    problem = problem_at(problems, position["line"], position["character"], document.source)
    if problem is None:
        return None
    try:
        from edulint import get_message_explanations

        explanation = get_message_explanations([problem.code]).get(problem.code)
    except Exception as e:  # hover must never break the server
        log.debug("could not get explanation: %s", e)
        return None
    if not explanation:
        return None
    parts = [f"**{problem.code}**"]
    if explanation.get("why", "").strip():
        parts.append(explanation["why"].strip())
    if explanation.get("examples", "").strip():
        parts.append(explanation["examples"].strip())
    return {"contents": {"kind": "markdown", "value": "\n\n".join(parts)}}
