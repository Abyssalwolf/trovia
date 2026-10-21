# How it works

A search runs through one pipeline, implemented in `trovia/pipeline.py`. The REST API and the
MCP tool both call it, so they behave identically.

```
request
  │
  ├─► response cache hit? ──────────────────────────────► return (milliseconds)
  │
  ▼
Stage 1  Discovery      Brave → Serper → SearXNG* → DuckDuckGo → list of URLs + snippets
Stage 2  Extraction     curl_cffi → Jina → snippet      → Markdown per page
Stage 3  Chunking       split pages into ~800-char passages; snippet is passage #0
Stage 4  Reranking      score passages against the query; keep the best, spread across sources
  │
  ▼
response (synthesized_context + results)  ──► stored in the response cache
```

\* SearXNG is optional and used only when `SEARXNG_URL` is set.

## Stage 1: Discovery (`trovia/discovery.py`)

Turns the query into a list of candidate pages (`title`, `url`, `snippet`, `published_date`,
`source_engine`).

Providers are tried **in order** until one returns results. The default order is
`brave,serper,searxng,ddgs` and is set with `PROVIDER_ORDER`.

- A provider with no API key configured is **skipped**, not tried. With no keys at all,
  DuckDuckGo handles everything. SearXNG is skipped unless `SEARXNG_URL` is set.
- A provider that errors, times out or returns nothing causes the next provider to be tried.
  Any failure counts: a 401 from a bad key, a 429 from a spent quota, a 5xx, a timeout.
- **Brave is metered.** Brave's free credit covers about 1,000 searches a month, so
  Trovia counts its Brave calls per calendar month (UTC) and stops using Brave at
  `BRAVE_MONTHLY_LIMIT` (default 950), moving on to the next provider. The count is stored
  locally in the cache folder and only knows about calls made by this service. It counts every
  attempt, including failed ones.
- Results are de-duplicated by URL (ignoring a trailing slash) and trimmed to the number of
  URLs wanted.
- If every provider fails, discovery returns nothing and the pipeline reports the failure in
  the response's `error` field instead of raising.

How many URLs are read depends on `search_depth`: `basic` reads `max_results` pages
(default 5); `advanced` reads at least 8.

## Stage 2: Extraction (`trovia/extractor.py`)

Every URL is read concurrently. Each one goes through a cascade; the first tier that
produces acceptable text wins.

| Order | Tier | What it does |
|---|---|---|
| – | Pre-flight | Skips binary files (`.zip`, images, audio, video and similar) and goes straight to the snippet. PDFs skip tier 1 and go to Jina, which can read them. |
| 1 | `tier1_trafilatura` | Downloads the page with `curl_cffi`, which impersonates a current Chrome browser's TLS fingerprint so ordinary bot checks pass, then converts the HTML to Markdown with `trafilatura`. |
| 2 | `tier2_jina` | Asks Jina Reader (`r.jina.ai`) to fetch and convert the page. It runs a real browser on Jina's side, so it can read many JavaScript-rendered pages. |
| 3 | `snippet_only` | If both tiers fail, the search snippet stands in for the page. The request still succeeds. |

**Validation gate.** A tier only counts as successful if the HTTP status is 200, the text is
at least 250 characters, and the start of the text does not contain a bot-challenge marker
such as "Just a moment..." or "Attention Required! | Cloudflare". Otherwise the next tier is
tried.

**Timeouts.** Each tier has its own timeout (`TIER1_TIMEOUT_SEC`, `TIER2_TIMEOUT_SEC`), and a
global limit (`GLOBAL_SCRAPE_TIMEOUT_SEC`, 20 s) caps the whole cascade for one page. Hitting
a timeout is handled like any other failure.

**Caching.** A successfully extracted page is cached for 24 hours. Failures are not cached,
so a page that failed is retried next time.

## Stage 3: Chunking (`trovia/reranker.py`)

Whole pages are far too long to use as context, so each page's Markdown is cut into
passages of about 800 characters.

- Splits happen at paragraph boundaries and before headings.
- **Code blocks are never split.** A fenced block stays in one passage unless it exceeds
  3,000 characters, in which case it is split by line.
