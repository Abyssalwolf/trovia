import asyncio
import re
from functools import lru_cache

from flashrank import Ranker, RerankRequest
from pydantic import BaseModel

from .config import get_settings
from .extractor import ExtractionResult
from .schemas import SearchHit

TARGET_CHARS = 800
OVERLAP_CHARS = 100
MAX_FENCE_CHARS = 3000  # a code block longer than this is split by lines
SCORE_BATCH_SIZE = 16

_FENCE = re.compile(r"^\s*```")
_HEADING = re.compile(r"^#{1,6}\s")


class Chunk(BaseModel):
    text: str
    title: str
    url: str
    source_engine: str
    is_snippet: bool = False


class ScoredChunk(Chunk):
    score: float
    extraction_tier: str = ""
    cached: bool = False


def _blocks(markdown: str) -> list[str]:
    """Split into paragraphs; a fenced code block is always one block."""
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False

    def flush():
        if current:
            blocks.append("\n".join(current).strip("\n"))
            current.clear()

    for line in markdown.splitlines():
        if _FENCE.match(line):
            if not in_fence:
                flush()
            current.append(line)
            in_fence = not in_fence
            if not in_fence:
                flush()
            continue
        if in_fence:
            current.append(line)
        elif not line.strip():
            flush()
        elif _HEADING.match(line):
            flush()
            current.append(line)
        else:
            current.append(line)
    flush()
    return [b for b in blocks if b.strip()]


