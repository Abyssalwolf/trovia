import pytest

from trovia.extractor import ExtractionResult
from trovia.reranker import (
    MAX_FENCE_CHARS,
    TARGET_CHARS,
    build_chunks,
    chunk_markdown,
    format_context,
    rerank,
)
from trovia.schemas import SearchHit

PARA = "Sentence about async mutexes in Rust and tokio. " * 8  # ~390 chars


def test_chunks_respect_target_size():
    md = "\n\n".join(PARA for _ in range(20))
    chunks = chunk_markdown(md)
    assert len(chunks) > 3
    assert all(len(c) <= TARGET_CHARS + 200 for c in chunks)  # target + overlap


def test_overlap_never_starts_mid_word():
    words = [f"w{i:04d}" for i in range(600)]
    chunks = chunk_markdown(("\n\n".join(" ".join(words[i:i + 60]) for i in range(0, 600, 60))))
    vocab = set(words)
    for c in chunks:
        assert c.split()[0] in vocab


def test_code_fence_is_never_split():
    code = "```python\n" + "\n".join(f"x{i} = {i}" for i in range(40)) + "\n```"
    md = f"{PARA}\n\n{code}\n\n{PARA}"
    chunks = chunk_markdown(md)
    holder = [c for c in chunks if "x0 = 0" in c]
    assert len(holder) == 1 and "x39 = 39" in holder[0]
    for c in chunks:
        assert c.count("```") % 2 == 0


def test_oversize_fence_is_split_by_lines():
    code = "```\n" + "\n".join("line %04d " % i + "y" * 40 for i in range(200)) + "\n```"
    assert len(code) > MAX_FENCE_CHARS
    assert len(chunk_markdown(code)) > 1


def test_headings_start_new_chunks():
    md = f"# One\n\n{PARA}\n\n## Two\n\n{PARA}"
    chunks = chunk_markdown(md)
    assert any(c.lstrip().startswith("## Two") or "\n\n## Two" in c for c in chunks)


def test_single_line_page_without_newlines_is_still_chunked():
    # e.g. a table-layout page that extraction flattened into one huge line
    md = "| " + " ".join(f"Sentence number {i} says something useful." for i in range(400))
    chunks = chunk_markdown(md)
    assert len(chunks) > 10
    assert all(len(c) <= TARGET_CHARS + 200 for c in chunks)
    assert not chunks[0].startswith("|")


def test_text_with_no_sentence_breaks_is_cut_on_whitespace():
    chunks = chunk_markdown("word " * 1000)
    assert len(chunks) > 3
    assert all(len(c) <= TARGET_CHARS + 200 for c in chunks)


def test_empty_markdown():
    assert chunk_markdown("") == []


def test_snippet_is_chunk_zero_and_snippet_only_adds_no_page_chunks():
    hits = [
        SearchHit(title="A", url="https://a.com", snippet="snip a", source_engine="e"),
        SearchHit(title="B", url="https://b.com", snippet="snip b", source_engine="e"),
    ]
    exs = [ExtractionResult(text=PARA * 3, tier="tier1_trafilatura"), ExtractionResult(text="snip b", tier="snippet_only")]
    pairs = build_chunks(hits, exs)
    a = [c for c, _ in pairs if c.url == "https://a.com"]
    b = [c for c, _ in pairs if c.url == "https://b.com"]
    assert a[0].is_snippet and a[0].text == "snip a" and len(a) > 1
    assert len(b) == 1 and b[0].is_snippet


def test_rerank_puts_relevant_chunk_first_and_formats_context():
    hit = SearchHit(title="Doc", url="https://d.com", snippet="", source_engine="e")
    texts = [
        "Bananas are yellow fruits that grow in tropical climates.",
        "Using a std::sync::Mutex in async Rust is fine if the lock is not held across .await points.",
        "The stock market closed higher on Tuesday amid earnings reports.",
    ]
    ex = ExtractionResult(text="x", tier="tier1_trafilatura")
    from trovia.reranker import Chunk

    pairs = [(Chunk(text=t, title="Doc", url="https://d.com", source_engine="e"), ex) for t in texts]
    top = rerank("rust async mutex held across await", pairs, top_k=2)
    assert len(top) == 2
    assert "Mutex" in top[0].text
    assert top[0].score >= top[1].score
    ctx = format_context(top)
    assert ctx.startswith("## Source: Doc (https://d.com)")
    assert "---" in ctx


