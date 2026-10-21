"""`trovia doctor`: check that the install, config and providers actually work."""

import socket
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import keys
from .config import config_path, data_dir, get_settings


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str = ""


def _folder_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("x")
        probe.unlink()
        return True
    except OSError:
        return False


def _key_check(name: str, key: str, check) -> Check:
    if not key:
        return Check(name, "warn", "no key set (skipped)")
    result = check(key)
    if result.status == "valid":
        return Check(name, "ok", "key works" + (f" ({result.detail})" if result.detail else ""))
    if result.status == "invalid":
        return Check(name, "fail", f"key rejected ({result.detail}); run `trovia config`")
    return Check(name, "warn", f"could not check the key: {result.detail}")


def _searxng_check(url: str) -> Check:
    if not url:
        return Check("SearXNG", "ok", "not enabled (optional)")
    try:
        r = httpx.get(url, params={"q": "test", "format": "json"}, timeout=8)
        if r.status_code == 200 and "results" in r.json():
            return Check("SearXNG", "ok", f"answering at {url}")
        return Check("SearXNG", "fail", f"{url} answered HTTP {r.status_code} (is JSON output enabled?)")
    except (httpx.HTTPError, ValueError) as e:
        return Check("SearXNG", "fail", f"cannot use {url}: {type(e).__name__}")


def _duckduckgo_check() -> Check:
    from . import discovery

    s = get_settings()
    try:
        results = discovery._ddgs_text("test", 1, s.ddgs_timeout_sec)
        return Check("DuckDuckGo", "ok", "returned results") if results else Check("DuckDuckGo", "warn", "returned nothing")
    except Exception as e:
        return Check("DuckDuckGo", "warn", f"search failed ({type(e).__name__}); it may be rate-limited right now")


def _port_check(host: str, port: int) -> Check:
    with socket.socket() as sock:
        sock.settimeout(1)
        if sock.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", port)) != 0:
            return Check("Port", "ok", f"{port} is free")
    try:
        if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).json().get("status") == "ok":
            return Check("Port", "ok", f"Trovia is already running on port {port}")
    except (httpx.HTTPError, ValueError):
        pass
    return Check("Port", "fail", f"port {port} is used by another program; run `trovia config set port 8001`")


def run_checks(check_brave=None, check_serper=None) -> list[Check]:
    check_brave = check_brave or keys.check_brave
    check_serper = check_serper or keys.check_serper
    s = get_settings()
    checks: list[Check] = []

    path = config_path()
    checks.append(Check("Config file", "ok", str(path)) if path.exists()
                  else Check("Config file", "warn", f"not created yet ({path}); run `trovia setup`"))

    folder = data_dir()
    checks.append(Check("Data folder", "ok", str(folder)) if _folder_writable(folder)
                  else Check("Data folder", "fail", f"cannot write to {folder}"))

    model = Path(s.models_dir) / s.rerank_model
    checks.append(Check("Reranker model", "ok", s.rerank_model) if model.exists()
                  else Check("Reranker model", "warn", "not downloaded yet; it downloads on first use (needs internet)"))

    if "brave" in s.providers:
        checks.append(_key_check("Brave", s.brave_api_key, check_brave))
    if "serper" in s.providers:
        checks.append(_key_check("Serper", s.serper_api_key, check_serper))
    if "searxng" in s.providers:
        checks.append(_searxng_check(s.searxng_url))
    if "ddgs" in s.providers:
        checks.append(_duckduckgo_check())

    checks.append(Check("Jina", "ok", "key set") if s.jina_api_key
                  else Check("Jina", "ok", "no key (limited to about 20 requests a minute)"))
    checks.append(_port_check(s.host, s.port))
    return checks
