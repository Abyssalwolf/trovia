import asyncio

import pytest

from trovia import extractor
from trovia.extractor import extract_url_with_fallback, is_valid_content
from trovia.schemas import SearchHit

GOOD = "word " * 100


def hit(url="https://example.com/post", snippet="the snippet"):
    return SearchHit(title="t", url=url, snippet=snippet, source_engine="test")


@pytest.fixture
def tiers(monkeypatch):
    calls = []

    def install(t1=None, t2=None):
        async def make(name, val):
            calls.append(name)
            if isinstance(val, Exception):
                raise val
            if callable(val):
                return await val()
            return val

        monkeypatch.setattr(extractor, "extract_tier1", lambda u, **kw: make("t1", t1))
        monkeypatch.setattr(extractor, "extract_tier2", lambda u, **kw: make("t2", t2))
        return calls

    return install


def test_validation_gate():
    assert is_valid_content(GOOD)
    assert not is_valid_content("short")
    assert not is_valid_content(None)
    assert not is_valid_content("Just a moment... " + GOOD)
    assert not is_valid_content("Attention Required! | Cloudflare " + GOOD)


async def test_tier1_success_skips_other_tiers(tiers):
    calls = tiers(t1=GOOD)
    r = await extract_url_with_fallback(hit())
    assert r.tier == "tier1_trafilatura" and calls == ["t1"]


async def test_falls_to_tier2_when_tier1_fails(tiers):
    calls = tiers(t1=None, t2=GOOD)
    r = await extract_url_with_fallback(hit())
    assert r.tier == "tier2_jina" and calls == ["t1", "t2"]


async def test_exceptions_in_every_tier_return_snippet(tiers):
    tiers(t1=RuntimeError("x"), t2=ValueError("y"))
    r = await extract_url_with_fallback(hit())
    assert r.tier == "snippet_only" and r.text == "the snippet"


async def test_global_timeout_returns_snippet(tiers, monkeypatch):
    async def hang():
        await asyncio.sleep(30)

    tiers(t1=hang)
    monkeypatch.setenv("GLOBAL_SCRAPE_TIMEOUT_SEC", "0.2")
    from trovia.config import get_settings

    get_settings.cache_clear()
    r = await extract_url_with_fallback(hit())
    assert r.tier == "snippet_only"


async def test_success_is_cached_failure_is_not(tiers):
    calls = tiers(t1=GOOD)
    await extract_url_with_fallback(hit())
    r = await extract_url_with_fallback(hit())
    assert r.cached and calls == ["t1"]

    calls = tiers(t1=None, t2=None)
    await extract_url_with_fallback(hit("https://fail.example/x"))
    await extract_url_with_fallback(hit("https://fail.example/x"))
    # one tier-1 hit from the cached success above, then two full misses
    assert calls == ["t1", "t1", "t2", "t1", "t2"]


async def test_binary_extension_skipped(tiers):
    calls = tiers(t1=GOOD)
    r = await extract_url_with_fallback(hit("https://example.com/file.zip"))
    assert r.tier == "snippet_only" and calls == []


async def test_pdf_goes_straight_to_tier2(tiers):
    calls = tiers(t1=GOOD, t2=GOOD)
    r = await extract_url_with_fallback(hit("https://example.com/paper.pdf"))
    assert r.tier == "tier2_jina" and calls == ["t2"]


async def test_one_search_shares_a_single_session_and_jina_client(monkeypatch):
    from trovia.extractor import extract_many

    seen = {"session": set(), "client": set()}

    async def t1(url, session=None):
        seen["session"].add(id(session))
        assert session is not None
        return None  # force the Jina tier too

    async def t2(url, client=None):
        seen["client"].add(id(client))
        assert client is not None
        return GOOD

    monkeypatch.setattr(extractor, "extract_tier1", t1)
    monkeypatch.setattr(extractor, "extract_tier2", t2)
    results = await extract_many([hit(f"https://s{i}.example/p") for i in range(5)], bypass_cache=True)
    assert [r.tier for r in results] == ["tier2_jina"] * 5
    assert len(seen["session"]) == 1 and len(seen["client"]) == 1
