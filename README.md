# Trovia

Web search for AI agents, running on your own machine. You give it a question; it searches the web,
reads the top pages, picks the passages that best answer the question, and returns them as clean,
source-cited Markdown that you can drop straight into a prompt.

It is a personal, single-user alternative to hosted search APIs such as Tavily or Exa. It needs no
account and no API key to start, and it exposes one engine two ways:

- a **REST API** (`POST /v1/search`)
- an **MCP tool** (`web_search`) for Claude Code, Claude Desktop and other MCP clients

```
question -> search providers -> read the pages -> split into passages -> rerank -> cited Markdown
            Brave / Serper /     curl_cffi,        ~800-char chunks       small local
            DuckDuckGo           then Jina                                model on CPU
```

## Install

**macOS and Linux**

```bash
curl -LsSf https://YOUR-SITE/install.sh | sh
```

**Windows (PowerShell)**

```powershell
irm https://YOUR-SITE/install.ps1 | iex
```

The installer sets up `trovia` in its own isolated environment (you do not need Python installed) and
then runs a short setup: paste a Brave and/or Serper API key if you have one (optional), and choose
your defaults, each shown with a recommended value. More options, update and uninstall:
[docs/install.md](docs/install.md).

## Use it

```bash
trovia
```

That starts the service on <http://127.0.0.1:8000>. Try a search:

```bash
curl -X POST http://localhost:8000/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "rust tokio async mutex vs std sync mutex performance"}'
```

Or without starting the service at all:

```bash
trovia search "rust tokio async mutex vs std sync mutex performance"
```

**With an MCP client** (the REST service does not need to be running):

```bash
claude mcp add trovia -- trovia mcp
```

See [docs/mcp.md](docs/mcp.md) for Claude Desktop and other clients.

## Commands

| Command | What it does |
|---|---|
| `trovia` | Start the service (first run: asks the setup questions first) |
| `trovia config` | Change API keys and defaults any time |
| `trovia setup` | Run the guided setup again |
| `trovia search "question"` | Run one search from the terminal |
| `trovia mcp` | Run the MCP server (your MCP client starts this) |
| `trovia doctor` | Check that everything works |

Full reference: [docs/cli.md](docs/cli.md).

## What you get back

```json
{
  "query": "rust tokio async mutex vs std sync mutex performance",
  "search_provider_used": "brave",
  "latency_ms": 4405,
  "synthesized_context": "## Source: Rust Std Mutex vs Tokio Mutex ... (https://...)\n...\n\n---\n\n## Source: ...",
  "results": [
    {
      "title": "Shared state | Tokio",
      "url": "https://tokio.rs/tokio/tutorial/shared-state",
      "chunk_content": "Generally, using a blocking mutex inside async code is fine ...",
      "relevance_score": 0.999,
      "extraction_tier": "tier1_trafilatura",
      "is_snippet": false,
      "cached": false
    }
  ]
}
```

`synthesized_context` is a ready-to-use Markdown string with a source header on every passage;
`results` carries the same passages as structured data.

## Your defaults

Every search accepts these optional controls on both the REST API and the MCP tool, and `trovia config`
sets your own defaults for them:

| Control | REST field | MCP argument | Default |
|---|---|---|---|
| How much to read | `search_depth` | `search_depth` | `basic` (`advanced` reads at least 8 pages) |
| Max passages returned | `top_k_chunks` | `max_chunks` | 6 (advanced: 12) |
| Max passages sent to the reranker | `max_chunks_to_rerank` | `max_chunks_to_rerank` | 300 |
| Max passages from any one page | `max_chunks_per_url` | `max_chunks_per_page` | 2 |

## Search providers

With no keys, Trovia searches through DuckDuckGo. That is free but best-effort and can be rate-limited,
so for reliable use add a Brave or Serper key (`trovia config`). Providers are tried in order and the
next one takes over if one fails. A self-hosted SearXNG can be added as an optional extra
([docs/configuration.md](docs/configuration.md#optional-searxng)).

## Docker

Prefer a container? `docker compose up -d --build` starts the API on `127.0.0.1:8000`; see
[docs/install.md](docs/install.md#docker).

## Documentation

| Document | What it covers |
|---|---|
| [docs/install.md](docs/install.md) | Install, update, uninstall, Docker |
| [docs/cli.md](docs/cli.md) | Every command and the setup questions |
| [docs/overview.md](docs/overview.md) | What Trovia is, who it is for, what it is not |
| [docs/how-it-works.md](docs/how-it-works.md) | The pipeline stage by stage, caching, failure handling |
| [docs/rest-api.md](docs/rest-api.md) | Full REST API reference with examples |
| [docs/mcp.md](docs/mcp.md) | Setting up and using the MCP tool |
| [docs/configuration.md](docs/configuration.md) | Every setting |
| [docs/development.md](docs/development.md) | Project layout, tests, releasing, troubleshooting |

The [skills/](skills/) folder has ready-made agent skills for the REST API and for MCP.

## Limits to know about

- **No JavaScript rendering.** Pages that only show content after running JavaScript, and that the Jina
  fallback also cannot read, are represented by their search snippet.
- **Local only.** There is no authentication. The service listens on `127.0.0.1` and refuses requests
  with a foreign `Host` header; do not expose it to a network without adding authentication in front.
- **Not instant.** An uncached search typically takes 4 to 11 seconds, mostly spent fetching pages. A
  repeat of the same search comes from the cache in milliseconds.
- **Free-tier limits apply.** Brave's free credit covers roughly 1,000 searches a month, and Jina's
  keyless reader allows about 20 requests a minute.
