import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from diskcache import Cache

from .config import get_settings

_caches: dict[str, Cache] = {}


def _cache(namespace: str) -> Cache:
    if namespace not in _caches:
        path = Path(get_settings().cache_dir) / namespace
        path.mkdir(parents=True, exist_ok=True)
        _caches[namespace] = Cache(str(path))
    return _caches[namespace]


def make_key(*parts: Any) -> str:
    """Stable hash of every parameter that changes the output."""
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def serp_get(key: str) -> Any | None:
    return _cache("serp").get(key)


def serp_set(key: str, value: Any) -> None:
    _cache("serp").set(key, value, expire=get_settings().serp_cache_ttl_sec)


def url_get(key: str) -> Any | None:
    return _cache("url").get(key)


def url_set(key: str, value: Any) -> None:
    _cache("url").set(key, value, expire=get_settings().url_cache_ttl_sec)


def incr_monthly(name: str) -> int:
    """Increment and return this calendar month's counter for `name`."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return _cache("usage").incr(f"{name}:{month}", default=0)


def get_monthly(name: str) -> int:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return _cache("usage").get(f"{name}:{month}", 0)


def close_all() -> None:
    for c in _caches.values():
        c.close()
    _caches.clear()
