from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SCRIPT_PATH = REPO_ROOT / "scripts" / "x_search_mcp.py"
RENDER_MCP_PATH = REPO_ROOT / "scripts" / "render_mcp_config.py"
INSTALL_PATH = REPO_ROOT / "scripts" / "install.py"
PROVIDER_REFS_PATH = REPO_ROOT / "config" / "provider_refs.json"

PLUGIN_SPEC = spec_from_file_location("x_search_mcp", PLUGIN_SCRIPT_PATH)
if PLUGIN_SPEC is None or PLUGIN_SPEC.loader is None:
    raise RuntimeError("Unable to load x_search_mcp.py")
PLUGIN_MODULE = module_from_spec(PLUGIN_SPEC)
sys.modules[PLUGIN_SPEC.name] = PLUGIN_MODULE
PLUGIN_SPEC.loader.exec_module(PLUGIN_MODULE)

RENDER_SPEC = spec_from_file_location("x_search_render_mcp_config", RENDER_MCP_PATH)
if RENDER_SPEC is None or RENDER_SPEC.loader is None:
    raise RuntimeError("Unable to load render_mcp_config.py")
RENDER_MODULE = module_from_spec(RENDER_SPEC)
sys.modules[RENDER_SPEC.name] = RENDER_MODULE
RENDER_SPEC.loader.exec_module(RENDER_MODULE)

INSTALL_SPEC = spec_from_file_location("x_search_install", INSTALL_PATH)
if INSTALL_SPEC is None or INSTALL_SPEC.loader is None:
    raise RuntimeError("Unable to load install.py")
INSTALL_MODULE = module_from_spec(INSTALL_SPEC)
sys.modules[INSTALL_SPEC.name] = INSTALL_MODULE
INSTALL_SPEC.loader.exec_module(INSTALL_MODULE)


