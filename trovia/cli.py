import asyncio
import os
import socket
import sys
from typing import Annotated

import typer
from pydantic import TypeAdapter, ValidationError

from . import __version__
from .config import Settings, config_path, get_settings, read_config_file, write_config_file

app = typer.Typer(
    help="Trovia: local web search and page reading for AI agents. Run `trovia` with no command to start the service.",
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
config_app = typer.Typer(
    help="View and change settings. Run `trovia config` with no command to edit them interactively.",
    add_completion=False,
    invoke_without_command=True,
)
app.add_typer(config_app, name="config")


def _utf8_streams() -> None:
    """Web text can contain any character; never crash on a legacy Windows code page."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _version_option(value: bool) -> None:
    if value:
        typer.echo(f"trovia {__version__}")
        raise typer.Exit()


def _prepare_model() -> None:
    from .reranker import get_ranker

    get_ranker()


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket() as sock:
        if os.name == "posix":
            # Like uvicorn: ignore TIME_WAIT leftovers from a server that just stopped, so a
            # quick restart isn't refused. A port someone is listening on still fails to bind.
            # (Not on Windows, where SO_REUSEADDR would let us bind over a live listener.)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


def _serve(host: str | None, port: int | None) -> None:
    s = get_settings()
    host, port = host or s.host, port or s.port
    if _port_in_use(host, port):
        typer.echo(f"Port {port} is already in use. Is Trovia already running?", err=True)
        typer.echo(f"Use a different port:  trovia serve --port {port + 1}   (or: trovia config set port {port + 1})", err=True)
        raise typer.Exit(1)

    from .discovery import active_providers

    active = active_providers(s)
    shown = "127.0.0.1" if host == "0.0.0.0" else host
    typer.echo(f"Trovia {__version__}")
    typer.echo(f"  REST API   http://{shown}:{port}   (interactive docs at /docs)")
    typer.echo("  MCP        add `trovia mcp` to your MCP client (see the docs)")
    typer.echo("  Search     " + " -> ".join(active))
    typer.echo("  Press Ctrl+C to stop.")
    typer.echo("")

    import uvicorn

    from .main import app as api

    uvicorn.run(api, host=host, port=port, log_level="info")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool, typer.Option("--version", callback=_version_option, is_eager=True, help="Show the version and exit.")
    ] = False,
) -> None:
    _utf8_streams()
    if ctx.invoked_subcommand is not None:
        return
    if not config_path().exists() and sys.stdin.isatty() and sys.stdout.isatty():
        from .wizard import finish, run_wizard

        typer.echo("Welcome to Trovia. Let's set it up first (you can change anything later with `trovia config`).")
        finish(run_wizard(first_run=True), _prepare_model)
        typer.echo("")
    _serve(None, None)


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Address to listen on. Default: 127.0.0.1")] = None,
    port: Annotated[int | None, typer.Option(help="Port to listen on. Default: 8000")] = None,
) -> None:
    """Start the REST API (same as running `trovia` with no command)."""
    _serve(host, port)


@app.command()
def setup(
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Ask nothing: keep current settings, create the config, download the model.")
    ] = False,
) -> None:
    """Guided first-time setup: API keys, defaults, and the reranker model."""
    from .wizard import finish, run_wizard

    finish({} if yes else run_wizard(first_run=not config_path().exists()), _prepare_model)


@app.command("mcp")
def mcp_command() -> None:
    """Run the MCP server over stdio, for Claude Code, Claude Desktop and other MCP clients."""
    from .mcp_server import mcp

    mcp.run(transport="stdio")


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="What to search for.")],
    depth: Annotated[str, typer.Option("--depth", "-d", help="basic or advanced")] = "basic",
    top_k: Annotated[int | None, typer.Option("--top-k", "-k", help="Passages to return.")] = None,
    per_page: Annotated[int | None, typer.Option("--per-page", help="Most passages from one page.")] = None,
    rerank: Annotated[int | None, typer.Option("--rerank", help="Most passages to rerank.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the full JSON response.")] = False,
) -> None:
    """Run one search from the terminal (handy for checking your setup)."""
    from .pipeline import run_search
    from .schemas import SearchRequest

    try:
        req = SearchRequest(
            query=query, search_depth=depth, top_k_chunks=top_k,
            max_chunks_per_url=per_page, max_chunks_to_rerank=rerank,
        )
    except ValidationError as e:
        first = e.errors()[0]
        typer.echo(f"Invalid option {first['loc'][-1]}: {first['msg']}", err=True)
        raise typer.Exit(2)

    resp = asyncio.run(run_search(req))
    if as_json:
        typer.echo(resp.model_dump_json(indent=2))
        return
    if resp.error:
        typer.echo(f"Search failed: {resp.error}", err=True)
        raise typer.Exit(1)
    typer.echo(resp.synthesized_context)
    typer.echo(f"\n[{resp.search_provider_used}, {resp.latency_ms} ms, {len(resp.results)} passages]", err=True)


@app.command()
def doctor() -> None:
    """Check the config, data folder, model, search providers and port."""
    from .doctor import run_checks

    labels = {"ok": " ok ", "warn": "warn", "fail": "FAIL"}
    checks = run_checks()
    for c in checks:
        typer.echo(f"[{labels[c.status]}] {c.name:<15} {c.detail}")
    if any(c.status == "fail" for c in checks):
        raise typer.Exit(1)


# ---- trovia config ----

SHOWN_KEYS = [
    "brave_api_key", "serper_api_key", "jina_api_key",
    "top_k_chunks", "max_chunks_to_rerank", "max_chunks_per_url",
    "provider_order", "searxng_url", "host", "port", "allowed_hosts",
]
RANGES = {"top_k_chunks": (1, 50), "max_chunks_to_rerank": (0, 500), "max_chunks_per_url": (1, 50), "port": (1, 65535)}


def _show_value(key: str, value) -> str:
    if key.endswith("_api_key"):
        return f"set, ends in {str(value)[-4:]}" if value else "(not set)"
    return "(empty)" if value in ("", None) else str(value)


@config_app.callback()
def config_main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    from .wizard import finish, run_wizard

    first_run = not config_path().exists()
    finish(run_wizard(first_run=first_run), _prepare_model if first_run else None)


@config_app.command("show")
def config_show() -> None:
    """Show the current settings and where each value comes from."""
    s = get_settings()
    stored = read_config_file()
    typer.echo(f"Config file: {config_path()}" + ("" if config_path().exists() else "  (not created yet)"))
    typer.echo("")
    for key in SHOWN_KEYS:
        source = "environment" if os.environ.get(key.upper()) else "config file" if key in stored else "default"
        typer.echo(f"  {key:<22} {_show_value(key, getattr(s, key)):<24} [{source}]")


@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Setting name, e.g. top_k_chunks or port")],
    value: Annotated[str, typer.Argument(help="New value")],
) -> None:
    """Change one setting. (For API keys, prefer the interactive `trovia config`, which hides what you type.)"""
    key = key.lower().replace("-", "_")
    field = Settings.model_fields.get(key)
    if field is None:
        typer.echo(f"Unknown setting '{key}'. Known settings: {', '.join(SHOWN_KEYS)}", err=True)
        raise typer.Exit(2)
    try:
        coerced = TypeAdapter(field.annotation).validate_python(value)
    except ValidationError:
        typer.echo(f"'{value}' is not a valid value for {key}.", err=True)
        raise typer.Exit(2)
    if key in RANGES and not (RANGES[key][0] <= coerced <= RANGES[key][1]):
        typer.echo(f"{key} must be between {RANGES[key][0]} and {RANGES[key][1]}.", err=True)
        raise typer.Exit(2)
    write_config_file({key: coerced})
    typer.echo(f"Set {key}.")


@config_app.command("unset")
def config_unset(key: Annotated[str, typer.Argument(help="Setting to reset to its default")]) -> None:
    """Remove a setting from the config file so the default applies again."""
    key = key.lower().replace("-", "_")
    if key not in Settings.model_fields:
        typer.echo(f"Unknown setting '{key}'. Known settings: {', '.join(SHOWN_KEYS)}", err=True)
        raise typer.Exit(2)
    if key not in read_config_file():
        typer.echo(f"{key} is not set in the config file; it is already using its default.")
        return
    write_config_file({key: None})
    typer.echo(f"Reset {key} to its default.")


@config_app.command("path")
def config_path_command() -> None:
    """Print where the config file lives."""
    typer.echo(str(config_path()))
