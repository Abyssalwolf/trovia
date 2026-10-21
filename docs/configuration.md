# Configuration

Trovia has sensible defaults and works with none of this. When you want to change something, there
are three ways, from easiest to most manual:

1. **`trovia config`**: interactive, hides API keys as you type, shows the recommended values.
2. **`trovia config set NAME VALUE`**: change one setting.
3. **Edit `config.toml`** by hand (find it with `trovia config path`).

## When changes take effect

Changes to `config.toml` (including those made with `trovia config`) reach an already-running
service, and an MCP server your client keeps open, on their **next search**. No restart is needed for
API keys, search providers, timeouts, cache lifetimes, or your three search defaults.

A restart is needed for: `host`, `port`, `warmup`, `rerank_model`, `models_dir`, `cache_dir`, and any
change to **environment variables** (they are read when Trovia starts). For the Docker setup, every
change is an environment variable, so run `docker compose up -d` after editing `.env`.

## Precedence

When the same setting is given in more than one place, the first of these wins:

1. an **environment variable** (the setting name in capitals, e.g. `BRAVE_API_KEY`),
2. the **config file** (`config.toml`),
3. the **built-in default**.

An empty environment variable counts as not set, so a blank `BRAVE_API_KEY=` line never hides a
key saved in your config file.

