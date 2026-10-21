# Command-line reference

Trovia is one command, `trovia`. Run `trovia --help` (or `trovia <command> --help`) for the
built-in help.

| Command | What it does |
|---|---|
| `trovia` | Start the service. On the very first run it asks the setup questions first. |
| `trovia serve` | Start the service (same as `trovia`), with options for address and port. |
| `trovia setup` | Guided setup: API keys, defaults, and the reranker model. |
| `trovia config` | Change settings interactively. Also `config show`, `config set`, `config unset`, `config path`. |
| `trovia mcp` | Run the MCP server over stdio, for Claude Code, Claude Desktop and other MCP clients. |
| `trovia search "question"` | Run one search from the terminal. |
| `trovia doctor` | Check that your config, model, providers and port are working. |
| `trovia --version` | Show the version. |

## `trovia` / `trovia serve`

Starts the REST API and keeps running until you press Ctrl+C.

```
$ trovia
Trovia 0.1.0
  REST API   http://127.0.0.1:8000   (interactive docs at /docs)
  MCP        add `trovia mcp` to your MCP client (see the docs)
  Search     brave -> ddgs
  Press Ctrl+C to stop.
```

The "Search" line shows which providers are active, in the order they are tried.

```bash
trovia serve --port 8001          # use another port for this run
trovia serve --host 0.0.0.0       # listen on all interfaces (not recommended: there is no authentication)
```

If the port is taken, Trovia says so and suggests another instead of failing with a stack trace.
To change the default port permanently: `trovia config set port 8001`.

On a first run in an interactive terminal, `trovia` runs the setup questions before starting. It
does not ask when there is no terminal (for example under a service manager); it just starts with
the defaults.

## `trovia setup`

Asks a short series of questions, saves your answers, and downloads the reranker model (about 3 MB,
once). Press Enter to skip a question or accept the value shown.

**Step 1: search providers.** Paste an API key for Brave and/or Serper, and optionally Jina.

- What you type is hidden, so a key never appears on screen or in terminal history.
- Brave and Serper keys are checked with one real search (it uses one query of your quota). If a
  key is rejected you can retry. If Trovia cannot reach the provider to check, it asks whether to
  save the key anyway.
- Skipping both is fine: Trovia falls back to DuckDuckGo.

**Step 2: defaults for every search.** Each prompt shows the recommended value.

| Prompt | Setting | Recommended | Allowed |
|---|---|---|---|
| Passages returned per search (top_k) | `top_k_chunks` | 6 (advanced searches return twice this) | 1 to 50 |
| Passages to rerank (candidate limit) | `max_chunks_to_rerank` | 300 | 1 to 500, or `0` / `all` for no limit |
| Passages allowed from one page | `max_chunks_per_url` | 2 | 1 to 50 |

At each number prompt: Enter keeps the value shown, `r` selects the recommended value, or type
a number. A value equal to the recommendation is not written to the config file, so your file
only lists what you changed.

```bash
trovia setup --yes      # ask nothing: keep current settings, create the config, download the model
```

## `trovia config`

Run with no arguments to go through the same questions again, with your current values shown.
Press Enter at a key prompt to keep it, or type `clear` to remove it.

```bash
trovia config show                      # current values, with where each one comes from
trovia config set top_k_chunks 10       # change one setting
trovia config set max-chunks-per-url 1  # dashes work too
trovia config unset top_k_chunks        # back to the default
trovia config path                      # where the config file is
```

`config show` hides keys (it only shows the last four characters) and labels each value
`[default]`, `[config file]` or `[environment]`:

```
  brave_api_key          set, ends in 9999        [config file]
  top_k_chunks           12                       [config file]
  port                   8123                     [environment]
```

Changes reach a running `trovia` service and any open MCP server on their next search, without a
restart (except `host`, `port` and a few others; see
[configuration](configuration.md#when-changes-take-effect)). `config unset` only accepts known setting
names, so a typo is reported instead of silently doing nothing.

For API keys, prefer the interactive `trovia config`: `config set` puts the key on the command
line, where your shell may record it. The full list of settings is in
[configuration](configuration.md).

## `trovia mcp`

Runs the MCP server on stdio. You do not run this yourself; your MCP client launches it. See
[mcp.md](mcp.md).

## `trovia search`

Runs one search and prints the result as Markdown, the same text the API returns as
`synthesized_context`. It is a quick way to check your setup.

```bash
trovia search "python asyncio gather vs taskgroup"
trovia search "rust tokio mutex" --depth advanced -k 8 --per-page 1
trovia search "postgres index types" --json
```

| Option | Meaning |
|---|---|
| `--depth`, `-d` | `basic` (default) or `advanced` |
| `--top-k`, `-k` | Passages to return |
| `--per-page` | Most passages from one page |
| `--rerank` | Most passages to rerank |
| `--json` | Print the full JSON response instead of the Markdown |

A footer such as `[brave, 4210 ms, 6 passages]` goes to stderr, so piping the output keeps only the
Markdown. It does not need the service to be running.

## `trovia doctor`

Checks each part and prints one line per check:

```
[ ok ] Config file     C:\Users\you\AppData\Local\trovia\config.toml
[ ok ] Data folder     C:\Users\you\AppData\Local\trovia
[ ok ] Reranker model  ms-marco-TinyBERT-L-2-v2
[warn] Brave           no key set (skipped)
[warn] Serper          no key set (skipped)
[ ok ] SearXNG         not enabled (optional)
[ ok ] DuckDuckGo      returned results
[ ok ] Jina            no key (limited to about 20 requests a minute)
[ ok ] Port            8000 is free
```

`warn` means something is optional or temporarily off; `FAIL` means it needs fixing, and the
command then exits with status 1. Brave and Serper checks use one real search each. A DuckDuckGo
warning usually means it is rate-limiting you for a minute or two.

## Exit codes

`0` success; `1` a failure (search failed, a doctor check failed, port in use); `2` invalid input
(a bad option or setting value).
