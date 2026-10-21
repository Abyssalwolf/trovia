from pathlib import Path

import pytest

from trovia import cache
from trovia.config import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    # Never read or write the real user's config or data.
    monkeypatch.setenv("TROVIA_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TROVIA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    # Reuse the already-downloaded reranker model instead of fetching it per test run.
    monkeypatch.setenv("MODELS_DIR", str(Path(__file__).resolve().parent.parent / "data" / "models"))
    monkeypatch.setenv("BRAVE_API_KEY", "invalid-brave-key")
    monkeypatch.setenv("SERPER_API_KEY", "serper-key")
    monkeypatch.setenv("SEARXNG_URL", "http://searxng.test/search")
    monkeypatch.setenv("WARMUP", "false")
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
    # Tests must never reach the real DuckDuckGo; individual tests override this.
    from trovia import discovery

    def no_network(query, n, timeout):
        raise RuntimeError("ddgs blocked in tests")

    monkeypatch.setattr(discovery, "_ddgs_text", no_network)
    get_settings.cache_clear()
    cache.close_all()
    yield
    cache.close_all()
    get_settings.cache_clear()