def test_at_most_two_chunks_per_url_and_top_k_still_filled():
    from trovia.reranker import Chunk

    ex = ExtractionResult(text="x", tier="tier1_trafilatura")
    mutex = "Using a std::sync::Mutex in async Rust is fine if the lock is not held across .await points."
    pairs = [(Chunk(text=f"{mutex} variant {i}", title="Big", url="https://big.com", source_engine="e"), ex) for i in range(6)]
    pairs += [(Chunk(text="Tokio mutex guards can be held across await, unlike the std mutex.", title="Small", url="https://small.com", source_engine="e"), ex)]
    top = rerank("rust async mutex across await", pairs, top_k=4)
    urls = [c.url for c in top]
    assert urls.count("https://big.com") == 2
    assert "https://small.com" in urls
    assert len(top) == 3  # only 3 chunks are eligible; no padding with extra big.com chunks


def _pairs(spec):
    """spec: {url: n_page_chunks}; every URL also gets a snippet chunk."""
    from trovia.reranker import Chunk

    ex = ExtractionResult(text="x", tier="tier1_trafilatura")
    out = []
    for url, n in spec.items():
        out.append((Chunk(text=f"snippet of {url}", title=url, url=url, source_engine="e", is_snippet=True), ex))
        out += [(Chunk(text=f"{url} chunk {i}", title=url, url=url, source_engine="e"), ex) for i in range(n)]
    return out


def test_select_candidates_keeps_snippets_then_round_robins_pages():
    from trovia.reranker import select_candidates

    pairs = _pairs({"a": 5, "b": 5, "c": 5})
    assert select_candidates(pairs, None) == pairs
    assert select_candidates(pairs, 100) == pairs
    picked = [c.text for c, _ in select_candidates(pairs, 6)]
    assert picked == ["snippet of a", "snippet of b", "snippet of c", "a chunk 0", "b chunk 0", "c chunk 0"]
    picked = [c.text for c, _ in select_candidates(pairs, 2)]
    assert picked == ["snippet of a", "snippet of b"]


def test_max_candidates_limits_what_gets_scored(monkeypatch):
    from trovia import reranker

    seen = {}
    real = reranker.get_ranker().rerank

    def spy(req):
        seen["n"] = len(req.passages)
        return real(req)

    monkeypatch.setattr(reranker.get_ranker(), "rerank", spy)
    rerank("query", _pairs({"a": 10, "b": 10}), top_k=5, max_candidates=7)
    assert seen["n"] == 7


def test_batched_scoring_scores_every_candidate_and_keeps_best_match_on_top(monkeypatch):
    from trovia import reranker

    pairs = _pairs({"a": 20, "b": 20, "c": 20})  # 63 candidates, several batches
    monkeypatch.setattr(reranker, "SCORE_BATCH_SIZE", 8)
    top = rerank("b chunk 7", pairs, top_k=100, max_per_url=100)
    assert len(top) == 63
    assert top[0].text == "b chunk 7"
    assert [c.score for c in top] == sorted((c.score for c in top), reverse=True)


def test_per_url_override_beats_default():
    pairs = _pairs({"a": 6, "b": 6})
    top = rerank("a chunk", pairs, top_k=10, max_per_url=1)
    assert sorted(c.url for c in top) == ["a", "b"]
    top = rerank("a chunk", pairs, top_k=10, max_per_url=4)
    assert max(sum(c.url == u for c in top) for u in ("a", "b")) == 4


def test_rerank_empty():
    assert rerank("q", [], 5) == []