def _split_oversize_fence(block: str) -> list[str]:
    if len(block) <= MAX_FENCE_CHARS:
        return [block]
    parts, buf, size = [], [], 0
    for line in block.splitlines():
        if size + len(line) > TARGET_CHARS * 2 and buf:
            parts.append("\n".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += len(line) + 1
    if buf:
        parts.append("\n".join(buf))
    return parts


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _split_long_text(text: str) -> list[str]:
    """Split an oversize prose block at sentence boundaries (e.g. a flattened table)."""
    text = text.strip().strip("|").strip()
    if len(text) <= TARGET_CHARS:
        return [text]
    parts: list[str] = []
    buf = ""
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > TARGET_CHARS:  # no sentence breaks: cut on whitespace
            cut = sentence.rfind(" ", 0, TARGET_CHARS)
            cut = cut if cut > 0 else TARGET_CHARS
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(sentence[:cut])
            sentence = sentence[cut:].lstrip()
        if buf and len(buf) + len(sentence) + 1 > TARGET_CHARS:
            parts.append(buf)
            buf = ""
        buf = f"{buf} {sentence}" if buf else sentence
    if buf:
        parts.append(buf)
    return parts


def chunk_markdown(markdown: str) -> list[str]:
    """Group blocks into ~TARGET_CHARS chunks, never splitting inside a code fence."""
    chunks: list[str] = []
    buf = ""
    for block in _blocks(markdown):
        if block.lstrip().startswith("```"):
            pieces = _split_oversize_fence(block)
        elif len(block) > TARGET_CHARS:
            pieces = _split_long_text(block)
        else:
            pieces = [block]
        for piece in pieces:
            is_heading = bool(_HEADING.match(piece))
            if buf and (len(buf) + len(piece) + 2 > TARGET_CHARS or (is_heading and len(buf) > TARGET_CHARS // 3)):
                chunks.append(buf)
                buf = ""
            buf = f"{buf}\n\n{piece}" if buf else piece
    if buf:
        chunks.append(buf)

    # Carry a short text overlap between neighbouring chunks (not across code).
    out: list[str] = []
    for i, c in enumerate(chunks):
        prev = chunks[i - 1] if i else ""
        if prev and "```" not in prev and "```" not in c:
            tail = prev[-OVERLAP_CHARS:]
            if prev[-OVERLAP_CHARS - 1 : -OVERLAP_CHARS].strip():  # cut landed mid-word
                tail = tail.partition(" ")[2]
            if tail.strip():
                c = tail.lstrip() + "\n\n" + c
        out.append(c)
    return out


def build_chunks(hits: list[SearchHit], extractions: list[ExtractionResult]) -> list[tuple[Chunk, ExtractionResult]]:
    """The search snippet is chunk #0 for each URL, followed by its page chunks."""
    out: list[tuple[Chunk, ExtractionResult]] = []
    for hit, ex in zip(hits, extractions):
        base = dict(title=hit.title, url=hit.url, source_engine=hit.source_engine)
        if hit.snippet:
            out.append((Chunk(text=hit.snippet, is_snippet=True, **base), ex))
        if ex.tier != "snippet_only":
            out.extend((Chunk(text=t, **base), ex) for t in chunk_markdown(ex.text))
    return out


@lru_cache
def get_ranker() -> Ranker:
    """Singleton so the ONNX model stays warm in memory."""
    return Ranker(model_name=get_settings().rerank_model, cache_dir=str(_model_dir()))


def _model_dir():
    from pathlib import Path

    p = Path(get_settings().models_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def select_candidates(
    pairs: list[tuple[Chunk, ExtractionResult]], limit: int | None
) -> list[tuple[Chunk, ExtractionResult]]:
    """Trim the pool before reranking: search snippets first, then page chunks
    round-robin across URLs (in document order) so every page stays represented."""
    if limit is None or len(pairs) <= limit:
        return pairs
    snippets = [p for p in pairs if p[0].is_snippet]
    by_url: dict[str, list] = {}
    for p in pairs:
        if not p[0].is_snippet:
            by_url.setdefault(p[0].url, []).append(p)
    ordered = list(snippets)
    queues = list(by_url.values())
    for rnd in range(max((len(q) for q in queues), default=0)):
        ordered.extend(q[rnd] for q in queues if rnd < len(q))
    return ordered[:limit]


def rerank(
    query: str,
    pairs: list[tuple[Chunk, ExtractionResult]],
    top_k: int,
    max_per_url: int | None = None,
    max_candidates: int | None = None,
) -> list[ScoredChunk]:
    pairs = select_candidates(pairs, max_candidates)
    if not pairs:
        return []
    passages = [{"id": i, "text": c.text} for i, (c, _) in enumerate(pairs)]
    # Score in small batches: one batch of hundreds of passages makes ONNX Runtime
    # allocate (and keep) over a gigabyte. Padding differs per batch, so scores shift
    # slightly (mostly mid/low ranks; top-12 matched 11-12/12 on real pages).
    ranker = get_ranker()
    ranked: list[dict] = []
    for i in range(0, len(passages), SCORE_BATCH_SIZE):
        ranked.extend(ranker.rerank(RerankRequest(query=query, passages=passages[i : i + SCORE_BATCH_SIZE])))
    ranked.sort(key=lambda r: r["score"], reverse=True)
    out: list[ScoredChunk] = []
    per_url: dict[str, int] = {}
    max_per_url = max_per_url or get_settings().max_chunks_per_url
    for r in ranked:
        if len(out) >= top_k:
            break
        chunk, ex = pairs[r["id"]]
        if per_url.get(chunk.url, 0) >= max_per_url:  # keep results spread across sources
            continue
        per_url[chunk.url] = per_url.get(chunk.url, 0) + 1
        out.append(
            ScoredChunk(**chunk.model_dump(), score=round(float(r["score"]), 4), extraction_tier=ex.tier, cached=ex.cached)
        )
    return out


async def rerank_async(query: str, pairs, top_k: int, max_per_url=None, max_candidates=None) -> list[ScoredChunk]:
    return await asyncio.to_thread(rerank, query, pairs, top_k, max_per_url, max_candidates)


def format_context(chunks: list[ScoredChunk]) -> str:
    """Markdown ready to paste into an LLM prompt, with source citations."""
    return "\n\n---\n\n".join(f"## Source: {c.title} ({c.url})\n{c.text}" for c in chunks)
