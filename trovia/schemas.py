from typing import Literal

from pydantic import BaseModel, Field


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str = ""
    published_date: str | None = None
    source_engine: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    search_depth: Literal["basic", "advanced"] = "basic"
    max_results: int = Field(default=5, ge=1, le=10)
    # None means "use the user's setting" (see config.py): top_k_chunks (doubled for advanced),
    # max_chunks_to_rerank, max_chunks_per_url.
    top_k_chunks: int | None = Field(default=None, ge=1, le=50)
    max_chunks_to_rerank: int | None = Field(default=None, ge=1, le=500)
    max_chunks_per_url: int | None = Field(default=None, ge=1, le=50)
    include_raw_markdown: bool = False
    bypass_cache: bool = False


class SearchResultItem(BaseModel):
    title: str
    url: str
    chunk_content: str
    relevance_score: float
    extraction_tier: str
    is_snippet: bool = False
    cached: bool = False


class SearchResponse(BaseModel):
    query: str
    search_provider_used: str
    latency_ms: int
    synthesized_context: str
    results: list[SearchResultItem]
    raw_markdown: dict[str, str] | None = None
    error: str | None = None
