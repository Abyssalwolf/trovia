"""Check that an API key works. Used by the setup wizard and `trovia doctor`."""

from dataclasses import dataclass
from typing import Literal

import httpx

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
SERPER_URL = "https://google.serper.dev/search"


@dataclass
class KeyCheck:
    status: Literal["valid", "invalid", "unknown"]
    detail: str = ""


def _classify(code: int, rejected: set[int]) -> KeyCheck:
    if code == 200:
        return KeyCheck("valid")
    if code in rejected:
        return KeyCheck("invalid", f"the provider answered HTTP {code}")
    if code == 429:
        return KeyCheck("valid", "recognised, but the provider says you are out of quota or rate-limited")
    return KeyCheck("unknown", f"unexpected HTTP {code}")


def check_brave(key: str, timeout: float = 10.0) -> KeyCheck:
    """Makes one real search, so it uses one query of the key's quota."""
    try:
        r = httpx.get(
            BRAVE_URL,
            params={"q": "test", "count": 1},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        return KeyCheck("unknown", f"could not reach Brave ({type(e).__name__})")
    return _classify(r.status_code, {401, 403, 422})


def check_serper(key: str, timeout: float = 10.0) -> KeyCheck:
    """Makes one real search, so it uses one credit."""
    try:
        r = httpx.post(SERPER_URL, json={"q": "test", "num": 1}, headers={"X-API-KEY": key}, timeout=timeout)
    except httpx.HTTPError as e:
        return KeyCheck("unknown", f"could not reach Serper ({type(e).__name__})")
    return _classify(r.status_code, {401, 403})
