# Development and troubleshooting

## Project layout

```
Searchable/                  (the repository folder; the product is called Trovia)
├── README.md
├── docs/                    this documentation
├── skills/                  ready-made agent skills (REST API, MCP)
├── scripts/
│   ├── install.sh           one-line installer for macOS and Linux
│   └── install.ps1          one-line installer for Windows
├── .github/workflows/       CI (tests, build, installer smoke test) and the PyPI release
├── docker-compose.yml       the API, plus optional SearXNG (profile "searxng")
├── Dockerfile               the API image
├── pyproject.toml           package metadata, dependencies, the `trovia` command
├── .env.example             environment variables for the Docker setup
├── searxng/settings.yml     optional SearXNG config
├── trovia/                  the Python package
│   ├── cli.py               the `trovia` command (serve, setup, config, mcp, search, doctor)
│   ├── wizard.py            the interactive setup questions
│   ├── doctor.py            the `trovia doctor` checks
│   ├── keys.py              checks that a Brave or Serper key works
│   ├── config.py            settings: environment > config.toml > defaults; per-user folders
│   ├── schemas.py           request and response models (pydantic)
│   ├── cache.py             disk cache, cache keys, monthly Brave counter
│   ├── discovery.py         Stage 1: Brave -> Serper -> SearXNG (optional) -> DuckDuckGo
│   ├── extractor.py         Stage 2: curl_cffi/trafilatura -> Jina -> snippet
│   ├── reranker.py          Stages 3-4: chunking, candidate selection, scoring, formatting
│   ├── pipeline.py          orchestrates the stages; response cache; error containment
│   ├── main.py              the FastAPI app (REST) and the Host-header check
│   └── mcp_server.py        the MCP server (stdio)
├── tests/                   pytest suite
└── data/                    only used by the Docker setup and by tests (not committed)
```

The REST API, the MCP server and the `trovia search` command are thin wrappers: they all build a
`SearchRequest` and call `pipeline.run_search`.

## Running from source

