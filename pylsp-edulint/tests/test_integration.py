"""End-to-end: run python-lsp-server over stdio with the plugin and check published diagnostics."""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

SAMPLE = """import os


def f(a=[]):
    if a:
        return 1
    else:
        return 2


total = 0
for i in range(3):
    total += i
"""


class Client:
    def __init__(self, root: Path, settings: dict) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "pylsp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=root,
        )
        self.messages: list = []
        self._id = 0
        threading.Thread(target=self._read, daemon=True).start()
        self.request(
            "initialize",
            {"processId": os.getpid(), "rootUri": root.as_uri(), "capabilities": {}},
        )
        self.notify("initialized", {})
        self.notify("workspace/didChangeConfiguration", {"settings": {"pylsp": settings}})

    def _read(self) -> None:
        out = self.proc.stdout
        while True:
            length = None
            while True:
                line = out.readline()
                if not line:
                    return
                if line in (b"\r\n", b"\n"):
                    break
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":")[1])
            self.messages.append(json.loads(out.read(length)))

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        self.proc.stdin.flush()

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict, timeout: float = 30):
        self._id += 1
        request_id = self._id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return self.wait(lambda m: m.get("id") == request_id and "method" not in m, timeout)

    def wait(self, predicate, timeout: float = 60):
        deadline = time.time() + timeout
        seen = 0
        while time.time() < deadline:
            for message in self.messages[seen:]:
                if predicate(message):
                    return message
            seen = len(self.messages)
            time.sleep(0.05)
        raise AssertionError("timed out waiting for message")

    def diagnostics_for(self, uri: str, predicate, timeout: float = 60):
        def is_match(m):
            return (
                m.get("method") == "textDocument/publishDiagnostics"
                and m["params"]["uri"] == uri
                and predicate(m["params"]["diagnostics"])
            )

        return self.wait(is_match, timeout)["params"]["diagnostics"]

    def close(self) -> None:
        try:
            self.request("shutdown", {}, timeout=10)
            self.notify("exit", {})
            self.proc.wait(10)
        except Exception:
            self.proc.kill()


def _open(client: Client, path: Path, text: str) -> str:
    uri = path.as_uri()
    client.notify(
        "textDocument/didOpen",
        {"textDocument": {"uri": uri, "languageId": "python", "version": 1, "text": text}},
    )
    return uri


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "sample.py"
    path.write_text(SAMPLE)
    return tmp_path, path


def _settings(**plugin):
    disabled = {
        name: {"enabled": False}
        for name in ("pyflakes", "pycodestyle", "mccabe", "pylint", "flake8", "autopep8", "yapf")
    }
    return {"plugins": {**disabled, "pylsp_edulint": plugin}}


def test_fast_mode_publishes_ruff_diagnostics(project):
    root, path = project
    client = Client(root, _settings(mode="fast"))
    try:
        uri = _open(client, path, SAMPLE)
        diagnostics = client.diagnostics_for(uri, lambda d: len(d) > 0)
    finally:
        client.close()
    codes = {d["code"] for d in diagnostics}
    assert {"F401", "W0102", "R1705"} <= codes
    assert {d["source"] for d in diagnostics} == {"edulint/ruff"}
    unused_import = next(d for d in diagnostics if d["code"] == "F401")
    assert unused_import["range"]["start"] == {"line": 0, "character": 7}
    assert unused_import["severity"] == 2
    assert unused_import["message"].endswith("[default]")


@pytest.mark.worker
def test_hybrid_mode_merges_worker_diagnostics(project):
    root, path = project
    client = Client(root, _settings(mode="hybrid", full_check="save", debounce=0.1))
    try:
        uri = _open(client, path, SAMPLE)
        first = client.diagnostics_for(uri, lambda d: len(d) > 0)
        assert {d["source"] for d in first} == {"edulint/ruff"}
        client.notify("textDocument/didSave", {"textDocument": {"uri": uri}})
        merged = client.diagnostics_for(
            uri, lambda d: any(x["source"] == "edulint/worker" for x in d), timeout=90
        )
    finally:
        client.close()
    assert "C0103" in {d["code"] for d in merged}  # invalid-name: not covered by Ruff
    assert "F401" in {d["code"] for d in merged}


@pytest.mark.worker
def test_full_mode_uses_worker_only(project):
    root, path = project
    client = Client(root, _settings(mode="full"))
    try:
        uri = _open(client, path, SAMPLE)
        diagnostics = client.diagnostics_for(uri, lambda d: len(d) > 0, timeout=90)
    finally:
        client.close()
    assert {d["source"] for d in diagnostics} == {"edulint/worker"}
