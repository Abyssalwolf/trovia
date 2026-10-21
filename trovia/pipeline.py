import logging
import time

from . import cache
from .config import get_settings
from .discovery import active_providers, get_search_hits
from .extractor import extract_many
from .reranker import build_chunks, format_context, rerank_async
from .schemas import SearchRequest, SearchResponse, SearchResultItem

log = logging.getLogger(__name__)

ADVANCED_MIN_URLS = 8


def _no_results_message() -> str:
    s = get_settings()
    message = "no search provider returned results"
    if not (s.brave_api_key or s.serper_api_key or s.searxng_url):
        message += (
            " (only DuckDuckGo is configured and it may be rate-limited; wait a minute,"
            " or add a Brave or Serper key with `trovia config`)"
        )
    return message


async def _run(req: SearchRequest) -> SearchResponse:
    advanced = req.search_depth == "advanced"
    n_urls = max(req.max_results, ADVANCED_MIN_URLS) if advanced else req.max_results
    settings = get_settings()
    top_k = req.top_k_chunks or settings.top_k_chunks * (2 if advanced else 1)
    rerank_cap = req.max_chunks_to_rerank or settings.max_chunks_to_rerank or None  # 0 = no cap

    hits, provider = await get_search_hits(req.query, n_urls, req.bypass_cache)
    if not hits:
        return SearchResponse(
            query=req.query, search_provider_used=provider, latency_ms=0,
            synthesized_context="", results=[], error=_no_results_message(),
        )

    extractions = await extract_many(hits, req.bypass_cache)
    pairs = build_chunks(hits, extractions)
    top = await rerank_async(
        req.query, pairs, top_k, req.max_chunks_per_url, rerank_cap
    )

    raw = None
    if req.include_raw_markdown:
        raw = {h.url: e.text for h, e in zip(hits, extractions) if e.tier != "snippet_only"}

    return SearchResponse(
        query=req.query,
        search_provider_used=provider,
        latency_ms=0,
        synthesized_context=format_context(top),
        results=[
            SearchResultItem(
                title=c.title, url=c.url, chunk_content=c.text, relevance_score=c.score,
                extraction_tier=c.extraction_tier, is_snippet=c.is_snippet, cached=c.cached,
            )
            for c in top
        ],
        raw_markdown=raw,
    )


async def run_search(req: SearchRequest) -> SearchResponse:
    """Full pipeline. Never raises; failures come back in `error`."""
    start = time.perf_counter()

    # Whole-response cache: keyed on every parameter that changes the output.
    s = get_settings()
    key = cache.make_key(
        "resp",
        req.model_dump(exclude={"bypass_cache"}),
        # user defaults and the providers in use also shape the output, so changing them
        # (e.g. adding a Brave key) never serves a response built under the old setup
        s.top_k_chunks, s.max_chunks_to_rerank, s.max_chunks_per_url, active_providers(s),
    )
    if not req.bypass_cache:
        cached = cache.serp_get(key)
        if cached:
            resp = SearchResponse(**cached)
            resp.latency_ms = int((time.perf_counter() - start) * 1000)
            for r in resp.results:
                r.cached = True
            return resp

    try:
        resp = await _run(req)
    except Exception as e:
        log.exception("pipeline failed")
        resp = SearchResponse(
            query=req.query, search_provider_used="none", latency_ms=0,
            synthesized_context="", results=[], error=f"{type(e).__name__}: {e}",
        )

    if resp.results and not resp.error:
        cache.serp_set(key, resp.model_dump())
    resp.latency_ms = int((time.perf_counter() - start) * 1000)
    return resp
