# Installing Trovia

Trovia installs as a single command, `trovia`. The installers set it up in its own isolated
environment, so it never touches your other Python projects, and you do not need Python
installed first.

## Quick install

**macOS and Linux**

```bash
curl -LsSf https://YOUR-SITE/install.sh | sh
```

**Windows (PowerShell)**

```powershell
irm https://YOUR-SITE/install.ps1 | iex
```

Each installer:

1. installs [uv](https://docs.astral.sh/uv/) if you do not have it (a small Python tool installer
   from Astral; no administrator rights needed),
2. installs `trovia` with uv,
3. starts `trovia setup`, which asks about API keys and defaults and downloads the reranker model
   (about 3 MB).

Read the installer before you run it if you like: the scripts are `scripts/install.sh` and
`scripts/install.ps1` in this repository. They accept these environment variables:

| Variable | Effect |
|---|---|
| `TROVIA_PACKAGE` | What to install. Default `trovia`. Use `trovia==0.1.0` to pin a version. |
| `TROVIA_NO_SETUP=1` | Install only; skip the setup questions. |
| `TROVIA_NO_MODIFY_PATH=1` | Do not edit your shell profile or user PATH. |

If the installer says to open a new terminal, do that once so your PATH includes the new command.

## Other ways to install

If you already use uv or pipx:

```bash
uv tool install trovia        # or: pipx install trovia
trovia setup
```

To try it without installing: `uvx trovia search "your question"`.

## First run

```bash
trovia            # first run: asks the setup questions, then starts the service
```

Check everything is working with:

```bash
trovia doctor
```

The service listens on <http://127.0.0.1:8000>. See [cli.md](cli.md) for every command.

## Update and uninstall

```bash
uv tool upgrade trovia        # update
uv tool uninstall trovia      # remove the command
```

Your settings and cache are kept when you uninstall. To remove them too, delete the two folders
shown by `trovia config path` (the config folder) and in [configuration](configuration.md#where-things-live)
(the data folder).

## Docker

If you prefer a container, or want the optional SearXNG provider, use Docker Compose from this
repository:

```bash
docker compose up -d --build    # starts the API on http://127.0.0.1:8000
```

To add API keys or change settings, copy `.env.example` to `.env`, edit it, and run
`docker compose up -d` again. Without a `.env` the container runs with the defaults (DuckDuckGo).

```bash
cp .env.example .env
```

The container is configured with environment variables in `.env` (it has no config file), and
keeps its cache and model in `./data`. To add SearXNG, see
[configuration](configuration.md#optional-searxng).

## Requirements

- Windows, macOS or Linux, with internet access (for searching and, once, for the model download).
- About 400 MB of free memory while running, and a few hundred MB of disk for the install.
- Python 3.11 or newer is only needed if you install with pip or pipx yourself; uv fetches its own.

## Troubleshooting the install

**`trovia: command not found` after installing.** Open a new terminal. If that does not help, run
`uv tool update-shell`, or add the folder printed by `uv tool dir --bin` to your PATH.

**The installer cannot download uv.** You may be offline or behind a proxy that blocks astral.sh.
Install uv another way (see its documentation), then run `uv tool install trovia`.

**Corporate or antivirus software blocks the script.** The installer is plain text; you can
download it, read it, and run it from disk instead of piping it.

**`trovia setup` cannot download the model.** The model comes from Hugging Face. Check your
connection and run `trovia setup` again; it also downloads on first use.
