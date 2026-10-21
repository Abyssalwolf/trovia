import pytest
from fastapi.testclient import TestClient

from trovia import pipeline
from trovia.extractor import ExtractionResult
from trovia.main import app
from trovia.mcp_server import web_search
from trovia.schemas import SearchHit, SearchRequest

BODY = ("Using a blocking mutex inside async code is fine when contention is low. " * 8 + "\n\n") * 4


@pytest.fixture
def fake(monkeypatch):
    state = {"search": 0, "extract": 0}

    async def hits(query, n, bypass=False, client=None):
        state["search"] += 1
        state["n"] = n
        return [
            SearchHit(title=f"T{i}", url=f"https://s{i}.com/p", snippet=f"snippet {i} mutex", source_engine="searxng")
            for i in range(n)
        ], "searxng"

    async def extract(hs, bypass=False):
        state["extract"] += 1
        return [ExtractionResult(text=BODY, tier="tier1_trafilatura") for _ in hs]

    monkeypatch.setattr(pipeline, "get_search_hits", hits)
    monkeypatch.setattr(pipeline, "extract_many", extract)
    return state


async def test_end_to_end_response_shape(fake):
    resp = await pipeline.run_search(SearchRequest(query="rust async mutex"))
    assert resp.search_provider_used == "searxng"
    assert 0 < len(resp.results) <= 6
    assert resp.synthesized_context.startswith("## Source:")
    assert all(r.relevance_score is not None for r in resp.results)
    assert resp.raw_markdown is None and resp.error is None


async def test_second_identical_request_is_cached(fake):
    await pipeline.run_search(SearchRequest(query="q"))
    second = await pipeline.run_search(SearchRequest(query="q"))
    assert fake["search"] == 1
    assert all(r.cached for r in second.results)


async def test_cache_key_distinguishes_depth_and_bypass_skips_cache(fake):
    await pipeline.run_search(SearchRequest(query="q"))
    await pipeline.run_search(SearchRequest(query="q", search_depth="advanced"))
    assert fake["search"] == 2
    await pipeline.run_search(SearchRequest(query="q", bypass_cache=True))
    assert fake["search"] == 3


async def test_advanced_crawls_at_least_eight_urls_and_returns_more_chunks(fake):
    resp = await pipeline.run_search(SearchRequest(query="q", search_depth="advanced"))
    assert fake["n"] == 8
    assert len(resp.results) > 6


async def test_include_raw_markdown(fake):
    resp = await pipeline.run_search(SearchRequest(query="q", include_raw_markdown=True))
    assert resp.raw_markdown and len(resp.raw_markdown) == 5


async def test_no_hits_returns_error_not_exception(monkeypatch):
    async def none(*a, **k):
        return [], "none"

    monkeypatch.setattr(pipeline, "get_search_hits", none)
    resp = await pipeline.run_search(SearchRequest(query="q"))
    assert resp.results == [] and resp.error


