import asyncio
import logging
from urllib.parse import urlparse

import httpx
import trafilatura
from curl_cffi.requests import AsyncSession
from pydantic import BaseModel

from . import cache
from .config import get_settings
from .schemas import SearchHit

log = logging.getLogger(__name__)

MIN_CHARS = 250
BINARY_EXTENSIONS = {
    ".zip", ".gz", ".tar", ".rar", ".7z", ".exe", ".dmg", ".iso",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav",
}
BLOCK_MARKERS = (
    "just a moment...",
    "attention required! | cloudflare",
    "cf-browser-verification",
    "enable javascript and cookies to continue",
    "checking your browser before accessing",
    "verify you are human",
)


class ExtractionResult(BaseModel):
    text: str
    tier: str  # tier1_trafilatura | tier2_jina | snippet_only
    cached: bool = False


def is_valid_content(text: str | None) -> bool:
    """Anti-bot validation gate: long enough and not a challenge page."""
    if not text or len(text) < MIN_CHARS:
        return False
    head = text[:2000].lower()
    return not any(m in head for m in BLOCK_MARKERS)


def _extension(url: str) -> str:
    path = urlparse(url).path.lower()
    return path[path.rfind("."):] if "." in path.rsplit("/", 1)[-1] else ""


async def extract_tier1(url: str, session: AsyncSession | None = None) -> str | None:
    s = get_settings()
    if session is None:
        async with AsyncSession(impersonate="chrome") as own:
            r = await own.get(url, timeout=s.tier1_timeout_sec, allow_redirects=True)
    else:
        r = await session.get(url, timeout=s.tier1_timeout_sec, allow_redirects=True)
    if r.status_code != 200:
        return None
    text = await asyncio.to_thread(
        trafilatura.extract,
        r.text,
        output_format="markdown",
        include_tables=True,
        include_links=False,
        favor_precision=True,
    )
    return text if is_valid_content(text) else None


async def extract_tier2(url: str, client: httpx.AsyncClient | None = None) -> str | None:
    s = get_settings()
    headers = {"X-Return-Format": "markdown"}
    if s.jina_api_key:
        headers["Authorization"] = f"Bearer {s.jina_api_key}"
    jina_url = f"https://r.jina.ai/{url}"
    if client is None:
        async with httpx.AsyncClient(follow_redirects=True) as own:
            r = await own.get(jina_url, headers=headers, timeout=s.tier2_timeout_sec)
    else:
        r = await client.get(jina_url, headers=headers, timeout=s.tier2_timeout_sec)
    if r.status_code != 200:
        return None
    return r.text if is_valid_content(r.text) else None


def _tiers(url: str, session: AsyncSession | None, client: httpx.AsyncClient | None):
    """(name, coroutine factory, timeout) for each tier that applies to this URL."""
    s = get_settings()
    tiers = []
    if _extension(url) != ".pdf":  # Jina reads PDFs; skip the HTML parser for them
        tiers.append(("tier1_trafilatura", lambda: extract_tier1(url, session=session), s.tier1_timeout_sec + 1))
    tiers.append(("tier2_jina", lambda: extract_tier2(url, client=client), s.tier2_timeout_sec + 1))
    return tiers


async def _cascade(
    url: str, session: AsyncSession | None = None, client: httpx.AsyncClient | None = None
) -> ExtractionResult | None:
    for name, attempt, timeout in _tiers(url, session, client):
        try:
            text = await asyncio.wait_for(attempt(), timeout=timeout)
        except Exception as e:
            log.info("%s failed for %s: %s: %s", name, url, type(e).__name__, e)
            continue
        if text:
            return ExtractionResult(text=text, tier=name)
    return None


async def extract_url_with_fallback(
    hit: SearchHit,
    bypass_cache: bool = False,
    session: AsyncSession | None = None,
    client: httpx.AsyncClient | None = None,
) -> ExtractionResult:
    """Never raises. Falls back to the search snippet if every tier fails."""
    snippet = ExtractionResult(text=hit.snippet, tier="snippet_only")
    if _extension(hit.url) in BINARY_EXTENSIONS:
        return snippet

    key = cache.make_key("url", hit.url)
    if not bypass_cache:
        cached = cache.url_get(key)
        if cached:
            return ExtractionResult(**cached).model_copy(update={"cached": True})

    try:
        result = await asyncio.wait_for(
            _cascade(hit.url, session, client), timeout=get_settings().global_scrape_timeout_sec
        )
    except Exception as e:
        log.info("extraction aborted for %s: %s", hit.url, type(e).__name__)
        result = None

    if result is None:
        return snippet
    cache.url_set(key, result.model_dump())
    return result


async def extract_many(
    hits: list[SearchHit], bypass_cache: bool = False
) -> list[ExtractionResult]:
    """Read every hit concurrently, sharing one browser-like session and one Jina client so
    pages fetched in the same search reuse connections instead of a new handshake each."""
    async with AsyncSession(impersonate="chrome") as session, httpx.AsyncClient(follow_redirects=True) as client:
        return await asyncio.gather(
            *(extract_url_with_fallback(h, bypass_cache, session, client) for h in hits)
        )
