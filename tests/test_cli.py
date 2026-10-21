import os
import socket

import httpx
import respx
from typer.testing import CliRunner

from trovia import cli, keys
from trovia.config import config_path, get_settings, read_config_file, write_config_file
from trovia.keys import KeyCheck
from trovia.schemas import SearchResponse, SearchResultItem

runner = CliRunner()


def stub_model(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_prepare_model", lambda: calls.append(1))
    return calls


def stub_keys(monkeypatch, brave=KeyCheck("valid"), serper=KeyCheck("valid")):
    seen = []
    monkeypatch.setattr(keys, "check_brave", lambda k: seen.append(("brave", k)) or brave)
    monkeypatch.setattr(keys, "check_serper", lambda k: seen.append(("serper", k)) or serper)
    return seen


def test_version():
    r = runner.invoke(cli.app, ["--version"])
    assert r.exit_code == 0 and r.output.startswith("trovia ")


def test_setup_accepting_everything_writes_an_empty_config(monkeypatch):
    model = stub_model(monkeypatch)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.setenv("SEARXNG_URL", "")
    get_settings.cache_clear()
    r = runner.invoke(cli.app, ["setup"], input="\n" * 6)
    assert r.exit_code == 0, r.output
    assert config_path().exists() and read_config_file() == {}
    assert model == [1]
    assert "recommended: 6" in r.output and "recommended: 300" in r.output and "recommended: 2" in r.output
    assert "Search order: ddgs" in r.output  # no keys -> DuckDuckGo only


def test_setup_saves_a_valid_key_and_custom_defaults(monkeypatch):
    stub_model(monkeypatch)
    seen = stub_keys(monkeypatch)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.setenv("SEARXNG_URL", "")
    get_settings.cache_clear()
    # brave key, no serper, no jina, top_k 9, cap 0 (= all), per page 3
    r = runner.invoke(cli.app, ["setup"], input="brave-secret\n\n\n9\nall\n3\n")
    assert r.exit_code == 0, r.output
    assert read_config_file() == {"brave_api_key": "brave-secret", "top_k_chunks": 9, "max_chunks_to_rerank": 0, "max_chunks_per_url": 3}
    assert seen == [("brave", "brave-secret")]
    assert "Key works" in r.output and "Search order: brave -> ddgs" in r.output
    assert "brave-secret" not in r.output  # typing is hidden, never echoed back


def test_values_equal_to_the_recommendation_are_not_written(monkeypatch):
    stub_model(monkeypatch)
    r = runner.invoke(cli.app, ["setup"], input="\n\n\n6\nr\n2\n")
    assert r.exit_code == 0 and read_config_file() == {}


def test_rejected_key_is_not_saved_when_the_user_gives_up(monkeypatch):
    stub_model(monkeypatch)
    stub_keys(monkeypatch, brave=KeyCheck("invalid", "the provider answered HTTP 401"))
    r = runner.invoke(cli.app, ["setup"], input="bad-key\nn\n\n\n\n\n\n")
    assert r.exit_code == 0, r.output
    assert "rejected" in r.output and "brave_api_key" not in read_config_file()


def test_rejected_key_can_be_retried(monkeypatch):
    stub_model(monkeypatch)
    results = iter([KeyCheck("invalid", "HTTP 401"), KeyCheck("valid")])
    monkeypatch.setattr(keys, "check_brave", lambda k: next(results))
    r = runner.invoke(cli.app, ["setup"], input="bad\ny\ngood\n\n\n\n\n\n")
    assert r.exit_code == 0 and read_config_file() == {"brave_api_key": "good"}


def test_unverifiable_key_is_saved_only_if_the_user_agrees(monkeypatch):
    stub_model(monkeypatch)
    stub_keys(monkeypatch, brave=KeyCheck("unknown", "could not reach Brave (ConnectError)"))
    runner.invoke(cli.app, ["setup"], input="offline-key\ny\n\n\n\n\n\n")
    assert read_config_file() == {"brave_api_key": "offline-key"}
    runner.invoke(cli.app, ["config"], input="clear\n\n\n\n\n\n")  # edit mode: remove it again
    assert "brave_api_key" not in read_config_file()


def test_out_of_range_numbers_are_asked_again(monkeypatch):
    stub_model(monkeypatch)
    r = runner.invoke(cli.app, ["setup"], input="\n\n\n99\nabc\n7\n\n\n")
    assert r.exit_code == 0 and read_config_file() == {"top_k_chunks": 7}
    assert "from 1 to 50" in r.output and "whole number" in r.output


def test_config_with_enter_everywhere_changes_nothing(monkeypatch):
    stub_keys(monkeypatch)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    write_config_file({"brave_api_key": "keep-me-1234", "top_k_chunks": 9})
    get_settings.cache_clear()
    r = runner.invoke(cli.app, ["config"], input="\n" * 6)
    assert r.exit_code == 0, r.output
    assert read_config_file() == {"brave_api_key": "keep-me-1234", "top_k_chunks": 9}
    assert "set, ends in 1234" in r.output and "current: 9" in r.output


def test_config_show_masks_keys_and_reports_sources(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    write_config_file({"brave_api_key": "abcdefgh-9999", "top_k_chunks": 12})
    monkeypatch.setenv("PORT", "8123")
    get_settings.cache_clear()
    out = runner.invoke(cli.app, ["config", "show"]).output
    assert "abcdefgh" not in out and "ends in 9999" in out
    assert "top_k_chunks" in out and "[config file]" in out
    assert "8123" in out and "[environment]" in out
    assert "(not set)" in out and "[default]" in out


def test_config_set_unset_and_path():
    assert runner.invoke(cli.app, ["config", "set", "top_k_chunks", "12"]).exit_code == 0
    assert runner.invoke(cli.app, ["config", "set", "max-chunks-per-url", "1"]).exit_code == 0
    assert read_config_file() == {"top_k_chunks": 12, "max_chunks_per_url": 1}
    assert runner.invoke(cli.app, ["config", "unset", "top_k_chunks"]).exit_code == 0
    assert read_config_file() == {"max_chunks_per_url": 1}
    assert runner.invoke(cli.app, ["config", "path"]).output.strip() == str(config_path())


def test_config_set_rejects_bad_input():
    for args in (["nonsense", "1"], ["port", "abc"], ["top_k_chunks", "0"], ["max_chunks_per_url", "99"], ["port", "70000"]):
        r = runner.invoke(cli.app, ["config", "set", *args])
        assert r.exit_code == 2, args
    assert read_config_file() == {}


def _response(**kw):
    item = SearchResultItem(
        title="T", url="https://t.com", chunk_content="hello", relevance_score=0.9, extraction_tier="tier1_trafilatura"
    )
    base = dict(
        query="q", search_provider_used="ddgs", latency_ms=5,
        synthesized_context="## Source: T (https://t.com)\nhello", results=[item],
    )
    return SearchResponse(**{**base, **kw})


def test_search_command_prints_the_context(monkeypatch):
    seen = {}

    async def fake(req):
        seen["req"] = req
        return _response()

    monkeypatch.setattr("trovia.pipeline.run_search", fake)
    r = runner.invoke(cli.app, ["search", "my question", "--depth", "advanced", "-k", "3", "--per-page", "1", "--rerank", "50"])
    assert r.exit_code == 0 and "## Source: T (https://t.com)" in r.output
    q = seen["req"]
    assert (q.query, q.search_depth, q.top_k_chunks, q.max_chunks_per_url, q.max_chunks_to_rerank) == (
        "my question", "advanced", 3, 1, 50
    )


def test_search_command_json_and_failure(monkeypatch):
    async def ok(req):
        return _response()

    monkeypatch.setattr("trovia.pipeline.run_search", ok)
    out = runner.invoke(cli.app, ["search", "q", "--json"]).output
    assert '"synthesized_context"' in out and '"results"' in out

    async def bad(req):
        return _response(synthesized_context="", results=[], error="no search provider returned results")

    monkeypatch.setattr("trovia.pipeline.run_search", bad)
    r = runner.invoke(cli.app, ["search", "q"])
    assert r.exit_code == 1 and "Search failed" in r.output


def test_search_command_rejects_bad_options():
    assert runner.invoke(cli.app, ["search", "q", "--depth", "turbo"]).exit_code == 2
    assert runner.invoke(cli.app, ["search", "q", "-k", "0"]).exit_code == 2


def test_no_command_starts_the_service_without_prompting_when_not_interactive(monkeypatch):
    started = []
    monkeypatch.setattr(cli, "_serve", lambda host, port: started.append((host, port)))
    r = runner.invoke(cli.app, [])
    assert r.exit_code == 0 and started == [(None, None)]
    assert "Step 1 of 2" not in r.output  # CliRunner is not a TTY, so no wizard


def test_serve_refuses_a_port_that_is_taken():
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        port = taken.getsockname()[1]
        r = runner.invoke(cli.app, ["serve", "--port", str(port)])
    assert r.exit_code == 1 and "already in use" in r.output


def test_mcp_command_runs_the_stdio_server(monkeypatch):
    seen = []
    from trovia import mcp_server

    monkeypatch.setattr(mcp_server.mcp, "run", lambda transport: seen.append(transport))
    assert runner.invoke(cli.app, ["mcp"]).exit_code == 0 and seen == ["stdio"]


@respx.mock
def test_key_checks_classify_responses():
    cases = (
        (keys.check_brave, respx.get, keys.BRAVE_URL, (401, 403, 422)),
        (keys.check_serper, respx.post, keys.SERPER_URL, (401, 403)),
    )
    for fn, method, url, rejected in cases:
        route = method(url)
        route.respond(200)
        assert fn("k").status == "valid"
        for code in rejected:
            route.respond(code)
            assert fn("k").status == "invalid", (fn.__name__, code)
        route.respond(429)
        r = fn("k")
        assert r.status == "valid" and "quota" in r.detail
        route.respond(500)
        assert fn("k").status == "unknown"
        route.mock(side_effect=httpx.ConnectTimeout("slow"))
        assert fn("k").status == "unknown"


@respx.mock
def test_doctor_reports_each_part(monkeypatch):
    from trovia import doctor

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    monkeypatch.setenv("PORT", str(free_port))
    get_settings.cache_clear()
    respx.get("http://searxng.test/search").respond(200, json={"results": []})
    checks = {
        c.name: c
        for c in doctor.run_checks(
            check_brave=lambda k: KeyCheck("valid"),
            check_serper=lambda k: KeyCheck("invalid", "the provider answered HTTP 401"),
        )
    }
    assert checks["Brave"].status == "ok"
    assert checks["Serper"].status == "fail" and "trovia config" in checks["Serper"].detail
    assert checks["SearXNG"].status == "ok"
    assert checks["DuckDuckGo"].status == "warn"  # the test fixture makes it fail
    assert checks["Config file"].status == "warn" and checks["Data folder"].status == "ok"
    assert checks["Port"].status == "ok"


def test_port_check_is_not_fooled_by_time_wait_after_a_server_stops():
    import time

    server = socket.socket()
    if os.name == "posix":
        # Behave like uvicorn, whose listener sets SO_REUSEADDR. Linux only lets a new bind
        # through a TIME_WAIT socket when both sockets set it (checked on real Linux).
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.listen()
    client = socket.create_connection(("127.0.0.1", port))
    conn, _ = server.accept()
    conn.close()  # the server side closes first, leaving its end of the port in TIME_WAIT
    time.sleep(0.2)
    client.close()
    server.close()
    assert cli._port_in_use("127.0.0.1", port) is False


def test_config_unset_rejects_unknown_names_and_does_not_create_a_file():
    r = runner.invoke(cli.app, ["config", "unset", "top_k"])  # typo for top_k_chunks
    assert r.exit_code == 2 and "Unknown setting" in r.output
    r = runner.invoke(cli.app, ["config", "unset", "top_k_chunks"])
    assert r.exit_code == 0 and "already using its default" in r.output
    assert not config_path().exists()  # so the first-run wizard still runs later
