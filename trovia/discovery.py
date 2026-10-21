import asyncio
import logging

import httpx

from . import cache
from .config import Settings, get_settings
from .schemas import SearchHit

log = logging.getLogger(__name__)

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
SERPER_URL = "https://google.serper.dev/search"


def _reserve_brave_call(s: Settings) -> bool:
    """Count one Brave call and say whether it is within the monthly limit. The increment is
    atomic in diskcache, so the REST service and an MCP server sharing the cache can't both take
    the last remaining call."""
    return cache.incr_monthly("brave") <= s.brave_monthly_limit


async def _brave(client: httpx.AsyncClient, query: str, n: int, s: Settings) -> list[SearchHit]:
    if not _reserve_brave_call(s):
        raise RuntimeError("brave monthly credit limit reached")
    r = await client.get(
        BRAVE_URL,
        params={"q": query, "count": min(n, 20)},
        headers={"X-Subscription-Token": s.brave_api_key, "Accept": "application/json"},
        timeout=s.brave_timeout_sec,
    )
    r.raise_for_status()
    items = r.json().get("web", {}).get("results", [])
    return [
        SearchHit(
            title=i.get("title", ""),
            url=i["url"],
            snippet=i.get("description", ""),
            published_date=i.get("page_age"),
            source_engine="brave",
        )
        for i in items
        if i.get("url")
    ]


async def _serper(client: httpx.AsyncClient, query: str, n: int, s: Settings) -> list[SearchHit]:
    r = await client.post(
        SERPER_URL,
        json={"q": query, "num": n},
        headers={"X-API-KEY": s.serper_api_key},
        timeout=s.serper_timeout_sec,
    )
    r.raise_for_status()
    items = r.json().get("organic", [])
    return [
        SearchHit(
            title=i.get("title", ""),
            url=i["link"],
            snippet=i.get("snippet", ""),
            published_date=i.get("date"),
            source_engine="serper",
        )
        for i in items
        if i.get("link")
    ]


async def _searxng(client: httpx.AsyncClient, query: str, n: int, s: Settings) -> list[SearchHit]:
    r = await client.get(
        s.searxng_url,
        params={"q": query, "format": "json"},
        timeout=s.searxng_timeout_sec,
    )
    r.raise_for_status()
    items = r.json().get("results", [])
    return [
        SearchHit(
            title=i.get("title", ""),
            url=i["url"],
            snippet=i.get("content", ""),
            published_date=i.get("publishedDate"),
            source_engine="searxng",
        )
        for i in items
        if i.get("url")
    ]


def _ddgs_text(query: str, n: int, timeout: float) -> list[dict]:
    from ddgs import DDGS  # imported here so the dependency loads only when used

    return DDGS(timeout=int(timeout)).text(query, max_results=n)


async def _ddgs(client: httpx.AsyncClient, query: str, n: int, s: Settings) -> list[SearchHit]:
    """Keyless DuckDuckGo search. Best-effort: it can be rate-limited."""
    items = await asyncio.wait_for(
        asyncio.to_thread(_ddgs_text, query, n, s.ddgs_timeout_sec),
        timeout=s.ddgs_timeout_sec + 2,
    )
    return [
        SearchHit(title=i.get("title", ""), url=i["href"], snippet=i.get("body", ""), source_engine="ddgs")
        for i in items
        if i.get("href")
    ]


_PROVIDERS = {"brave": _brave, "serper": _serper, "searxng": _searxng, "ddgs": _ddgs}


def _configured(name: str, s: Settings) -> bool:
    if name == "brave":
        return bool(s.brave_api_key)
    if name == "serper":
        return bool(s.serper_api_key)
    if name == "searxng":
        return bool(s.searxng_url)  # opt-in: only when a SearXNG URL is set
    return name in _PROVIDERS  # ddgs needs no key


def active_providers(s: Settings) -> list[str]:
    """The providers that will actually be tried, in order (configured ones from provider_order)."""
    return [p for p in s.providers if _configured(p, s)]


def _dedupe(hits: list[SearchHit], limit: int) -> list[SearchHit]:
    seen: set[str] = set()
    out: list[SearchHit] = []
    for h in hits:
        key = h.url.rstrip("/")
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out[:limit]


async def get_search_hits(
    query: str,
    max_results: int = 5,
    bypass_cache: bool = False,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[SearchHit], str]:
    """Walk the provider cascade; never raises. Returns (hits, provider_used)."""
    s = get_settings()
    providers = active_providers(s)
    key = cache.make_key("serp", query, max_results, providers)

    if not bypass_cache:
        cached = cache.serp_get(key)
        if cached:
            hits, provider = cached
            return [SearchHit(**h) for h in hits], provider

    own_client = client is None
    client = client or httpx.AsyncClient()
    try:
        for name in providers:
            try:
                hits = _dedupe(await _PROVIDERS[name](client, query, max_results, s), max_results)
            except Exception as e:  # any failure -> next provider
                log.warning("search provider %s failed: %s: %s", name, type(e).__name__, e)
                continue
            if hits:
                cache.serp_set(key, ([h.model_dump() for h in hits], name))
                return hits, name
            log.warning("search provider %s returned no results", name)
    finally:
        if own_client:
            await client.aclose()

    return [], "none"
