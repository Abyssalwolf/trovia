import httpx
import respx

from trovia import cache
from trovia.discovery import BRAVE_URL, SERPER_URL, get_search_hits

SEARXNG = "http://searxng.test/search"
SERPER_OK = {"organic": [{"title": "A", "link": "https://a.com", "snippet": "sa"}]}
SEARXNG_OK = {"results": [{"title": "B", "url": "https://b.com", "content": "sb"}]}


@respx.mock
async def test_invalid_brave_key_falls_back_to_serper():
    respx.get(BRAVE_URL).respond(401)
    respx.post(SERPER_URL).respond(200, json=SERPER_OK)
    hits, provider = await get_search_hits("q")
    assert provider == "serper"
    assert hits[0].url == "https://a.com"


@respx.mock
async def test_brave_and_serper_fail_falls_back_to_searxng():
    respx.get(BRAVE_URL).respond(429)
    respx.post(SERPER_URL).respond(500)
    respx.get(SEARXNG).respond(200, json=SEARXNG_OK)
    hits, provider = await get_search_hits("q")
    assert provider == "searxng"
    assert hits[0].source_engine == "searxng"


@respx.mock
async def test_timeout_falls_back():
    respx.get(BRAVE_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
    respx.post(SERPER_URL).respond(200, json=SERPER_OK)
    _, provider = await get_search_hits("q")
    assert provider == "serper"


@respx.mock
async def test_all_fail_returns_empty_without_raising():
    respx.get(BRAVE_URL).respond(500)
    respx.post(SERPER_URL).respond(500)
    respx.get(SEARXNG).respond(500)
    hits, provider = await get_search_hits("q")
    assert (hits, provider) == ([], "none")


@respx.mock
async def test_providers_without_keys_are_skipped(monkeypatch):
    from trovia.config import get_settings

    monkeypatch.setenv("BRAVE_API_KEY", "")
    monkeypatch.setenv("SERPER_API_KEY", "")
    get_settings.cache_clear()
    brave = respx.get(BRAVE_URL).respond(200, json={})
    respx.get(SEARXNG).respond(200, json=SEARXNG_OK)
    _, provider = await get_search_hits("q")
    assert provider == "searxng"
    assert not brave.called


@respx.mock
async def test_brave_monthly_limit_skips_brave(monkeypatch):
    from trovia.config import get_settings

    monkeypatch.setenv("BRAVE_MONTHLY_LIMIT", "1")
    get_settings.cache_clear()
    cache.incr_monthly("brave")
    brave = respx.get(BRAVE_URL).respond(200, json={})
    respx.post(SERPER_URL).respond(200, json=SERPER_OK)
    _, provider = await get_search_hits("q")
    assert provider == "serper"
    assert not brave.called


@respx.mock
async def test_second_call_is_served_from_cache_and_key_includes_max_results():
    route = respx.post(SERPER_URL).respond(200, json=SERPER_OK)
    respx.get(BRAVE_URL).respond(500)
    await get_search_hits("q", 5)
    await get_search_hits("q", 5)
    assert route.call_count == 1
    await get_search_hits("q", 3)
    assert route.call_count == 2


@respx.mock
async def test_results_are_deduplicated_and_capped():
    dup = {"organic": [{"title": "A", "link": "https://a.com/"}, {"title": "A2", "link": "https://a.com"}, {"title": "C", "link": "https://c.com"}]}
    respx.get(BRAVE_URL).respond(500)
    respx.post(SERPER_URL).respond(200, json=dup)
    hits, _ = await get_search_hits("q", 2)
    assert [h.url for h in hits] == ["https://a.com/", "https://c.com"]


DDGS_OK = [
    {"title": "D1", "href": "https://d1.com", "body": "body one"},
    {"title": "D2", "href": "https://d2.com", "body": "body two"},
]


def _no_keys_no_searxng(monkeypatch):
    from trovia.config import get_settings

    monkeypatch.setenv("BRAVE_API_KEY", "")
    monkeypatch.setenv("SERPER_API_KEY", "")
    monkeypatch.setenv("SEARXNG_URL", "")
    get_settings.cache_clear()


@respx.mock
async def test_with_no_keys_and_no_searxng_duckduckgo_is_used(monkeypatch):
    from trovia import discovery

    _no_keys_no_searxng(monkeypatch)
    monkeypatch.setattr(discovery, "_ddgs_text", lambda q, n, t: DDGS_OK)
    hits, provider = await get_search_hits("q")
    assert provider == "ddgs"
    assert [(h.title, h.url, h.snippet, h.source_engine) for h in hits][0] == ("D1", "https://d1.com", "body one", "ddgs")
    assert len(respx.calls) == 0  # no HTTP provider was contacted


@respx.mock
async def test_searxng_is_skipped_when_no_url_is_configured(monkeypatch):
    from trovia import discovery

    _no_keys_no_searxng(monkeypatch)
    searx = respx.get(SEARXNG).respond(200, json=SEARXNG_OK)
    monkeypatch.setattr(discovery, "_ddgs_text", lambda q, n, t: DDGS_OK)
    _, provider = await get_search_hits("q")
    assert provider == "ddgs" and not searx.called


@respx.mock
async def test_searxng_is_preferred_over_duckduckgo_when_configured(monkeypatch):
    from trovia import discovery

    respx.get(BRAVE_URL).respond(500)
    respx.post(SERPER_URL).respond(500)
    respx.get(SEARXNG).respond(200, json=SEARXNG_OK)
    called = []
    monkeypatch.setattr(discovery, "_ddgs_text", lambda q, n, t: called.append(1) or DDGS_OK)
    _, provider = await get_search_hits("q")
    assert provider == "searxng" and not called


@respx.mock
async def test_duckduckgo_is_the_last_resort_when_everything_else_fails(monkeypatch):
    from trovia import discovery

    respx.get(BRAVE_URL).respond(500)
    respx.post(SERPER_URL).respond(500)
    respx.get(SEARXNG).respond(500)
    monkeypatch.setattr(discovery, "_ddgs_text", lambda q, n, t: DDGS_OK)
    _, provider = await get_search_hits("q")
    assert provider == "ddgs"


@respx.mock
async def test_duckduckgo_failure_returns_empty_without_raising(monkeypatch):
    _no_keys_no_searxng(monkeypatch)  # the default fixture makes ddgs raise
    hits, provider = await get_search_hits("q")
    assert (hits, provider) == ([], "none")


@respx.mock
async def test_duckduckgo_results_without_a_url_are_dropped(monkeypatch):
    from trovia import discovery

    _no_keys_no_searxng(monkeypatch)
    monkeypatch.setattr(discovery, "_ddgs_text", lambda q, n, t: [{"title": "x", "body": "y"}] + DDGS_OK)
    hits, _ = await get_search_hits("q")
    assert [h.url for h in hits] == ["https://d1.com", "https://d2.com"]


def test_active_providers_lists_only_configured_ones_in_order(monkeypatch):
    from trovia.config import get_settings
    from trovia.discovery import active_providers

    monkeypatch.setenv("BRAVE_API_KEY", "")
    monkeypatch.setenv("PROVIDER_ORDER", "serper,typo,brave,searxng,ddgs")
    get_settings.cache_clear()
    assert active_providers(get_settings()) == ["serper", "searxng", "ddgs"]


def test_brave_monthly_cap_holds_with_many_concurrent_callers(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from trovia import discovery
    from trovia.config import get_settings

    monkeypatch.setenv("BRAVE_MONTHLY_LIMIT", "5")
    get_settings.cache_clear()
    s = get_settings()
    with ThreadPoolExecutor(16) as pool:
        granted = list(pool.map(lambda _: discovery._reserve_brave_call(s), range(40)))
    assert granted.count(True) == 5