- Prose that has no paragraph breaks at all (some table-layout pages come out as one long
  line) is split at sentence boundaries, and at word boundaries if there are no sentences.
- Neighbouring prose passages share a 100-character overlap that starts on a word boundary,
  so a sentence cut at the edge is not lost.
- The **search snippet is always added as passage #0** for its URL. Search engines are good
  at extracting the sentence that answers a query, so the snippet is often the best passage.
  It is marked `is_snippet: true` in the response.
- Pages that fell back to `snippet_only` contribute only the snippet.

## Stage 4: Reranking (`trovia/reranker.py`)

The passages from every page are scored against the query by a **cross-encoder**, a model
that reads the query and a passage together and judges how well the passage answers it. This
is much more accurate than keyword or vector similarity.

- The model is `ms-marco-TinyBERT-L-2-v2`, run on CPU through the FlashRank library. It is
  loaded once at server start and kept in memory.
- **Candidate limit.** If the pool is larger than the candidate limit (`max_chunks_to_rerank`,
  default 300; real `advanced` searches produced 150 to 220 candidates, so it rarely applies),
  the pool is trimmed before scoring: all snippets first, then page passages taken one at a time from each URL in
  turn (in document order), so no page is crowded out.
- **Batching.** Passages are scored 16 at a time. Scoring hundreds of passages in a single
  batch made the model runtime hold over a gigabyte of memory; batching keeps the service
  around 400 MB. The side effect is that a passage's score can shift slightly depending on
  which passages it was batched with. The effect is mostly in mid and low ranks.
- **Selection.** Passages are sorted by score and the best `top_k_chunks` are returned (6 for
  `basic`, 12 for `advanced` by default), with at most `max_chunks_per_url` from any single
  page (default 2) so one site cannot dominate the answer.

The result is formatted into `synthesized_context`: one block per passage, each starting
with `## Source: <title> (<url>)`, separated by `---`.

> **About `relevance_score`.** The score is the model's output between 0 and 1. With this
> small model, relevant passages cluster very close to 1.0, so the score is reliable for
> *ordering* passages but not meaningful as an absolute measure of relevance.

## Caching

Trovia caches at three levels, all on disk in the cache folder (`CACHE_DIR`, by default the `cache` folder inside Trovia's data folder; see [configuration](configuration.md#where-things-live)):

| Cache | Key | Lifetime | Notes |
|---|---|---|---|
| Response | Every request parameter except `bypass_cache` | 1 hour (`SERP_CACHE_TTL_SEC`) | Only successful, non-empty responses are stored. A hit returns with every result marked `cached: true`. |
| Search results | Query, `max_results`, and the active providers | 1 hour | Saves search credit when a different response is built from the same search. |
| Page content | URL | 24 hours (`URL_CACHE_TTL_SEC`) | Only successful extractions. |

Because the response cache key includes `search_depth`, `top_k_chunks`, `max_chunks_per_url`
and the other options, changing any option never returns a result cached under different
settings. Set `bypass_cache: true` on a request to ignore all three caches for that request.

Cached data is not refreshed early: a response can be up to an hour old, a page up to a day.

## Failure handling

The pipeline is designed so the caller always gets a well-formed response.

| What goes wrong | What happens |
|---|---|
| A search provider fails, times out or is out of quota | The next provider is tried |
| A provider has no API key | It is skipped |
| The Brave monthly limit is reached | Brave is skipped for the rest of the month |
| A page cannot be fetched or is a bot-challenge page | Jina is tried, then the search snippet is used |
| A page fetch hangs | It is cancelled at the timeout and treated as a failure |
| Every search provider fails | HTTP 200 with empty `results` and an `error` message (MCP returns `Search failed: ...`) |
| An unexpected exception anywhere in the pipeline | Caught; returned as an `error` in a normal response |

Invalid request values (for example `top_k_chunks: 0`) are the exception: the REST API rejects
them with HTTP 422, and the MCP tool returns `Invalid search options: ...`.

## Timing

Uncached searches took roughly 4 to 11 seconds in testing. Nearly all of that is spent
downloading pages, because the pipeline waits for every page it is reading (or its timeout).
Reranking takes a fraction of a second. A repeated search returns from the response cache in
milliseconds. `latency_ms` in each response reports the actual time.
