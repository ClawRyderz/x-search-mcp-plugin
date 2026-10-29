from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import x_search_mcp  # noqa: E402

CLI_SPEC = spec_from_file_location("x_search_cli", SCRIPTS_DIR / "x_search_cli.py")
assert CLI_SPEC is not None and CLI_SPEC.loader is not None
CLI_MODULE = module_from_spec(CLI_SPEC)
CLI_SPEC.loader.exec_module(CLI_MODULE)


def _fake_fetch(calls: list[tuple[str, str]]):
    def fake_fetch_json_once(*, request_url: str, bearer_token: str, operation_name: str):
        del operation_name
        calls.append((request_url, bearer_token))
        post = {"id": "42", "text": "hello", "author_id": "7"}
        users = {"users": [{"id": "7", "username": "someone", "name": "Someone"}]}
        if "/search/recent" in request_url:
            return ({"data": [post], "includes": users, "meta": {"result_count": 1}}, {})
        return ({"data": post, "includes": users}, {})

    return fake_fetch_json_once


@pytest.mark.parametrize(
    "target", ["https://x.com/someone/status/42?s=20", "twitter.com/someone/status/42", "42"]
)
def test_post_fetches_by_url_or_id_with_the_configured_bearer(
    target: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setenv("X_SEARCH_BEARER_TOKEN", "proxy-placeholder")
    monkeypatch.setenv("X_SEARCH_CONFIG_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setattr(x_search_mcp, "_fetch_json_once", _fake_fetch(calls))

    assert CLI_MODULE.main(["post", target]) == 0

    [(request_url, bearer)] = calls
    assert request_url.startswith("https://api.x.com/2/tweets?ids=42&")
    assert bearer == "proxy-placeholder"
    output = json.loads(capsys.readouterr().out)
    assert output["post"]["text"] == "hello"


def test_search_prints_posts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setenv("X_SEARCH_BEARER_TOKEN", "proxy-placeholder")
    monkeypatch.setenv("X_SEARCH_CONFIG_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setattr(x_search_mcp, "_fetch_json_once", _fake_fetch(calls))

    assert CLI_MODULE.main(["search", "from:someone", "--max-results", "10"]) == 0

    assert "query=from%3Asomeone" in calls[0][0]
    assert json.loads(capsys.readouterr().out)["posts"][0]["text"] == "hello"


def test_rejected_credential_exits_nonzero_with_a_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def unauthorized(*, request_url: str, bearer_token: str, operation_name: str):
        raise x_search_mcp._XRequestError(
            operation_name=operation_name, status_code=401, detail="Unauthorized"
        )

    monkeypatch.setenv("X_SEARCH_BEARER_TOKEN", "proxy-placeholder")
    monkeypatch.setenv("X_SEARCH_CONFIG_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setattr(x_search_mcp, "_fetch_json_once", unauthorized)

    assert CLI_MODULE.main(["post", "42"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "HTTP 401" in captured.err
