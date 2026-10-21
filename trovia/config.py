import os
import tomllib
from pathlib import Path
from typing import Any

import platformdirs
import tomli_w
from pydantic import model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

APP_NAME = "trovia"

# Recommended values, shown in the setup wizard next to each prompt.
RECOMMENDED_TOP_K = 6
RECOMMENDED_PER_URL = 2
# Measured on real advanced searches (pools of 150-215 passages): scoring everything takes ~0.3 s,
# while a cap of 100 dropped 4 of the top 12 passages. 300 only bounds the worst case. 0 = no cap.
RECOMMENDED_RERANK_CAP = 300


def config_dir() -> Path:
    """Per-user folder for config.toml. Override with TROVIA_CONFIG_DIR."""
    override = os.environ.get("TROVIA_CONFIG_DIR")
    return Path(override) if override else Path(platformdirs.user_config_dir(APP_NAME, appauthor=False, roaming=False))


def data_dir() -> Path:
    """Per-user folder for the cache and the reranker model. Override with TROVIA_DATA_DIR."""
    override = os.environ.get("TROVIA_DATA_DIR")
    return Path(override) if override else Path(platformdirs.user_data_dir(APP_NAME, appauthor=False, roaming=False))


def config_path() -> Path:
    return config_dir() / "config.toml"


def read_config_file() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def write_config_file(updates: dict[str, Any]) -> Path:
    """Merge `updates` into config.toml. A value of None removes that key."""
    data = read_config_file()
    for key, value in updates.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(data), encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o600)  # the file holds API keys
    return path


class Settings(BaseSettings):
    """Precedence, highest first: environment variables, config.toml, defaults."""

    # An empty variable (e.g. a blank BRAVE_API_KEY= line) counts as unset, so it can't
    # silently hide a value saved in config.toml.
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    # Host names the API will answer to; blocks DNS-rebinding from web pages.
    allowed_hosts: str = "localhost,127.0.0.1"

    # Stage 1: discovery
    brave_api_key: str = ""
    serper_api_key: str = ""
    # Optional self-hosted SearXNG (advanced). Empty = SearXNG is not used.
    searxng_url: str = ""
    # Providers are tried in this order; any that is not configured is skipped.
    # ddgs (DuckDuckGo) needs no key, so it is always available as the last resort.
    provider_order: str = "brave,serper,searxng,ddgs"
    brave_timeout_sec: float = 5.0
    serper_timeout_sec: float = 5.0
    searxng_timeout_sec: float = 10.0
    ddgs_timeout_sec: float = 10.0
    # Brave's $5 monthly credit covers ~1,000 queries; stop short of it.
    brave_monthly_limit: int = 950

    # Load the reranker at server startup instead of first request.
    warmup: bool = True

    # Stage 2: extraction
    jina_api_key: str = ""
    tier1_timeout_sec: float = 5.0
    tier2_timeout_sec: float = 10.0
    global_scrape_timeout_sec: float = 20.0

    # Stage 3 / user defaults for every search (a request can override each one)
    top_k_chunks: int = RECOMMENDED_TOP_K  # advanced depth returns twice as many
    max_chunks_to_rerank: int = RECOMMENDED_RERANK_CAP  # 0 = score every candidate
    max_chunks_per_url: int = RECOMMENDED_PER_URL
    # TinyBERT is ~50x faster than MiniLM-L-12 on CPU (see Phase 4 benchmark).
    rerank_model: str = "ms-marco-TinyBERT-L-2-v2"
    models_dir: str = ""
    cache_dir: str = ""
    serp_cache_ttl_sec: int = 3600
    url_cache_ttl_sec: int = 86400

    @model_validator(mode="after")
    def _default_paths(self) -> "Settings":
        if not self.cache_dir:
            self.cache_dir = str(data_dir() / "cache")
        if not self.models_dir:
            self.models_dir = str(data_dir() / "models")
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=config_path()),
        )

    @property
    def providers(self) -> list[str]:
        return [p.strip().lower() for p in self.provider_order.split(",") if p.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]


_settings_cache: tuple[int | None, Path, Settings] | None = None


def _config_mtime(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None


def get_settings() -> Settings:
    """Current settings. Rebuilt whenever config.toml changes, so `trovia config` reaches a
    running service or MCP server on its next search without a restart. (Environment variables
    are read when the settings are built; changing them still needs a restart.)"""
    global _settings_cache
    path = config_path()
    mtime = _config_mtime(path)
    if _settings_cache is None or _settings_cache[0] != mtime or _settings_cache[1] != path:
        _settings_cache = (mtime, path, Settings())
    return _settings_cache[2]


def _clear_settings_cache() -> None:
    global _settings_cache
    _settings_cache = None


get_settings.cache_clear = _clear_settings_cache  # same API the old lru_cache offered
