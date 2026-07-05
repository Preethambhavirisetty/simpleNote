from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from typing import Any, Callable


_MAX_GRAPH_ENTRIES = 16
_MAX_PROVIDER_ENTRIES = 32

_graph_cache: OrderedDict[str, tuple[Any, Any]] = OrderedDict()
_provider_cache: OrderedDict[str, Any] = OrderedDict()
_lock = RLock()


def _set_lru_entry(cache: OrderedDict[str, Any], key: str, value: Any, *, max_entries: int) -> Any:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > max_entries:
        _old_key, old_value = cache.popitem(last=False)
        _close_cached_value(old_value)
    return value


def get_or_create_graph(
    signature: str,
    builder: Callable[[], tuple[Any, Any]],
) -> tuple[Any, Any]:
    with _lock:
        if signature in _graph_cache:
            value = _graph_cache.pop(signature)
            _graph_cache[signature] = value
            return value
    graph, checkpointer = builder()
    with _lock:
        if signature in _graph_cache:
            _close_cached_value((graph, checkpointer))
            value = _graph_cache.pop(signature)
            _graph_cache[signature] = value
            return value
        return _set_lru_entry(
            _graph_cache,
            signature,
            (graph, checkpointer),
            max_entries=_MAX_GRAPH_ENTRIES,
        )


def get_or_create_provider(
    signature: str,
    kind: str,
    builder: Callable[[], Any],
) -> Any:
    key = f"{signature}:{kind}"
    with _lock:
        if key in _provider_cache:
            value = _provider_cache.pop(key)
            _provider_cache[key] = value
            return value
    provider = builder()
    with _lock:
        if key in _provider_cache:
            _close_cached_value(provider)
            value = _provider_cache.pop(key)
            _provider_cache[key] = value
            return value
        return _set_lru_entry(_provider_cache, key, provider, max_entries=_MAX_PROVIDER_ENTRIES)


def clear_engine_caches() -> None:
    with _lock:
        for value in _graph_cache.values():
            _close_cached_value(value)
        for value in _provider_cache.values():
            _close_cached_value(value)
        _graph_cache.clear()
        _provider_cache.clear()


def _close_cached_value(value: Any) -> None:
    values = value if isinstance(value, tuple) else (value,)
    for item in values:
        close = getattr(item, "close", None)
        if callable(close):
            close()
