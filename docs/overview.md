# Overview

## What Trovia is

Trovia is a search service built for AI agents rather than for people. A normal search
engine returns ten blue links, and the agent would then have to open each page, strip out
navigation and ads, and work out which paragraphs matter. Trovia does that work and
returns only the relevant passages, each labelled with its source.

Given a question, it:

1. asks a search provider for candidate pages,
2. downloads those pages and converts them to clean Markdown,
3. splits the Markdown into short passages,
4. scores every passage against your question with a small local model, and
5. returns the best passages as Markdown that is ready to paste into a prompt.

It is a self-hosted, single-user equivalent of commercial search APIs for agents (Tavily,
Exa, Perplexity's Sonar API). It runs on your own machine and exposes two interfaces that
share one engine: a REST API and an MCP tool.

## Who it is for

- You run a coding assistant or agent that needs current information from the web.
- You would rather run one small service than depend on a paid search API.
- You are the only user, on your own machine.

Installing takes one command and a short setup (see [install.md](install.md)).

## Design goals

| Goal | How it is met |
|---|---|
| Never leave the caller with an error | Every stage has a fallback; the pipeline returns a normal response even if every provider fails (see [how-it-works](how-it-works.md#failure-handling)) |
| Work for free | DuckDuckGo is built in and needs no key; Brave and Serper are optional upgrades, and SearXNG is an optional self-hosted extra |
| Keep context small | Pages are cut into ~800-character passages and only the top few come back, instead of whole pages |
| Run on a laptop | The reranker is a ~3 MB model on CPU; idle memory is about 100 MB |
| Be repeatable | Results are cached, so an agent that retries the same query does not re-fetch pages or spend search credit |

## What it is not

- **Not a crawler or an index.** It does not store the web. It searches live, then caches.
- **Not a multi-user service.** There is no authentication, rate limiting per user or
  tenant isolation. It binds to `127.0.0.1`.
- **Not a browser.** It does not run JavaScript. A page that renders its content with
  JavaScript is read through the Jina fallback if possible, and otherwise represented by
  its search snippet.
- **Not an answer generator.** It returns source passages; it does not write an answer. Your
  LLM does that with the passages as context.

## Components

| Component | Role |
|---|---|
| **The `trovia` command** | One installed program: it starts the service, runs setup, edits settings, and checks your install (see [cli.md](cli.md)) |
| **REST API** (`trovia`) | The FastAPI service on `127.0.0.1:8000` that runs the pipeline (also available as a Docker container) |
| **MCP server** (`trovia mcp`) | Exposes the same pipeline as a `web_search` tool over stdio |
| **Config file** (`config.toml`) | Your API keys and defaults, in a per-user folder |
| **Disk cache** (data folder) | SQLite-backed cache of search results, pages and responses, plus the reranker model |
| **SearXNG** (optional, Docker) | A self-hosted metasearch engine you can add as an extra search provider |

External services it can call: Brave Search API and Serper.dev (search, optional), and Jina
Reader (`r.jina.ai`, page-reading fallback). Pages themselves are fetched directly from
their websites.

## A note on privacy

Trovia runs locally, but it does call out. Your query goes to whichever search provider
answers (Brave, Serper, DuckDuckGo, or the engines behind SearXNG). The URLs of pages that cannot be read
directly are sent to Jina Reader. Nothing is sent anywhere else.
