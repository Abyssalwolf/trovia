"""Interactive setup. Used by `trovia setup`, `trovia config`, and the first run of `trovia`."""

from typing import Callable

import typer

from . import keys
from .config import (
    RECOMMENDED_PER_URL,
    RECOMMENDED_RERANK_CAP,
    RECOMMENDED_TOP_K,
    config_path,
    get_settings,
    read_config_file,
    write_config_file,
)

KEEP = "Enter to keep"


def _mask(value: str) -> str:
    return f"set, ends in {value[-4:]}" if value else "not set"


def _prompt_key(
    name: str,
    label: str,
    blurb: str,
    current: str,
    check: Callable[[str], keys.KeyCheck] | None,
) -> dict:
    """Ask for one API key. Returns {} (no change), {name: value} or {name: None} (remove)."""
    typer.echo(blurb)
    hint = f"{_mask(current)}; {KEEP}, or type 'clear' to remove" if current else "Enter to skip"
    while True:
        raw = typer.prompt(
            f"{label} ({hint}; typing is hidden)", default="", show_default=False, hide_input=True
        ).strip()
        if not raw:
            return {}
        if raw.lower() == "clear":
            return {name: None}
        if check is None:
            return {name: raw}
        typer.echo("  Checking the key (uses 1 search)...")
        result = check(raw)
        if result.status == "valid":
            typer.echo("  Key works." + (f" Note: {result.detail}." if result.detail else ""))
            return {name: raw}
        if result.status == "invalid":
            typer.echo(f"  That key was rejected ({result.detail}).")
            if typer.confirm("  Try again?", default=True):
                continue
            return {}
        typer.echo(f"  Could not check the key: {result.detail}.")
        return {name: raw} if typer.confirm("  Save it anyway?", default=False) else {}


def _prompt_number(label: str, current: int, recommended: int, low: int, high: int, zero_means: str | None = None) -> int:
    note = f"recommended: {recommended}" + (f", current: {current}" if current != recommended else "")
    extra = f"; 0 = {zero_means}" if zero_means else ""
    while True:
        raw = typer.prompt(
            f"{label} [{note}{extra}; Enter keeps {current}, 'r' = recommended]",
            default=str(current),
            show_default=False,
        ).strip().lower()
        if raw in ("r", "recommended"):
            return recommended
        if zero_means and raw in ("all", zero_means):
            return 0
        try:
            value = int(raw)
        except ValueError:
            typer.echo("  Please enter a whole number.")
            continue
        if (zero_means and value == 0) or low <= value <= high:
            return value
        typer.echo(f"  Please enter a number from {low} to {high}" + (" (or 0)." if zero_means else "."))


def _as_default(key: str, value: int, recommended: int) -> dict:
    """Store only values that differ from the recommendation, so the file stays minimal."""
    return {key: None if value == recommended else value}


def run_wizard(first_run: bool) -> dict:
    """Ask the questions and return the config.toml updates (not yet written)."""
    s = get_settings()
    stored = read_config_file()
    updates: dict = {}

    typer.echo("")
    typer.echo("Trovia setup" if first_run else "Trovia settings")
    typer.echo("Press Enter to skip a question or keep the value shown." if not first_run
               else "Press Enter to skip a question or accept the recommended value.")
    typer.echo("")
    typer.echo("Step 1 of 2: search providers")
    typer.echo("Trovia works with no keys at all: it falls back to DuckDuckGo. That is free but")
    typer.echo("best-effort and can be rate-limited. A Brave or Serper key makes search more reliable.")
    typer.echo("")
    updates |= _prompt_key(
        "brave_api_key",
        "Brave Search API key",
        "Brave: https://brave.com/search/api  (a monthly credit covers roughly 1,000 searches; a card is required)",
        s.brave_api_key if "brave_api_key" in stored else "",
        keys.check_brave,
    )
    typer.echo("")
    updates |= _prompt_key(
        "serper_api_key",
        "Serper API key",
        "Serper: https://serper.dev  (Google results; new accounts get a free starter allowance)",
        s.serper_api_key if "serper_api_key" in stored else "",
        keys.check_serper,
    )
    typer.echo("")
    updates |= _prompt_key(
        "jina_api_key",
        "Jina API key (optional)",
        "Jina reads pages that block direct access. A free key raises its limit from about 20 to about 500 requests a minute.",
        s.jina_api_key if "jina_api_key" in stored else "",
        None,
    )

    typer.echo("")
    typer.echo("Step 2 of 2: defaults for every search (each search can still override them)")
    typer.echo("")
    top_k = _prompt_number("Passages returned per search (top_k)", s.top_k_chunks, RECOMMENDED_TOP_K, 1, 50)
    typer.echo("  (Advanced searches return twice this many.)")
    cap = _prompt_number(
        "Passages to rerank (candidate limit)", s.max_chunks_to_rerank, RECOMMENDED_RERANK_CAP, 1, 500, zero_means="all"
    )
    per_url = _prompt_number("Passages allowed from one page", s.max_chunks_per_url, RECOMMENDED_PER_URL, 1, 50)
    updates |= _as_default("top_k_chunks", top_k, RECOMMENDED_TOP_K)
    updates |= _as_default("max_chunks_to_rerank", cap, RECOMMENDED_RERANK_CAP)
    updates |= _as_default("max_chunks_per_url", per_url, RECOMMENDED_PER_URL)
    return updates


def finish(updates: dict, prepare_model: Callable[[], None] | None) -> None:
    """Write the config, load it, make sure the reranker model is present, and print next steps."""
    path = write_config_file(updates)
    get_settings.cache_clear()
    s = get_settings()
    typer.echo("")
    typer.echo(f"Saved to {path}")
    if prepare_model is not None:
        typer.echo("Preparing the reranker model (about 3 MB, downloaded once)...")
        try:
            prepare_model()
            typer.echo("Model ready.")
        except Exception as e:  # offline, etc. It will be fetched on first use.
            typer.echo(f"Could not download it now ({type(e).__name__}); it will download on first use.")
    from .discovery import active_providers

    typer.echo("")
    typer.echo("Search order: " + " -> ".join(active_providers(s)))
    typer.echo("")
    typer.echo("Next:")
    typer.echo("  trovia            start the service (REST API on http://127.0.0.1:%d)" % s.port)
    typer.echo("  trovia config     change these settings later")
    typer.echo("  trovia doctor     check that everything works")