async def test_unexpected_exception_is_contained(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(pipeline, "get_search_hits", boom)
    resp = await pipeline.run_search(SearchRequest(query="q"))
    assert resp.error and "kaboom" in resp.error


def test_rest_endpoints(fake):
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        r = client.post("/v1/search", json={"query": "rust async mutex", "top_k_chunks": 3})
        assert r.status_code == 200
        body = r.json()
        assert len(body["results"]) == 3 and "synthesized_context" in body
        assert client.post("/v1/search", json={"query": ""}).status_code == 422


async def test_request_options_reach_the_reranker(fake, monkeypatch):
    seen = {}

    async def spy(query, pairs, top_k, max_per_url=None, max_candidates=None):
        seen.update(top_k=top_k, per_url=max_per_url, cand=max_candidates)
        return []

    monkeypatch.setattr(pipeline, "rerank_async", spy)
    await pipeline.run_search(
        SearchRequest(query="q", top_k_chunks=3, max_chunks_per_url=1, max_chunks_to_rerank=20)
    )
    assert seen == {"top_k": 3, "per_url": 1, "cand": 20}


async def test_different_options_are_cached_separately(fake):
    await pipeline.run_search(SearchRequest(query="q"))
    await pipeline.run_search(SearchRequest(query="q", max_chunks_per_url=1))
    assert fake["search"] == 2


async def test_per_page_option_is_honoured_end_to_end(fake):
    resp = await pipeline.run_search(SearchRequest(query="mutex", max_chunks_per_url=1, top_k_chunks=20))
    urls = [r.url for r in resp.results]
    assert len(urls) == len(set(urls))


def test_rest_accepts_options_and_validates_them(fake):
    with TestClient(app) as client:
        ok = client.post("/v1/search", json={"query": "q", "top_k_chunks": 2, "max_chunks_to_rerank": 10, "max_chunks_per_url": 1})
        assert ok.status_code == 200 and len(ok.json()["results"]) <= 2
        for bad in ({"max_chunks_per_url": 0}, {"max_chunks_to_rerank": 0}, {"top_k_chunks": 0}):
            assert client.post("/v1/search", json={"query": "q", **bad}).status_code == 422


async def test_mcp_options_are_passed_and_bad_values_reported(fake, monkeypatch):
    seen = {}

    async def spy(req):
        seen["req"] = req
        return await real(req)

    real = pipeline.run_search
    from trovia import mcp_server

    monkeypatch.setattr(mcp_server, "run_search", spy)
    await web_search("q", max_chunks=2, max_chunks_to_rerank=15, max_chunks_per_page=1)
    r = seen["req"]
    assert (r.top_k_chunks, r.max_chunks_to_rerank, r.max_chunks_per_url) == (2, 15, 1)
    assert (await web_search("q", max_chunks=0)).startswith("Invalid search options")


async def test_mcp_tool_returns_context_string(fake):
    out = await web_search("rust async mutex", "advanced")
    assert out.startswith("## Source:")
    assert fake["n"] == 8  # advanced depth reads more pages
    assert isinstance(await web_search("q", "bogus-depth"), str)


def test_requests_with_a_foreign_host_header_are_refused(fake):
    with TestClient(app) as client:
        assert client.get("/health", headers={"host": "localhost:8000"}).status_code == 200
        assert client.get("/health", headers={"host": "127.0.0.1:8000"}).status_code == 200
        bad = client.get("/health", headers={"host": "evil.example.com"})
        assert bad.status_code == 400 and "Invalid host" in bad.text
        assert client.post("/v1/search", json={"query": "q"}, headers={"host": "evil.example.com"}).status_code == 400


def test_wildcard_allowed_hosts_disables_the_check(fake, monkeypatch):
    from trovia.config import get_settings

    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get("/health", headers={"host": "anything.example"}).status_code == 200


async def test_no_results_message_suggests_a_key_only_when_duckduckgo_is_all_there_is(monkeypatch):
    from trovia.config import get_settings

    async def none(*a, **k):
        return [], "none"

    monkeypatch.setattr(pipeline, "get_search_hits", none)
    with_keys = await pipeline.run_search(SearchRequest(query="a"))
    assert "trovia config" not in with_keys.error  # conftest configures keys

    for var in ("BRAVE_API_KEY", "SERPER_API_KEY", "SEARXNG_URL"):
        monkeypatch.setenv(var, "")
    get_settings.cache_clear()
    keyless = await pipeline.run_search(SearchRequest(query="b"))
    assert "rate-limited" in keyless.error and "trovia config" in keyless.error


def test_service_starts_even_if_the_model_cannot_be_loaded(fake, monkeypatch):
    from trovia import reranker
    from trovia.config import get_settings

    monkeypatch.setenv("WARMUP", "true")
    get_settings.cache_clear()

    def offline():
        raise ConnectionError("model host unreachable")

    monkeypatch.setattr(reranker, "get_ranker", offline)
    with TestClient(app) as client:  # startup must not fail
        assert client.get("/health").status_code == 200


async def test_adding_a_provider_key_does_not_serve_the_old_cached_response(fake, monkeypatch):
    from trovia.config import get_settings

    monkeypatch.setenv("BRAVE_API_KEY", "")
    get_settings.cache_clear()
    await pipeline.run_search(SearchRequest(query="same question"))
    monkeypatch.setenv("BRAVE_API_KEY", "now-i-have-a-key")
    get_settings.cache_clear()
    second = await pipeline.run_search(SearchRequest(query="same question"))
    assert fake["search"] == 2 and not any(r.cached for r in second.results)


async def test_mcp_tool_description_matches_the_real_defaults():
    from trovia.mcp_server import mcp

    tool = next(t for t in await mcp.list_tools() if t.name == "web_search")
    text = tool.description
    assert "default: all" not in text and "default 6 basic" not in text
    assert "user's setting" in text and "300" in text
