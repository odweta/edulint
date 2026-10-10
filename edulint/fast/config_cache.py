"""
Cheaper repeated configuration loading for long-running processes.

``install()`` patches three functions of :mod:`edulint.config.config`:

* ``parse_config_file`` is memoised by path and modification time (including
  the base configuration files it was derived from),
* ``extract_args`` can read in-file ``# edulint:`` options from an unsaved
  buffer (see :func:`buffer_override`),
* ``search_for_config_in_parents`` tolerates files that do not exist on disk.

The EduLint CLI never calls ``install()``, so its behaviour is unchanged.
"""

import io
import os
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

from edulint.config import config as config_module
from edulint.config.file_config import ConfigFileType, get_config_type

Stamp = Tuple[int, int]

_local = threading.local()
_cache: Dict[Tuple[str, int], Tuple[Tuple[Tuple[str, Optional[Stamp]], ...], Any]] = {}
_installed = False
_originals: Dict[str, Any] = {}
stats = {"hits": 0, "misses": 0}


def _stamp(path: str) -> Optional[Stamp]:
    """Modification stamp of a config file, or None if it cannot be cached (remote, missing)."""
    config_type = get_config_type(path)
    if config_type == ConfigFileType.REMOTE:
        return None
    if config_type == ConfigFileType.PACKAGED:
        path = os.path.join(os.path.dirname(config_module.__file__), "files", path + ".toml")
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _caching_parse_config_file(path: str, option_parses: Any) -> Any:
    key = (path, id(option_parses))
    entry = _cache.get(key)
    if entry is not None and all(_stamp(p) == s for p, s in entry[0]):
        stats["hits"] += 1
        parent = getattr(_local, "deps_stack", None)
        if parent:
            parent[-1].extend(entry[0])
        return entry[1]

    stats["misses"] += 1
    stack: List[List[Tuple[str, Optional[Stamp]]]] = _local.__dict__.setdefault("deps_stack", [])
    stack.append([(path, _stamp(path))])
    try:
        result = _originals["parse_config_file"](path, option_parses)
    finally:
        deps = stack.pop()
    if stack:
        stack[-1].extend(deps)
    if result is not None and all(s is not None for _p, s in deps):
        _cache[key] = (tuple(deps), result)
    return result


def _overriding_extract_args(path: str) -> List[str]:
    overrides = getattr(_local, "overrides", None)
    if overrides:
        text = overrides.get(os.path.abspath(path))
        if text is not None:
            return config_module.extract_args_from_lines(io.StringIO(text, newline=None))
    return _originals["extract_args"](path)


def _safe_search_for_config_in_parents(path: str) -> Optional[str]:
    try:
        return _originals["search_for_config_in_parents"](path)
    except OSError:
        return None


def install() -> None:
    """Idempotently installs the patches in this process."""
    global _installed
    if _installed:
        return
    for name, replacement in (
        ("parse_config_file", _caching_parse_config_file),
        ("extract_args", _overriding_extract_args),
        ("search_for_config_in_parents", _safe_search_for_config_in_parents),
    ):
        _originals[name] = getattr(config_module, name)
        setattr(config_module, name, replacement)
    _installed = True


def uninstall() -> None:
    """Removes the patches (used by tests)."""
    global _installed
    if not _installed:
        return
    for name, original in _originals.items():
        setattr(config_module, name, original)
    _originals.clear()
    _installed = False
    clear()


def clear() -> None:
    _cache.clear()
    stats["hits"] = stats["misses"] = 0


@contextmanager
def buffer_override(path: str, text: Optional[str]) -> Iterator[None]:
    """Makes in-file option extraction for ``path`` use ``text`` instead of the file on disk."""
    install()
    if text is None:
        yield
        return
    overrides = _local.__dict__.setdefault("overrides", {})
    key = os.path.abspath(path)
    previous = overrides.get(key)
    overrides[key] = text
    try:
        yield
    finally:
        if previous is None:
            overrides.pop(key, None)
        else:
            overrides[key] = previous