You need Python 3.11 to 3.14 and [uv](https://docs.astral.sh/uv/). The upper limit comes from
onnxruntime (used by the reranker), which has no wheels for Python 3.15 yet. When it does, raise
`requires-python` in `pyproject.toml` and the `--python` range in both install scripts.

```bash
uv sync --extra dev          # install runtime and test dependencies
uv run trovia setup          # or: uv run trovia --help
uv run trovia                # start the service
```

`uv sync` installs the project in editable mode, so code changes take effect immediately.

## Tests

```bash
uv run pytest -q
```

The suite covers provider fallback and caching, the extraction cascade and its validation gate, chunking
(including code blocks and single-line pages), candidate selection and per-page limits, the pipeline,
the REST API and its Host-header check, the MCP tool, the config system (precedence, the file, empty
variables), the setup wizard and every CLI command, key checking, and `doctor`. Network calls are
mocked; the one exception is the reranker model, which the reranker tests run for real (it is read from
`data/models`, and downloaded there if missing).

Every test runs against a temporary config and data folder, with fake API keys and DuckDuckGo blocked, so
the tests never touch your real settings, cache, or search quota.

Not covered by automated tests: live calls to Brave and Serper, the SSE transport of the MCP server, and
the interactive wizard in a real terminal (it is tested by feeding it input, not through a TTY).

## Building and installing a local build

```bash
uv build                                     # creates dist/trovia-<version>-py3-none-any.whl
uv tool install --force dist/trovia-*.whl    # install it as the `trovia` command
```

To test the installer scripts against a local build **without touching your real setup**, point uv at
throwaway folders and install the wheel by path:

```bash
export UV_TOOL_DIR=/tmp/t/tools UV_TOOL_BIN_DIR=/tmp/t/bin
export TROVIA_PACKAGE=$PWD/dist/trovia-0.1.0-py3-none-any.whl TROVIA_NO_SETUP=1 TROVIA_NO_MODIFY_PATH=1
sh scripts/install.sh && /tmp/t/bin/trovia --version
```

To run the installed command against throwaway config and data, set `TROVIA_CONFIG_DIR` and
`TROVIA_DATA_DIR`.

## Releasing

1. Update `version` in `pyproject.toml`.
2. Tag and push: `git tag v0.1.1 && git push origin v0.1.1`.
3. The `release` workflow builds the package and publishes it to PyPI using trusted publishing (no
   token is stored). Before the first release you must create the project on PyPI and register this
   repository and workflow as a trusted publisher (PyPI: project settings, Publishing).
4. Host `scripts/install.sh` and `scripts/install.ps1` at the URLs your website shows.

## Common changes

**Add a search provider.** In `trovia/discovery.py`, write an async function with the same signature as
`_brave`/`_serper`/`_searxng`/`_ddgs` that returns a list of `SearchHit`, add it to `_PROVIDERS`,
handle its credentials in `_configured`, and add settings for its key and timeout in `trovia/config.py`.
Users then enable it through `provider_order`.

**Add a setting.** Add a field to `Settings` in `trovia/config.py`. It is then available as an
environment variable, in `config.toml`, and through `trovia config set` automatically. If it should
appear in `trovia config show`, add it to `SHOWN_KEYS` in `trovia/cli.py`; if it should be asked in
setup, add a prompt in `trovia/wizard.py`.

**Change passage size.** Edit `TARGET_CHARS` and `OVERLAP_CHARS` in `trovia/reranker.py`. Passages much
larger than 800 characters are truncated by the reranker model, so larger is not necessarily better.

## Troubleshooting

Start with `trovia doctor`; it checks most of what is listed here.

**Searches return `error: "no search provider returned results"`.**
Every provider failed or returned nothing. If you have no API keys, DuckDuckGo is probably rate-limiting
you: wait a minute or add a Brave or Serper key (`trovia config`). Otherwise check the log output for
warnings naming each provider and the reason: a wrong key (401), no internet, or (if enabled) SearXNG
not running.

**Brave is never used even though I set a key.**
Check `provider_order` includes `brave`, and that you have not hit `brave_monthly_limit` (reset the
counter by deleting the `cache/usage` folder in the data folder). Run `trovia config show` to see whether
the key is being read, and from where.

**A setting seems to be ignored.**
An environment variable overrides the config file. `trovia config show` labels each value with its
source.

**Results look stale.**
Responses are cached for an hour and pages for a day. Send `"bypass_cache": true` (REST) or delete the
`cache` folder in the data folder.

**Many results are only snippets (`extraction_tier: "snippet_only"`).**
Those pages could not be read by either the direct fetch or Jina. This happens with sites that block
automated access outright or need a login. Jina's keyless limit is 20 requests a minute; an `advanced`
search can use 8 of them in one go, so adding a free Jina key helps.

**`Port 8000 is already in use`.**
Another program (or another copy of Trovia) is using it. Use `trovia serve --port 8001`, or change it
permanently with `trovia config set port 8001`.

**Requests fail with `Invalid host header` (HTTP 400).**
You are reaching the service by a hostname other than `localhost` or `127.0.0.1`. Add it to
`allowed_hosts` (`trovia config set allowed_hosts localhost,127.0.0.1,myname`).

**Memory use is higher than expected.**
Idle memory is about 100 MB and grows to roughly 400 MB after several `advanced` searches (measured in
Docker). If yours is much higher, reduce `SCORE_BATCH_SIZE` in `trovia/reranker.py`.

**The MCP client cannot start the server.**
Run `trovia mcp` in a terminal to see any error (it then waits for input; press Ctrl+C). If the client
cannot find `trovia`, give it the full path to the executable (see [mcp.md](mcp.md)).

**`curl` with a JSON body fails on Windows.**
Quoting rules differ in `cmd.exe` and PowerShell. Use the PowerShell example in
[rest-api.md](rest-api.md#powershell), or run curl from Git Bash.

## Known limitations

- No JavaScript rendering. Pages that need it fall back to Jina, then to the snippet.
- `relevance_score` values cluster near 1.0 for good matches; use them for ordering only.
- Scoring in batches shifts a passage's score slightly depending on its batch mates, which can reorder
  passages with nearly equal scores.
- No authentication; designed for `localhost` only.
- DuckDuckGo (the no-key provider) is best-effort and can be rate-limited.
- Uncached searches are not fast (typically 4 to 11 s), because each search waits for every page it reads.
