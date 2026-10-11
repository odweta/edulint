import types

import pytest

from pylsp_edulint import plugin


class FakeConfig:
    def __init__(self, **settings):
        self.settings = settings

    def plugin_settings(self, name, document_path=None):
        assert name == "pylsp_edulint"
        return self.settings


class FakeWorkspace:
    def __init__(self):
        self.published = []
        self.documents = {}

    def get_document(self, uri):
        return self.documents[uri]

    def publish_diagnostics(self, uri, diagnostics, version=None):
        self.published.append((uri, diagnostics, version))


def make_document(tmp_path, text, version=1):
    path = tmp_path / "a.py"
    return types.SimpleNamespace(
        uri=path.as_uri(), path=str(path), source=text, version=version, lines=text.splitlines()
    )


@pytest.fixture(autouse=True)
def reset_state():
    plugin.pylsp_shutdown()
    plugin._STATE.ruff_error_reported = False
    yield
    plugin.pylsp_shutdown()


def test_default_settings_are_exposed():
    settings = plugin.pylsp_settings()["plugins"]["pylsp_edulint"]
    assert settings["mode"] == "hybrid"
    assert settings["full_check"] == "save"
    assert settings["live_mode"] is True
    assert {"enabled", "options", "timeout", "ruff_executable"} <= set(settings)


def test_invalid_mode_falls_back_to_default():
    assert plugin._settings(FakeConfig(mode="nope", full_check="never"))["mode"] == "hybrid"
    assert plugin._settings(FakeConfig(mode="nope", full_check="never"))["full_check"] == "save"


def test_disabled_plugin_returns_nothing(tmp_path):
    document = make_document(tmp_path, "import os\n")
    config = FakeConfig(enabled=False)
    assert plugin.pylsp_lint(config, FakeWorkspace(), document, True) == []


def test_fast_mode_diagnostics(tmp_path):
    document = make_document(tmp_path, "import os\n")
    config = FakeConfig(mode="fast")
    diagnostics = plugin.pylsp_lint(config, FakeWorkspace(), document, False)
    assert [d["code"] for d in diagnostics] == ["F401"]
    assert diagnostics[0]["source"] == "edulint/ruff"
    assert diagnostics[0]["range"]["start"] == {"line": 0, "character": 7}


def test_live_mode_off_keeps_previous_diagnostics_until_saved(tmp_path):
    config = FakeConfig(mode="fast", live_mode=False)
    saved = make_document(tmp_path, "import os\n")
    first = plugin.pylsp_lint(config, FakeWorkspace(), saved, True)
    assert len(first) == 1
    edited = make_document(tmp_path, "import os\nimport sys\n")
    assert plugin.pylsp_lint(config, FakeWorkspace(), edited, False) == first
    assert len(plugin.pylsp_lint(config, FakeWorkspace(), edited, True)) == 2


def test_missing_ruff_is_reported_once_with_a_clear_message(tmp_path):
    document = make_document(tmp_path, "import os\n")
    config = FakeConfig(mode="fast", ruff_executable="no-such-ruff-binary")
    first = plugin.pylsp_lint(config, FakeWorkspace(), document, True)
    assert len(first) == 1 and "not found" in first[0]["message"] and first[0]["severity"] == 1
    assert plugin.pylsp_lint(config, FakeWorkspace(), document, True) == []


def test_closing_a_document_drops_its_cache(tmp_path):
    document = make_document(tmp_path, "import os\n")
    plugin.pylsp_lint(FakeConfig(mode="fast"), FakeWorkspace(), document, True)
    assert document.uri in plugin._STATE.documents
    plugin.pylsp_document_did_close(document=document)
    assert document.uri not in plugin._STATE.documents


def test_hybrid_publishes_worker_result_and_drops_stale_ones(tmp_path):
    config = FakeConfig(mode="hybrid", full_check="save", debounce=0.0)
    workspace = FakeWorkspace()
    document = make_document(tmp_path, "def f(a):\n    return a\n\n\nx = 1\n")
    workspace.documents[document.uri] = document

    class FakeWorker:
        def __init__(self):
            self.calls = []

        def stop(self):
            pass

        def lint(self, path, text, options, restricted, timeout):
            self.calls.append(restricted)
            from edulint.linters import Linter
            from edulint.linting.problem import Problem

            return [Problem(Linter.PYLINT, "default", path, 5, 0, "C0103", "invalid name", 5, 1, "invalid-name")]

    worker = FakeWorker()
    plugin._STATE.worker = worker

    plugin.pylsp_lint(config, workspace, document, False)  # not saved: no slow tier
    plugin._STATE.doc(document.uri)
    assert worker.calls == []

    plugin.pylsp_lint(config, workspace, document, True)
    plugin._STATE.doc(document.uri).timer.join()
    (uri, diagnostics, version), = workspace.published
    assert [(d["code"], d["source"]) for d in diagnostics] == [("C0103", "edulint/worker")]
    assert worker.calls == [True]

    # the buffer changes while the worker runs: the result is dropped
    workspace.published.clear()
    stale_document = make_document(tmp_path, "x = 1\n", version=2)
    workspace.documents[document.uri] = types.SimpleNamespace(**{**vars(stale_document), "source": "x = 2\n"})
    plugin.pylsp_lint(config, workspace, stale_document, True)
    plugin._STATE.doc(document.uri).timer.join()
    assert workspace.published == []
