import os

import pytest

from edulint.config.config import get_config_many
from edulint.fast import config_cache
from edulint.options import Option


@pytest.fixture(autouse=True)
def cache():
    config_cache.uninstall()
    config_cache.install()
    yield config_cache
    config_cache.uninstall()


def write(path, text, mtime):
    path.write_text(text)
    os.utime(path, (mtime, mtime))


def test_config_files_are_parsed_once(tmp_path, cache):
    cfg = tmp_path / "my.toml"
    cfg.write_text("[pylint]\nenable = ['no-else-return']\n")
    src = tmp_path / "a.py"
    src.write_text("x = 1\n")

    for _ in range(3):
        configs = get_config_many([str(src)], [f"config-file={cfg}"])
    assert len(configs) == 1
    assert cache.stats["misses"] == 2  # my.toml and the default.toml it is based on
    assert cache.stats["hits"] >= 2


def test_cache_is_invalidated_by_modification_time(tmp_path, cache):
    cfg = tmp_path / "my.toml"
    write(cfg, "[flake8]\nselect = ['E501']\n", 1_000_000)
    src = tmp_path / "a.py"
    src.write_text("x = 1\n")

    args = [f"config-file={cfg}"]
    first = get_config_many([str(src)], args)[0][1]
    write(cfg, "[flake8]\nselect = ['W291']\n", 2_000_000)
    second = get_config_many([str(src)], args)[0][1]

    assert "--select=E501" in first[Option.FLAKE8]
    assert "--select=W291" in second[Option.FLAKE8]


def test_cache_is_invalidated_by_base_file_modification(tmp_path, cache):
    base = tmp_path / "base.toml"
    child = tmp_path / "child.toml"
    write(base, "[flake8]\nselect = ['E501']\n", 1_000_000)
    child.write_text("config-file = 'base.toml'\n")
    src = tmp_path / "a.py"
    src.write_text("x = 1\n")

    args = [f"config-file={child}"]
    assert "--select=E501" in get_config_many([str(src)], args)[0][1][Option.FLAKE8]
    write(base, "[flake8]\nselect = ['W291']\n", 2_000_000)
    assert "--select=W291" in get_config_many([str(src)], args)[0][1][Option.FLAKE8]


def test_cached_result_equals_uncached_result(tmp_path):
    src = tmp_path / "a.py"
    src.write_text("# edulint: config-file=cs1\nx = 1\n")
    config_cache.uninstall()
    plain = get_config_many([str(src)], [])
    config_cache.install()
    cached = get_config_many([str(src)], [])
    cached_again = get_config_many([str(src)], [])
    assert [c for _p, c, _t in plain] == [c for _p, c, _t in cached] == [c for _p, c, _t in cached_again]


def test_buffer_override_replaces_in_file_options(tmp_path, cache):
    src = tmp_path / "a.py"
    src.write_text("x = 1\n")
    with cache.buffer_override(str(src), "# edulint: flake8=--max-line-length=10\n"):
        (_p, config, _t), = get_config_many([str(src)], [])
    assert "--max-line-length=10" in config[Option.FLAKE8]
    (_p, config, _t), = get_config_many([str(src)], [])
    assert "--max-line-length=10" not in config[Option.FLAKE8]


def test_file_that_does_not_exist_gets_a_config(tmp_path, cache):
    new = str(tmp_path / "new.py")
    with cache.buffer_override(new, "# edulint: flake8=--max-line-length=10\n"):
        (_p, config, _t), = get_config_many([new], [])
    assert "--max-line-length=10" in config[Option.FLAKE8]
