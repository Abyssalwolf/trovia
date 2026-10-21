import os
import stat

from trovia import config
from trovia.config import (
    RECOMMENDED_PER_URL,
    RECOMMENDED_RERANK_CAP,
    RECOMMENDED_TOP_K,
    config_path,
    get_settings,
    read_config_file,
    write_config_file,
)


def fresh(monkeypatch=None):
    get_settings.cache_clear()
    return get_settings()


def test_defaults_use_recommended_numbers(monkeypatch):
    for var in ("BRAVE_API_KEY", "SERPER_API_KEY", "SEARXNG_URL", "CACHE_DIR", "MODELS_DIR"):
        monkeypatch.delenv(var, raising=False)
    s = fresh()
    assert (s.top_k_chunks, s.max_chunks_to_rerank, s.max_chunks_per_url) == (
        RECOMMENDED_TOP_K, RECOMMENDED_RERANK_CAP, RECOMMENDED_PER_URL
    )
    assert (s.host, s.port) == ("127.0.0.1", 8000)


def test_paths_default_to_the_per_user_data_folder(monkeypatch):
    monkeypatch.delenv("CACHE_DIR", raising=False)
    monkeypatch.delenv("MODELS_DIR", raising=False)
    s = fresh()
    data = config.data_dir()
    assert s.cache_dir == str(data / "cache") and s.models_dir == str(data / "models")


def test_config_file_is_read(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    write_config_file({"brave_api_key": "from-file", "top_k_chunks": 9})
    s = fresh()
    assert s.brave_api_key == "from-file" and s.top_k_chunks == 9


def test_environment_overrides_the_config_file(monkeypatch):
    write_config_file({"brave_api_key": "from-file", "top_k_chunks": 9})
    monkeypatch.setenv("BRAVE_API_KEY", "from-env")
    s = fresh()
    assert s.brave_api_key == "from-env" and s.top_k_chunks == 9  # file still fills other keys


def test_write_merges_and_none_removes_a_key():
    write_config_file({"brave_api_key": "k", "port": 9000})
    write_config_file({"port": 9100, "brave_api_key": None})
    assert read_config_file() == {"port": 9100}


def test_missing_config_file_is_fine():
    assert not config_path().exists()
    assert read_config_file() == {}
    fresh()


def test_config_file_is_private_on_posix():
    path = write_config_file({"brave_api_key": "secret"})
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.exists()


def test_an_empty_environment_variable_does_not_hide_the_config_file(monkeypatch):
    write_config_file({"brave_api_key": "from-file"})
    monkeypatch.setenv("BRAVE_API_KEY", "")
    assert fresh().brave_api_key == "from-file"


def test_editing_the_config_file_reaches_a_running_process_without_a_restart(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    first = fresh()
    assert first.brave_api_key == ""
    path = write_config_file({"brave_api_key": "added-later"})
    os.utime(path, ns=(1, 1_000_000_000))  # make sure the change is visible even on coarse clocks
    assert get_settings().brave_api_key == "added-later"  # no cache_clear() here
    write_config_file({"top_k_chunks": 11})
    os.utime(path, ns=(2, 2_000_000_000))
    assert get_settings().top_k_chunks == 11


def test_settings_are_reused_while_the_file_is_unchanged():
    write_config_file({"top_k_chunks": 7})
    a = fresh()
    assert get_settings() is a
