# Using Trovia through MCP

[MCP](https://modelcontextprotocol.io) (Model Context Protocol) lets an AI client call tools that you
provide. Trovia provides one tool, **`web_search`**, which gives the client web search that returns
relevant, source-cited passages.

## How it runs

The MCP server is the command `trovia mcp`. Your MCP client starts it when needed and talks to it over
**stdio**; you never run it by hand. It runs the same search pipeline as the REST API, directly on your
machine, so:

- you only need Trovia installed (see [install.md](install.md)); the REST service does **not** have to
  be running, and Docker is not needed;
- it reads the same `config.toml` as everything else, so the API keys and defaults you set with
  `trovia setup` or `trovia config` apply automatically, from the next search on, even while the
  client keeps the server open (nothing needs to be passed in the client's configuration);
- it shares the cache with the REST service, so a search made through one is cached for the other.

Before connecting a client, run `trovia setup` once (API keys are optional) and check it with
`trovia doctor`.

## The tool

```
web_search(
    query: str,
    search_depth: str = "basic",
    max_chunks: int | None = None,
    max_chunks_to_rerank: int | None = None,
    max_chunks_per_page: int | None = None,
) -> str
```

| Argument | Description | Default |
|---|---|---|
| `query` | What to search for. | required |
| `search_depth` | `"basic"` (faster) or `"advanced"` (reads at least 8 pages, returns more passages). Any other value is treated as `"basic"`. | `"basic"` |
| `max_chunks` | Most passages to return in total. | your `top_k_chunks` setting (6); advanced returns twice as many |
| `max_chunks_to_rerank` | Most candidate passages to score. | your setting (300) |
| `max_chunks_per_page` | Most passages returned from any one page. | your setting (2) |

All arguments except `query` are optional. Ranges match the [REST API](rest-api.md#request):
`max_chunks` 1 to 50, `max_chunks_to_rerank` 1 to 500, `max_chunks_per_page` 1 to 50.

### What it returns

A single Markdown string, the same text as the REST API's `synthesized_context`. Each passage is
preceded by `## Source: <title> (<url>)` and passages are separated by `---`.

```
## Source: Shared state | Tokio (https://tokio.rs/tokio/tutorial/shared-state)
Generally, using a blocking mutex inside async code is fine as long as ...

---

## Source: What makes async mutex more expensive than sync mutex? (https://users.rust-lang.org/...)
...
```

The tool never raises an error to the client. Problems come back as text:

| Situation | Returned text |
|---|---|
| No results | `No results found.` |
| Search could not be completed | `Search failed: <reason>` |
| An argument is out of range (for example `max_chunks: 0`) | `Invalid search options: <details>` |

If you only use DuckDuckGo (no keys) and it is rate-limiting you, the reason says so and suggests adding
a key with `trovia config`.

## Connecting a client

The client launches `trovia mcp`, so it must be able to find the `trovia` command. The installer puts it
in a folder that is on your PATH once you open a new terminal. Desktop apps sometimes start with a
shorter PATH; if a client cannot find `trovia`, give it the full path instead (run `where trovia` on
Windows, or `which trovia` on macOS and Linux, to see it).

### Claude Code

```bash
claude mcp add trovia -- trovia mcp
```

Run `claude mcp list` to confirm it is connected. To share the setup with a team through a project
file, add `--scope project`.

### Claude Desktop

Open Settings, then Developer, then Edit Config, and add the server under `mcpServers`:

```json
{
  "mcpServers": {
    "trovia": {
      "command": "trovia",
      "args": ["mcp"]
    }
  }
}
```

If Claude Desktop reports that it cannot start the server, replace `"trovia"` with the full path to
the executable (on Windows, double the backslashes in JSON, e.g. `"C:\\Users\\you\\.local\\bin\\trovia.exe"`).
Restart Claude Desktop afterwards.

### Other MCP clients

Any client that can launch a stdio MCP server works. The command is:

```
trovia mcp
```

### Running over HTTP (SSE)

The underlying MCP library can serve over HTTP using the SSE transport, but Trovia's `trovia mcp`
command supports stdio only, and the SSE mode has not been tested. Stdio is the supported setup.

## Behaviour to expect

- **The first search in a session is slower.** Unlike the REST service, the MCP server does not preload
  the reranker; the model loads on the first search (a second or two once it is downloaded).
- **Searches take a few seconds.** An uncached `basic` search typically takes 4 to 11 seconds; repeats
  come from the cache almost instantly. `advanced` reads more pages and is usually slower.
- **Logs go to stderr.** MCP uses stdout for protocol messages, so diagnostic output appears in the
  client's server log, not in the conversation.

## Tips for prompting

The model decides when to call the tool, so tell it when to use it. For example:

> Use the `trovia` `web_search` tool for anything that may have changed recently or that you are not
> sure about. Use `search_depth: "advanced"` for broad or contested questions. Cite the sources from
> the results.

For a small context budget, set `max_chunks` lower (for example 3). For variety across sources, set
`max_chunks_per_page` to 1.

There are also ready-made skills that teach an agent how to use Trovia; see the `skills/` folder in
this repository.