The Docker container has no config file; it is configured with environment variables (from `.env`).
See [install.md](install.md#docker).

## The config file

`config.toml` is a flat list of `name = value` lines. Only values you changed need to appear:

```toml
brave_api_key = "BSA..."
top_k_chunks = 10
max_chunks_per_url = 1
provider_order = "brave,ddgs"
```

On macOS and Linux the file is created readable only by you, because it holds API keys. On Windows
it lives in your user profile, which other accounts cannot read by default.

## Where things live

| | Windows | macOS | Linux |
|---|---|---|---|
| **Config folder** (`config.toml`) | `%LOCALAPPDATA%\trovia` | `~/Library/Application Support/trovia` | `~/.config/trovia` |
| **Data folder** (cache, model) | `%LOCALAPPDATA%\trovia` | `~/Library/Application Support/trovia` | `~/.local/share/trovia` |

These are the standard per-user locations (chosen by the `platformdirs` library). Only the Windows
paths were checked on a real machine. Override them with `TROVIA_CONFIG_DIR` and `TROVIA_DATA_DIR`.
Inside the data folder, `cache/` holds search results, pages and the Brave usage counter, and
`models/` holds the reranker model.

## Settings

Names are shown as they appear in `config.toml`; the environment variable is the same name in capitals.

### Your defaults for every search

These are the three you are asked about in setup. A search can override each one in the request.

| Setting | Default (recommended) | Meaning |
|---|---|---|
| `top_k_chunks` | `6` | Passages returned per search. Advanced searches return twice as many. (1 to 50) |
| `max_chunks_to_rerank` | `300` | Most candidate passages scored by the reranker; `0` scores all of them. (0, or 1 to 500) |
| `max_chunks_per_url` | `2` | Most passages returned from any one page. (1 to 50) |

Why 300 for the candidate limit: on real `advanced` searches the pool was 150 to 220 passages, and
scoring all of them took about 0.3 seconds. A limit of 100 saved only about 0.13 seconds but dropped
4 of the top 12 passages in testing. So 300 is a safety ceiling for unusually large pools, not a
tuning knob; lowering it mostly makes results worse.

### Search providers

| Setting | Default | Meaning |
|---|---|---|
| `brave_api_key` | empty | [Brave Search API](https://brave.com/search/api/) key. Empty means Brave is skipped. |
| `serper_api_key` | empty | [Serper.dev](https://serper.dev) key (Google results). Empty means Serper is skipped. |
| `searxng_url` | empty | Optional, advanced: endpoint of a self-hosted SearXNG. Empty means it is not used. |
| `provider_order` | `brave,serper,searxng,ddgs` | Order providers are tried. Remove a name to disable it. `ddgs` is DuckDuckGo, which needs no key. |
| `brave_monthly_limit` | `950` | Stop using Brave after this many calls in a calendar month. |
| `brave_timeout_sec` | `5` | Timeout for a Brave request. |
| `serper_timeout_sec` | `5` | Timeout for a Serper request. |
| `searxng_timeout_sec` | `10` | Timeout for a SearXNG request. |
| `ddgs_timeout_sec` | `10` | Timeout for a DuckDuckGo search. |

**Choosing providers.** With no keys, everything goes through DuckDuckGo. It needs no setup, but it is
best-effort: it can be rate-limited or blocked (in one test run, a fourth search in quick
succession returned nothing), and it returns short snippets rather than rich results. For reliable
use, add a Brave or Serper key. Brave is fast and independent; Serper returns Google results and
has a one-time free allowance with no card. To use only one provider, set `provider_order` to just
that name.

**Brave's free credit.** Brave's plan gives a monthly credit worth roughly 1,000 searches, requires a
card on file, and does not cap spending past the credit. Trovia's own counter (`brave_monthly_limit`)
is a safeguard, not a guarantee: it counts only calls made by Trovia on this machine, including
failed ones. To reset it, delete the `cache/usage` folder in the data folder. Check current Brave
and Serper pricing and terms on their sites; they change.

### Page extraction

| Setting | Default | Meaning |
|---|---|---|
| `jina_api_key` | empty | Optional [Jina](https://jina.ai) key. Without it, Jina Reader allows about 20 requests a minute; a free key raises that to about 500. |
| `tier1_timeout_sec` | `5` | Timeout for the direct page fetch (a 1 s allowance is added for parsing). |
| `tier2_timeout_sec` | `10` | Timeout for the Jina fallback (a 1 s allowance is added). |
| `global_scrape_timeout_sec` | `20` | Upper limit for reading one page across all tiers. |

### Server

| Setting | Default | Meaning |
|---|---|---|
| `host` | `127.0.0.1` | Address the service listens on. Keep it local: there is no authentication. |
| `port` | `8000` | Port the service listens on. |
| `allowed_hosts` | `localhost,127.0.0.1` | `Host` header values the service accepts; anything else gets HTTP 400. This blocks web pages from reaching the service through DNS rebinding. Use `*` to turn the check off, or add a name if you reach the service by another hostname. |
| `warmup` | `true` | Load the reranker model when the service starts, so the first search is not slow. |

### Reranker and cache

| Setting | Default | Meaning |
|---|---|---|
| `rerank_model` | `ms-marco-TinyBERT-L-2-v2` | FlashRank model used for scoring. `ms-marco-MiniLM-L-12-v2` is more precise in principle but took about 14 s for 40 passages on a 12-core laptop CPU, so it is not practical. |
| `models_dir` | `<data folder>/models` | Where the model is stored. |
| `cache_dir` | `<data folder>/cache` | Where the cache is stored. |
| `serp_cache_ttl_sec` | `3600` | How long search results and complete responses are cached (1 hour). |
| `url_cache_ttl_sec` | `86400` | How long extracted page content is cached (24 hours). |

Changing `rerank_model` downloads the new model on first use. To clear the caches, stop Trovia and
delete the `cache` folder, or send requests with `bypass_cache: true`.

## Fixed in code

These are constants rather than settings (edit the source to change them):

| Constant | Value | File |
|---|---|---|
| Target passage size | 800 characters | `trovia/reranker.py` |
| Passage overlap | 100 characters | `trovia/reranker.py` |
| Reranker batch size | 16 passages | `trovia/reranker.py` |
| Minimum page text | 250 characters | `trovia/extractor.py` |
| Pages read by `advanced` | at least 8 | `trovia/pipeline.py` |

## Optional: SearXNG

SearXNG is a self-hosted metasearch engine you can add as an extra provider. It queries several search
engines at once, so one engine being blocked does not stop it. It is off by default and needs Docker
(it has no supported native Windows install). It is aimed at advanced users.

```bash
# in the Trovia repository folder
# 1. in .env set a secret for the SearXNG container, e.g.  SEARXNG_SECRET=<random value>
# 2. start it (the "searxng" profile is opt-in)
docker compose --profile searxng up -d
# 3. tell Trovia where it is
trovia config set searxng_url http://localhost:8080/search
```

With a URL set, SearXNG is tried after Brave and Serper and before DuckDuckGo (change the order with
`provider_order`). If you run Trovia itself in Docker, set `SEARXNG_URL=http://searxng:8080/search`
in `.env` instead. SearXNG's own settings are in `searxng/settings.yml` (JSON output enabled, limiter
off); it listens on `127.0.0.1:8080`.