def test_committed_provider_config_contains_no_private_references() -> None:
    payload = json.loads(PROVIDER_REFS_PATH.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    assert "op://" not in serialized
    assert "op_service_account_token_file" not in payload
    assert payload["credential_sources"] == {
        "bearer_token_ref_candidates": [],
        "api_key_ref_candidates": [],
        "api_secret_ref_candidates": [],
    }


def test_normalize_x_status_url_adds_scheme_when_missing() -> None:
    assert (
        PLUGIN_MODULE._normalize_x_status_url("x.com/openai/status/1234567890")
        == "https://x.com/openai/status/1234567890"
    )


def test_extract_post_id_from_x_or_twitter_urls() -> None:
    assert (
        PLUGIN_MODULE._extract_post_id_from_url("https://x.com/openai/status/1234567890")
        == "1234567890"
    )
    assert (
        PLUGIN_MODULE._extract_post_id_from_url("https://twitter.com/openai/status/9876543210")
        == "9876543210"
    )


def test_render_mcp_config_writes_absolute_paths(tmp_path: Path) -> None:
    bundle_root = tmp_path / "x-search"
    (bundle_root / "scripts").mkdir(parents=True)
    (bundle_root / "config").mkdir(parents=True)
    output_path = tmp_path / ".mcp.json"

    exit_code = RENDER_MODULE.main(
        [
            "--bundle-root",
            str(bundle_root),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    server = payload["mcpServers"]["x-search-local"]

    assert exit_code == 0
    assert server["args"] == [str(bundle_root / "scripts" / "x_search_mcp.py")]
    assert server["env"]["X_SEARCH_CONFIG_FILE"] == str(
        bundle_root / "config" / "provider_refs.json"
    )


def test_install_copies_bundle_and_renders_absolute_mcp(tmp_path: Path) -> None:
    destination = tmp_path / "x-search-installed"

    exit_code = INSTALL_MODULE.main(
        [
            "--bundle-root",
            str(REPO_ROOT),
            "--destination",
            str(destination),
        ]
    )

    payload = json.loads((destination / ".mcp.json").read_text(encoding="utf-8"))
    server = payload["mcpServers"]["x-search-local"]

    assert exit_code == 0
    assert (destination / ".codex-plugin" / "plugin.json").exists()
    assert (destination / "scripts" / "x_search_mcp.py").exists()
    assert not (destination / ".git").exists()
    assert server["args"] == [str(destination / "scripts" / "x_search_mcp.py")]


def test_install_replaces_symlink_destination(tmp_path: Path) -> None:
    real_target = tmp_path / "real-target"
    real_target.mkdir()
    destination = tmp_path / "x-search-link"
    destination.symlink_to(real_target, target_is_directory=True)

    exit_code = INSTALL_MODULE.main(
        [
            "--bundle-root",
            str(REPO_ROOT),
            "--destination",
            str(destination),
            "--force",
        ]
    )

    assert exit_code == 0
    assert destination.is_dir()
    assert not destination.is_symlink()
    assert (destination / ".codex-plugin" / "plugin.json").exists()


def test_install_creates_default_x_api_compat_alias(tmp_path: Path) -> None:
    destination = tmp_path / "x-search"
    compat_alias = tmp_path / "x-api"

    exit_code = INSTALL_MODULE.main(
        [
            "--bundle-root",
            str(REPO_ROOT),
            "--destination",
            str(destination),
        ]
    )

    assert exit_code == 0
    assert compat_alias.is_symlink()
    assert compat_alias.resolve() == destination.resolve()
    assert (compat_alias / "scripts" / "x_api_mcp.py").exists()


def test_resolve_bearer_token_candidates_keeps_oauth_and_bearer_fallback() -> None:
    original_first_env_value = PLUGIN_MODULE._first_env_value
    original_resolve_candidate_refs = PLUGIN_MODULE._resolve_candidate_refs
    original_read_first_resolved_secret = PLUGIN_MODULE._read_first_resolved_secret
    original_issue_app_only_bearer_token = PLUGIN_MODULE._issue_app_only_bearer_token
    original_resolve_service_account_token_file = PLUGIN_MODULE._resolve_service_account_token_file

    def fake_resolve_candidate_refs(
        config: dict[str, object],
        *,
        env_single: str,
        env_many: str,
        config_key: str,
    ) -> list[str]:
        del config, env_single, env_many
        mapping = {
            "api_key_ref_candidates": ["op://vault/x-api-key"],
            "api_secret_ref_candidates": ["op://vault/x-api-secret"],
            "bearer_token_ref_candidates": ["op://vault/x-bearer"],
        }
        return mapping.get(config_key, [])

    try:
        PLUGIN_MODULE._first_env_value = lambda *names: None
        PLUGIN_MODULE._resolve_service_account_token_file = lambda config: None
        PLUGIN_MODULE._resolve_candidate_refs = fake_resolve_candidate_refs
        PLUGIN_MODULE._read_first_resolved_secret = (
            lambda refs, service_account_token_file, label: f"{label}:{refs[0]}"
        )
        PLUGIN_MODULE._issue_app_only_bearer_token = (
            lambda *, api_key, api_secret: f"minted:{api_key}|{api_secret}"
        )

        candidates = PLUGIN_MODULE._resolve_bearer_token_candidates({})
    finally:
        PLUGIN_MODULE._first_env_value = original_first_env_value
        PLUGIN_MODULE._resolve_candidate_refs = original_resolve_candidate_refs
        PLUGIN_MODULE._read_first_resolved_secret = original_read_first_resolved_secret
        PLUGIN_MODULE._issue_app_only_bearer_token = original_issue_app_only_bearer_token
        PLUGIN_MODULE._resolve_service_account_token_file = original_resolve_service_account_token_file

    assert candidates == [
        (
            "oauth:client-credentials",
            "minted:api_key_ref_candidates:op://vault/x-api-key|api_secret_ref_candidates:op://vault/x-api-secret",
        ),
        (
            "ref:bearer-token",
            "bearer_token_ref_candidates:op://vault/x-bearer",
        ),
    ]


def test_fetch_json_retries_with_next_credential_source_after_401() -> None:
    original_fetch_json_once = PLUGIN_MODULE._fetch_json_once
    calls: list[str] = []

    def fake_fetch_json_once(
        *,
        request_url: str,
        bearer_token: str,
        operation_name: str,
    ) -> tuple[dict[str, object], dict[str, str]]:
        del request_url, operation_name
        calls.append(bearer_token)
        if bearer_token == "bad-token":
            raise PLUGIN_MODULE._XRequestError(
                operation_name="X recent-search",
                status_code=401,
                detail="Unauthorized",
            )
        return ({"data": [{"id": "1"}]}, {"x-rate-limit-remaining": "42"})

    try:
        PLUGIN_MODULE._fetch_json_once = fake_fetch_json_once
        payload, headers = PLUGIN_MODULE._fetch_json(
            request_url="https://api.x.com/2/tweets/search/recent?query=openai",
            bearer_token_candidates=[
                ("env:bearer", "bad-token"),
                ("oauth:client-credentials", "good-token"),
            ],
            operation_name="X recent-search",
        )
    finally:
        PLUGIN_MODULE._fetch_json_once = original_fetch_json_once

    assert calls == ["bad-token", "good-token"]
    assert payload == {"data": [{"id": "1"}]}
    assert headers == {"x-rate-limit-remaining": "42"}
