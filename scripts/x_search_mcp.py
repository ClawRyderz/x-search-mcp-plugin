#!/usr/bin/env python3

"""Local-only MCP server for recent public X search."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from mcp_stdio import read_message as _read_message, write_message as _write_message  # noqa: E402

_RUNTIME_SERVER_NAME = "x-search-local"
_DOCTOR_SERVER_NAME = "x-search-doctor-local"
_SERVER_VERSION = "1.4.1"
_LATEST_PROTOCOL_VERSION = "2025-06-18"
_SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {"2024-11-05", "2025-03-26", _LATEST_PROTOCOL_VERSION}
)
_RECENT_SEARCH_ENDPOINT = "https://api.x.com/2/tweets/search/recent"
_POST_LOOKUP_ENDPOINT = "https://api.x.com/2/tweets"
_TOKEN_ENDPOINT = "https://api.x.com/oauth2/token"
_DEFAULT_TWEET_FIELDS = ("created_at", "public_metrics", "author_id", "lang")
_DEFAULT_USER_FIELDS = ("username", "name", "verified", "public_metrics")
_DEFAULT_EXPANSIONS = ("author_id",)
_LOOKUP_TWEET_FIELDS = (
    "author_id",
    "conversation_id",
    "created_at",
    "entities",
    "lang",
    "possibly_sensitive",
    "public_metrics",
    "referenced_tweets",
    "source",
    "text",
)
_X_URL_HOSTS = frozenset(
    {
        "x.com",
        "www.x.com",
        "twitter.com",
        "www.twitter.com",
        "mobile.twitter.com",
    }
)
_STATUS_PATH_PATTERN = re.compile(r"/status(?:es)?/(\d+)")
_CONFIG_ENV_VARS = (
    "X_SEARCH_CONFIG_FILE",
    "X_SEARCH_PLUGIN_CONFIG_FILE",
    "X_API_PLUGIN_CONFIG_FILE",
)
_MODE_ENV_VAR = "X_SEARCH_PLUGIN_MODE"
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "provider_refs.json"
_DEFAULT_DOCTOR_PROBE_QUERY = "from:XDevelopers"
_DEFAULT_RUNTIME_FAILURE_GUIDANCE = (
    "Use the X Search Doctor plugin's x_refresh_runtime_token tool to refresh the local bearer-token file."
)
_OP_AUTH_ENV_KEYS = frozenset(
    {
        "OP_CONNECT_HOST",
        "OP_CONNECT_TOKEN",
        "OP_SERVICE_ACCOUNT_TOKEN",
        "OP_SERVICE_ACCOUNT_TOKEN_FILE",
    }
)
_READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

_RUNTIME_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "name": "x_recent_search",
        "title": "Search recent X posts",
        "description": "Search recent public posts on X and return posts, permalinks, authors, and rate-limit metadata.",
        "annotations": _READ_ONLY_ANNOTATIONS,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "X recent-search query string."
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 10,
                    "maximum": 100,
                    "default": 10
                },
                "pages": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 1
                },
                "sort_order": {
                    "type": "string",
                    "enum": ["recency", "relevancy"],
                    "default": "recency"
                },
                "start_time": {
                    "type": "string",
                    "description": "Optional ISO-8601 UTC lower bound."
                },
                "end_time": {
                    "type": "string",
                    "description": "Optional ISO-8601 UTC upper bound."
                }
            },
            "required": ["query"],
            "additionalProperties": False
        }
    },
    {
        "name": "x_get_post",
        "title": "Get an X post",
        "description": "Fetch one public X post by post ID and return its text, author, permalink, and rate-limit metadata.",
        "annotations": _READ_ONLY_ANNOTATIONS,
        "inputSchema": {
            "type": "object",
            "properties": {
                "post_id": {
                    "type": "string",
                    "description": "Numeric X post ID."
                }
            },
            "required": ["post_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "x_get_post_by_url",
        "title": "Get an X post by URL",
        "description": "Fetch one public X post from an x.com or twitter.com status URL.",
        "annotations": _READ_ONLY_ANNOTATIONS,
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "An x.com or twitter.com post URL."
                }
            },
            "required": ["url"],
            "additionalProperties": False
        }
    },
)

_DOCTOR_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "name": "x_auth_doctor",
        "title": "Diagnose X Search authentication",
        "description": (
            "Diagnose local X auth without exposing secrets. Reports config path, candidate refs, "
            "1Password vault visibility, and bearer/client-credentials probe results."
        ),
        "annotations": _READ_ONLY_ANNOTATIONS,
        "inputSchema": {
            "type": "object",
            "properties": {
                "probe_query": {
                    "type": "string",
                    "description": (
                        "Optional recent-search query used for the live auth probe. "
                        "Defaults to a conservative query against the XDevelopers account."
                    ),
                    "default": _DEFAULT_DOCTOR_PROBE_QUERY,
                }
            },
            "additionalProperties": False
        }
    },
    {
        "name": "x_refresh_runtime_token",
        "title": "Refresh the X Search runtime token",
        "description": (
            "Refresh the local runtime bearer-token file from admin credential sources, "
            "verify it with a conservative probe query, and report the refreshed file path."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "probe_query": {
                    "type": "string",
                    "description": (
                        "Optional recent-search query used to verify the refreshed bearer token. "
                        "Defaults to a conservative query against the XDevelopers account."
                    ),
                    "default": _DEFAULT_DOCTOR_PROBE_QUERY,
                }
            },
            "additionalProperties": False
        }
    },
)


def _resolve_plugin_mode() -> str:
    mode = os.environ.get(_MODE_ENV_VAR, "runtime").strip().lower() or "runtime"
    if mode not in {"runtime", "doctor"}:
        raise ValueError(f"Unsupported {_MODE_ENV_VAR} value {mode!r}.")
    return mode


def _resolve_server_name() -> str:
    return _DOCTOR_SERVER_NAME if _resolve_plugin_mode() == "doctor" else _RUNTIME_SERVER_NAME


def _tool_schemas_for_mode() -> tuple[dict[str, Any], ...]:
    return _DOCTOR_TOOL_SCHEMAS if _resolve_plugin_mode() == "doctor" else _RUNTIME_TOOL_SCHEMAS


def _write_result(request_id: Any, result: dict[str, Any]) -> None:
    _write_message({"jsonrpc": "2.0", "id": request_id, "result": result})


def _write_error(request_id: Any, code: int, message: str) -> None:
    _write_message(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
    )


def _load_config() -> dict[str, Any]:
    config_path = _resolve_config_path()
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("X Search plugin config must contain a JSON object.")
    return payload


def _resolve_config_path() -> Path:
    config_env_value = _first_env_value(*_CONFIG_ENV_VARS)
    return Path(config_env_value or str(_DEFAULT_CONFIG_PATH)).expanduser()


def _load_credential_sources(config: dict[str, Any]) -> dict[str, Any]:
    sources = config.get("credential_sources")
    if sources is None:
        return {}
    if not isinstance(sources, dict):
        raise ValueError("credential_sources must be an object when present.")
    return sources


def _normalize_ref_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array when present.")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings.")
        stripped = item.strip()
        if stripped:
            normalized.append(stripped)
    return normalized


def _resolve_vault_candidates(config: dict[str, Any]) -> list[str]:
    env_value = _first_env_value("X_SEARCH_VAULT_CANDIDATES", "X_API_VAULT_CANDIDATES")
    if env_value:
        return [value.strip() for value in env_value.split(",") if value.strip()]
    sources = _load_credential_sources(config)
    return _normalize_ref_list(sources.get("vault_candidates"), field_name="vault_candidates")


def _expand_ref_templates(references: list[str], *, vault_candidates: list[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for reference in references:
        candidates = [reference]
        if "{vault}" in reference and vault_candidates:
            candidates = [reference.replace("{vault}", vault_name) for vault_name in vault_candidates]
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            expanded.append(candidate)
    return expanded


def _read_secret_from_1password(reference: str, *, service_account_token_file: str | None) -> str:
    if not reference.strip():
        raise ValueError("1Password reference must be non-empty.")
    env = _build_1password_env(service_account_token_file=service_account_token_file)
    completed = subprocess.run(
        ["op", "read", reference],
        capture_output=True,
        check=False,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise ValueError(stderr or f"1Password read failed for {reference}.")
    secret_value = completed.stdout.strip()
    if not secret_value:
        raise ValueError(f"1Password read returned an empty value for {reference}.")
    return secret_value


def _build_1password_env(*, service_account_token_file: str | None) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in _OP_AUTH_ENV_KEYS}
    token = _load_1password_service_account_token(service_account_token_file=service_account_token_file)
    if token:
        env["OP_SERVICE_ACCOUNT_TOKEN"] = token
    return env


def _load_1password_service_account_token(*, service_account_token_file: str | None) -> str:
    token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN", "").strip()
    resolved_token_file = _resolve_service_account_token_path(
        service_account_token_file=service_account_token_file
    )
    if not token and resolved_token_file is not None and resolved_token_file.exists():
        token = resolved_token_file.read_text(encoding="utf-8").strip()
    return token


def _resolve_service_account_token_path(*, service_account_token_file: str | None) -> Path | None:
    token_file = service_account_token_file or os.environ.get("OP_SERVICE_ACCOUNT_TOKEN_FILE", "").strip()
    return Path(token_file).expanduser() if token_file else None


def _read_secret_from_file(path_value: str, *, label: str) -> str:
    resolved_path = Path(path_value).expanduser()
    if not resolved_path.exists():
        raise ValueError(f"{label} file does not exist: {resolved_path}")
    if not resolved_path.is_file():
        raise ValueError(f"{label} path is not a file: {resolved_path}")
    secret_value = resolved_path.read_text(encoding="utf-8").strip()
    if not secret_value:
        raise ValueError(f"{label} file is empty: {resolved_path}")
    return secret_value


def _write_secret_to_file(path_value: str, *, label: str, secret_value: str) -> None:
    resolved_path = Path(path_value).expanduser()
    stripped_secret = secret_value.strip()
    if not stripped_secret:
        raise ValueError(f"{label} value must be non-empty.")
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(f"{stripped_secret}\n", encoding="utf-8")
    resolved_path.chmod(0o600)


def _list_accessible_1password_vaults(*, service_account_token_file: str | None) -> list[str]:
    completed = subprocess.run(
        ["op", "vault", "list", "--format", "json"],
        capture_output=True,
        check=False,
        text=True,
        env=_build_1password_env(service_account_token_file=service_account_token_file),
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise ValueError(stderr or "1Password vault listing failed.")
    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("1Password vault listing returned invalid JSON.") from exc
    if not isinstance(payload, list):
        raise ValueError("1Password vault listing returned an unexpected payload.")
    vault_names: list[str] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if name:
            vault_names.append(name)
    return vault_names


def _first_env_value(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def _resolve_service_account_token_file(config: dict[str, Any]) -> str | None:
    env_value = _first_env_value("X_SEARCH_OP_SERVICE_ACCOUNT_TOKEN_FILE", "X_API_OP_SERVICE_ACCOUNT_TOKEN_FILE")
    if env_value:
        return env_value
    configured_value = config.get("op_service_account_token_file")
    if configured_value is None:
        return None
    if not isinstance(configured_value, str):
        raise ValueError("op_service_account_token_file must be a string when present.")
    stripped = configured_value.strip()
    return stripped or None


def _resolve_bearer_token_file(config: dict[str, Any]) -> str | None:
    env_value = _first_env_value("X_SEARCH_BEARER_TOKEN_FILE", "X_API_BEARER_TOKEN_FILE")
    if env_value:
        return env_value
    configured_value = config.get("bearer_token_file")
    if configured_value is None:
        return None
    if not isinstance(configured_value, str):
        raise ValueError("bearer_token_file must be a string when present.")
    stripped = configured_value.strip()
    return stripped or None


def _resolve_candidate_refs(
    config: dict[str, Any],
    *,
    env_single: str,
    env_many: str,
    config_key: str,
) -> list[str]:
    single = _first_env_value(env_single)
    if single:
        references = [single]
        return _expand_ref_templates(references, vault_candidates=_resolve_vault_candidates(config))
    many = _first_env_value(env_many)
    if many:
        references = [value.strip() for value in many.split(",") if value.strip()]
        return _expand_ref_templates(references, vault_candidates=_resolve_vault_candidates(config))
    sources = _load_credential_sources(config)
    references = _normalize_ref_list(sources.get(config_key), field_name=config_key)
    return _expand_ref_templates(references, vault_candidates=_resolve_vault_candidates(config))


def _resolve_bearer_token(config: dict[str, Any]) -> str:
    return _resolve_bearer_token_candidates(config)[0][1]


def _resolve_bearer_token_candidates(
    config: dict[str, Any],
    *,
    include_runtime_file: bool = True,
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    errors: list[str] = []
    seen_tokens: set[str] = set()

    def remember(label: str, token: str) -> None:
        stripped = token.strip()
        if not stripped or stripped in seen_tokens:
            return
        seen_tokens.add(stripped)
        candidates.append((label, stripped))

    direct_bearer = _first_env_value("X_SEARCH_BEARER_TOKEN", "X_API_BEARER_TOKEN")
    if direct_bearer:
        remember("env:bearer", direct_bearer)

    bearer_token_file = _resolve_bearer_token_file(config)
    if include_runtime_file and bearer_token_file:
        try:
            remember(
                "file:bearer-token",
                _read_secret_from_file(bearer_token_file, label="bearer_token_file"),
            )
        except ValueError as exc:
            errors.append(str(exc))

    service_account_token_file = _resolve_service_account_token_file(config)
    api_key_refs = _resolve_candidate_refs(
        config,
        env_single="X_API_KEY_REF",
        env_many="X_API_KEY_REFS",
        config_key="api_key_ref_candidates",
    )
    api_secret_refs = _resolve_candidate_refs(
        config,
        env_single="X_API_SECRET_REF",
        env_many="X_API_SECRET_REFS",
        config_key="api_secret_ref_candidates",
    )
    if api_key_refs or api_secret_refs:
        if not api_key_refs or not api_secret_refs:
            errors.append(
                "Both api_key_ref_candidates and api_secret_ref_candidates must resolve together."
            )
        else:
            try:
                api_key = _read_first_resolved_secret(
                    api_key_refs,
                    service_account_token_file=service_account_token_file,
                    label="api_key_ref_candidates",
                )
                api_secret = _read_first_resolved_secret(
                    api_secret_refs,
                    service_account_token_file=service_account_token_file,
                    label="api_secret_ref_candidates",
                )
                remember(
                    "oauth:client-credentials",
                    _issue_app_only_bearer_token(api_key=api_key, api_secret=api_secret),
                )
            except ValueError as exc:
                errors.append(str(exc))

    bearer_refs = _resolve_candidate_refs(
        config,
        env_single="X_API_BEARER_TOKEN_REF",
        env_many="X_API_BEARER_TOKEN_REFS",
        config_key="bearer_token_ref_candidates",
    )
    if bearer_refs:
        try:
            remember(
                "ref:bearer-token",
                _read_first_resolved_secret(
                    bearer_refs,
                    service_account_token_file=service_account_token_file,
                    label="bearer_token_ref_candidates",
                ),
            )
        except ValueError as exc:
            errors.append(str(exc))

    if candidates:
        return candidates
    if errors:
        raise ValueError(errors[-1])
    raise ValueError(
        "No X credential source is configured. Set local ref candidates in the plugin config or supply env overrides."
    )


def _resolve_runtime_bearer_token_candidates(config: dict[str, Any]) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    errors: list[str] = []
    direct_bearer = _first_env_value("X_SEARCH_BEARER_TOKEN", "X_API_BEARER_TOKEN")
    if direct_bearer:
        candidates.append(("env:bearer", direct_bearer.strip()))

    bearer_token_file = _resolve_bearer_token_file(config)
    if bearer_token_file:
        try:
            candidates.append(
                (
                    "file:bearer-token",
                    _read_secret_from_file(bearer_token_file, label="bearer_token_file"),
                )
            )
        except ValueError as exc:
            errors.append(str(exc))

    if candidates:
        return candidates

    try:
        return _resolve_bearer_token_candidates(config, include_runtime_file=False)
    except ValueError as exc:
        errors.append(str(exc))

    message = errors[-1] if errors else "The runtime X plugin could not find a usable credential."
    raise ValueError(f"{message} {_DEFAULT_RUNTIME_FAILURE_GUIDANCE}") from None


def _resolve_admin_bearer_token_candidates(config: dict[str, Any]) -> list[tuple[str, str]]:
    candidates = [
        (label, token)
        for label, token in _resolve_bearer_token_candidates(config, include_runtime_file=False)
        if not label.startswith("file:")
    ]
    if candidates:
        return candidates
    raise ValueError(
        "The X Search Doctor plugin could not find any admin credential source to refresh the runtime token."
    )


def _read_first_resolved_secret(
    references: list[str],
    *,
    service_account_token_file: str | None,
    label: str,
) -> str:
    return _read_first_resolved_secret_candidate(
        references,
        service_account_token_file=service_account_token_file,
        label=label,
    )[1]


def _read_first_resolved_secret_candidate(
    references: list[str],
    *,
    service_account_token_file: str | None,
    label: str,
) -> tuple[str, str]:
    last_error: str | None = None
    for reference in references:
        try:
            return (
                reference,
                _read_secret_from_1password(
                    reference,
                    service_account_token_file=service_account_token_file,
                ),
            )
        except ValueError as exc:
            last_error = str(exc)
    raise ValueError(last_error or f"No usable references were configured for {label}.")


def _redact_detail(detail: str) -> str:
    return detail.replace("\r", " ").replace("\n", " ").strip()


def _infer_auth_failure_hint(*, kind: str, status_code: int | None, detail: str) -> str | None:
    normalized_detail = detail.lower()
    if kind in {"env_bearer_token", "bearer_token_file", "bearer_token_ref"} and status_code == 401:
        return "Bearer token was rejected. It is usually stale, regenerated, or tied to a different X app."
    if kind == "oauth_client_credentials":
        if status_code == 403 and "authenticity_token_error" in normalized_detail:
            return (
                "Consumer key/secret pair was rejected. This usually means the stored X API key "
                "or secret is stale, mismatched, or was regenerated in the developer portal."
            )
        if status_code in {401, 403}:
            return "X rejected the app-only OAuth request. Recheck the stored consumer key/secret pair."
    return None


def _probe_recent_search(
    *,
    bearer_token: str,
    probe_query: str,
    operation_name: str,
) -> dict[str, Any]:
    request_url = _build_search_url(
        {
            "query": probe_query,
            "max_results": 10,
            "pages": 1,
            "sort_order": "recency",
        }
    )
    payload, headers = _fetch_json_once(
        request_url=request_url,
        bearer_token=bearer_token,
        operation_name=operation_name,
    )
    meta = payload.get("meta", {})
    result_count = None
    if isinstance(meta, dict):
        result_count = _coerce_int(meta.get("result_count"))
    return {
        "request_url": request_url,
        "result_count": result_count,
        "rate_limit": {
            "limit": _coerce_int(headers.get("x-rate-limit-limit")),
            "remaining": _coerce_int(headers.get("x-rate-limit-remaining")),
            "reset_unix_seconds": _coerce_int(headers.get("x-rate-limit-reset")),
        },
    }


def _diagnose_auth(arguments: dict[str, Any]) -> dict[str, Any]:
    config = _load_config()
    service_account_token_file = _resolve_service_account_token_file(config)
    bearer_token_file = _resolve_bearer_token_file(config)
    resolved_config_path = _resolve_config_path()
    service_account_token_path = _resolve_service_account_token_path(
        service_account_token_file=service_account_token_file
    )
    bearer_token_file_path = Path(bearer_token_file).expanduser() if bearer_token_file else None
    probe_query = str(arguments.get("probe_query", _DEFAULT_DOCTOR_PROBE_QUERY)).strip()
    if not probe_query:
        probe_query = _DEFAULT_DOCTOR_PROBE_QUERY

    bearer_refs = _resolve_candidate_refs(
        config,
        env_single="X_API_BEARER_TOKEN_REF",
        env_many="X_API_BEARER_TOKEN_REFS",
        config_key="bearer_token_ref_candidates",
    )
    api_key_refs = _resolve_candidate_refs(
        config,
        env_single="X_API_KEY_REF",
        env_many="X_API_KEY_REFS",
        config_key="api_key_ref_candidates",
    )
    api_secret_refs = _resolve_candidate_refs(
        config,
        env_single="X_API_SECRET_REF",
        env_many="X_API_SECRET_REFS",
        config_key="api_secret_ref_candidates",
    )

    report: dict[str, Any] = {
        "healthy": False,
        "config_file": str(resolved_config_path),
        "probe_query": probe_query,
        "service_account_token_file": {
            "path": str(service_account_token_path) if service_account_token_path is not None else None,
            "exists": service_account_token_path.exists() if service_account_token_path is not None else False,
        },
        "credential_sources": {
            "vault_candidates": _resolve_vault_candidates(config),
            "bearer_token_ref_candidates": bearer_refs,
            "api_key_ref_candidates": api_key_refs,
            "api_secret_ref_candidates": api_secret_refs,
            "bearer_token_file": (
                {
                    "path": str(bearer_token_file_path),
                    "exists": bearer_token_file_path.exists(),
                }
                if bearer_token_file_path is not None
                else None
            ),
            "direct_env_sources": {
                "bearer_token": bool(_first_env_value("X_SEARCH_BEARER_TOKEN", "X_API_BEARER_TOKEN")),
                "api_key_ref": bool(_first_env_value("X_API_KEY_REF", "X_API_KEY_REFS")),
                "api_secret_ref": bool(_first_env_value("X_API_SECRET_REF", "X_API_SECRET_REFS")),
            },
        },
        "checks": [],
    }

    try:
        report["available_1password_vaults"] = _list_accessible_1password_vaults(
            service_account_token_file=service_account_token_file
        )
    except ValueError as exc:
        report["available_1password_vaults_error"] = _redact_detail(str(exc))

    direct_bearer = _first_env_value("X_SEARCH_BEARER_TOKEN", "X_API_BEARER_TOKEN")
    if direct_bearer:
        check: dict[str, Any] = {
            "kind": "env_bearer_token",
            "label": "env:bearer",
        }
        try:
            check["probe"] = _probe_recent_search(
                bearer_token=direct_bearer,
                probe_query=probe_query,
                operation_name="X auth doctor env bearer probe",
            )
            check["status"] = "ok"
            report["healthy"] = True
        except _XRequestError as exc:
            check["status"] = "error"
            check["status_code"] = exc.status_code
            check["detail"] = _redact_detail(exc.detail)
            likely_cause = _infer_auth_failure_hint(
                kind=str(check["kind"]),
                status_code=exc.status_code,
                detail=check["detail"],
            )
            if likely_cause is not None:
                check["likely_cause"] = likely_cause
        report["checks"].append(check)

    if bearer_token_file_path is not None:
        check = {
            "kind": "bearer_token_file",
            "label": str(bearer_token_file_path),
        }
        try:
            token = _read_secret_from_file(
                str(bearer_token_file_path),
                label="bearer_token_file",
            )
            check["probe"] = _probe_recent_search(
                bearer_token=token,
                probe_query=probe_query,
                operation_name=f"X auth doctor bearer file probe ({bearer_token_file_path})",
            )
            check["status"] = "ok"
            report["healthy"] = True
        except _XRequestError as exc:
            check["status"] = "error"
            check["status_code"] = exc.status_code
            check["detail"] = _redact_detail(exc.detail)
            likely_cause = _infer_auth_failure_hint(
                kind=str(check["kind"]),
                status_code=exc.status_code,
                detail=check["detail"],
            )
            if likely_cause is not None:
                check["likely_cause"] = likely_cause
        except ValueError as exc:
            check["status"] = "error"
            check["detail"] = _redact_detail(str(exc))
        report["checks"].append(check)

    for reference in bearer_refs:
        check = {
            "kind": "bearer_token_ref",
            "label": reference,
        }
        try:
            token = _read_secret_from_1password(
                reference,
                service_account_token_file=service_account_token_file,
            )
            check["probe"] = _probe_recent_search(
                bearer_token=token,
                probe_query=probe_query,
                operation_name=f"X auth doctor bearer ref probe ({reference})",
            )
            check["status"] = "ok"
            report["healthy"] = True
        except _XRequestError as exc:
            check["status"] = "error"
            check["status_code"] = exc.status_code
            check["detail"] = _redact_detail(exc.detail)
            likely_cause = _infer_auth_failure_hint(
                kind=str(check["kind"]),
                status_code=exc.status_code,
                detail=check["detail"],
            )
            if likely_cause is not None:
                check["likely_cause"] = likely_cause
        except ValueError as exc:
            check["status"] = "error"
            check["detail"] = _redact_detail(str(exc))
        report["checks"].append(check)

    oauth_check: dict[str, Any] = {
        "kind": "oauth_client_credentials",
    }
    if api_key_refs or api_secret_refs:
        try:
            api_key_reference, api_key = _read_first_resolved_secret_candidate(
                api_key_refs,
                service_account_token_file=service_account_token_file,
                label="api_key_ref_candidates",
            )
            api_secret_reference, api_secret = _read_first_resolved_secret_candidate(
                api_secret_refs,
                service_account_token_file=service_account_token_file,
                label="api_secret_ref_candidates",
            )
            oauth_check["api_key_ref"] = api_key_reference
            oauth_check["api_secret_ref"] = api_secret_reference
            bearer_token = _issue_app_only_bearer_token(api_key=api_key, api_secret=api_secret)
            oauth_check["probe"] = _probe_recent_search(
                bearer_token=bearer_token,
                probe_query=probe_query,
                operation_name="X auth doctor oauth probe",
            )
            oauth_check["status"] = "ok"
            report["healthy"] = True
        except (_XRequestError, ValueError) as exc:
            oauth_check["status"] = "error"
            if isinstance(exc, _XRequestError):
                oauth_check["status_code"] = exc.status_code
                oauth_check["detail"] = _redact_detail(exc.detail)
                likely_cause = _infer_auth_failure_hint(
                    kind=str(oauth_check["kind"]),
                    status_code=exc.status_code,
                    detail=oauth_check["detail"],
                )
                if likely_cause is not None:
                    oauth_check["likely_cause"] = likely_cause
            else:
                oauth_check["detail"] = _redact_detail(str(exc))
    else:
        oauth_check["status"] = "skipped"
        oauth_check["detail"] = "No API key/secret ref candidates were configured."
    report["checks"].append(oauth_check)
    return report


def _issue_app_only_bearer_token(*, api_key: str, api_secret: str, timeout_seconds: float = 30.0) -> str:
    if not api_key.strip() or not api_secret.strip():
        raise ValueError("X app key and secret must both be non-empty.")
    basic_auth = base64.b64encode(f"{api_key}:{api_secret}".encode("utf-8")).decode("ascii")
    request = Request(
        _TOKEN_ENDPOINT,
        data=urlencode({"grant_type": "client_credentials"}).encode("utf-8"),
        headers={
            "Authorization": f"Basic {basic_auth}",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": "x-search-mcp-plugin/1.4.1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"X OAuth bearer-token mint failed with HTTP {exc.code}: {body or exc.reason}"
        ) from exc
    except URLError as exc:
        raise ValueError(f"X OAuth bearer-token mint failed: {exc.reason}") from exc
    token_type = str(payload.get("token_type", "")).strip().lower()
    access_token = str(payload.get("access_token", "")).strip()
    if token_type != "bearer" or not access_token:
        raise ValueError("X OAuth token response did not contain a usable bearer token.")
    return access_token


def _build_search_url(arguments: dict[str, Any], *, next_token: str | None = None) -> str:
    query = str(arguments.get("query", "")).strip()
    if not query:
        raise ValueError("query is required.")
    max_results = int(arguments.get("max_results", 10))
    pages = int(arguments.get("pages", 1))
    sort_order = str(arguments.get("sort_order", "recency")).strip() or "recency"
    if not 10 <= max_results <= 100:
        raise ValueError("max_results must be between 10 and 100.")
    if not 1 <= pages <= 5:
        raise ValueError("pages must be between 1 and 5.")
    if sort_order not in {"recency", "relevancy"}:
        raise ValueError("sort_order must be either 'recency' or 'relevancy'.")
    params = {
        "query": query,
        "max_results": str(max_results),
        "sort_order": sort_order,
        "expansions": ",".join(_DEFAULT_EXPANSIONS),
        "tweet.fields": ",".join(_DEFAULT_TWEET_FIELDS),
        "user.fields": ",".join(_DEFAULT_USER_FIELDS),
    }
    for field_name in ("start_time", "end_time"):
        value = arguments.get(field_name)
        if value is None:
            continue
        stripped = str(value).strip()
        if stripped:
            params[field_name] = stripped
    if next_token:
        params["next_token"] = next_token
    return f"{_RECENT_SEARCH_ENDPOINT}?{urlencode(params)}"


def _build_lookup_url(*, post_id: str) -> str:
    stripped_post_id = str(post_id).strip()
    if not stripped_post_id.isdigit():
        raise ValueError("post_id must be a numeric X post ID.")
    params = {
        "ids": stripped_post_id,
        "expansions": ",".join(_DEFAULT_EXPANSIONS),
        "tweet.fields": ",".join(_LOOKUP_TWEET_FIELDS),
        "user.fields": ",".join(_DEFAULT_USER_FIELDS),
    }
    return f"{_POST_LOOKUP_ENDPOINT}?{urlencode(params)}"


class _XRequestError(ValueError):
    def __init__(self, *, operation_name: str, detail: str, status_code: int | None = None) -> None:
        self.operation_name = operation_name
        self.detail = detail
        self.status_code = status_code
        if status_code is None:
            message = f"{operation_name} failed: {detail}"
        else:
            message = f"{operation_name} failed with HTTP {status_code}: {detail}"
        super().__init__(message)


def _fetch_json_once(
    *,
    request_url: str,
    bearer_token: str,
    operation_name: str,
) -> tuple[dict[str, Any], Any]:
    request = Request(
        request_url,
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "User-Agent": "x-search-mcp-plugin/1.4.1",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=30.0) as response:
            return json.loads(response.read().decode("utf-8")), response.headers
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        raise _XRequestError(
            operation_name=operation_name,
            status_code=exc.code,
            detail=body or exc.reason,
        ) from exc
    except URLError as exc:
        raise _XRequestError(operation_name=operation_name, detail=str(exc.reason)) from exc


def _fetch_json(
    *,
    request_url: str,
    bearer_token_candidates: list[tuple[str, str]],
    operation_name: str,
    bearer_token_file: str | None = None,
) -> tuple[dict[str, Any], Any]:
    auth_errors: list[str] = []
    last_auth_error: _XRequestError | None = None
    for label, bearer_token in bearer_token_candidates:
        try:
            payload, headers = _fetch_json_once(
                request_url=request_url,
                bearer_token=bearer_token,
                operation_name=operation_name,
            )
            if (
                bearer_token_file
                and label in {"oauth:client-credentials", "ref:bearer-token"}
            ):
                try:
                    _write_secret_to_file(
                        bearer_token_file,
                        label="bearer_token_file",
                        secret_value=bearer_token,
                    )
                except ValueError:
                    pass
            return (payload, headers)
        except _XRequestError as exc:
            if exc.status_code not in {401, 403}:
                raise
            auth_errors.append(label)
            last_auth_error = exc
    if last_auth_error is not None:
        attempted_sources = ", ".join(auth_errors)
        raise ValueError(
            f"{last_auth_error.operation_name} failed with HTTP {last_auth_error.status_code} "
            f"after trying {len(auth_errors)} credential source(s): {attempted_sources}."
        )
    raise ValueError(f"{operation_name} failed before any X credential source could be used.")


def _fetch_runtime_json(
    *,
    request_url: str,
    bearer_token_candidates: list[tuple[str, str]],
    operation_name: str,
) -> tuple[dict[str, Any], Any]:
    try:
        return _fetch_json(
            request_url=request_url,
            bearer_token_candidates=bearer_token_candidates,
            operation_name=operation_name,
        )
    except ValueError as exc:
        raise ValueError(f"{exc} {_DEFAULT_RUNTIME_FAILURE_GUIDANCE}") from exc


def _build_users_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    users_by_id: dict[str, dict[str, Any]] = {}
    includes = payload.get("includes", {})
    if not isinstance(includes, dict):
        return users_by_id
    users = includes.get("users", [])
    if not isinstance(users, list):
        return users_by_id
    for user in users:
        if not isinstance(user, dict):
            continue
        user_id = str(user.get("id", "")).strip()
        if user_id:
            users_by_id[user_id] = user
    return users_by_id


def _normalize_post(raw_post: dict[str, Any], users_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    post_id = str(raw_post.get("id", "")).strip()
    text = str(raw_post.get("text", "")).strip()
    if not post_id or not text:
        return None
    author_id = str(raw_post.get("author_id", "")).strip()
    author_payload = users_by_id.get(author_id, {})
    username = author_payload.get("username")
    permalink = None
    if isinstance(username, str) and username.strip():
        permalink = f"https://x.com/{username.strip()}/status/{post_id}"
    return {
        "post_id": post_id,
        "text": text,
        "created_at": raw_post.get("created_at"),
        "conversation_id": raw_post.get("conversation_id"),
        "lang": raw_post.get("lang"),
        "source": raw_post.get("source"),
        "possibly_sensitive": raw_post.get("possibly_sensitive"),
        "public_metrics": raw_post.get("public_metrics", {}),
        "referenced_tweets": raw_post.get("referenced_tweets", []),
        "entities": raw_post.get("entities", {}),
        "permalink": permalink,
        "author": {
            "author_id": author_id or None,
            "username": username,
            "name": author_payload.get("name"),
            "verified": author_payload.get("verified"),
            "public_metrics": author_payload.get("public_metrics", {}),
        },
    }


def _search_recent_posts(arguments: dict[str, Any]) -> dict[str, Any]:
    config = _load_config()
    bearer_token_candidates = _resolve_runtime_bearer_token_candidates(config)
    pages_to_fetch = int(arguments.get("pages", 1))
    next_token: str | None = None
    pages: list[dict[str, Any]] = []
    aggregated_posts: list[dict[str, Any]] = []

    for _ in range(pages_to_fetch):
        request_url = _build_search_url(arguments, next_token=next_token)
        payload, headers = _fetch_runtime_json(
            request_url=request_url,
            bearer_token_candidates=bearer_token_candidates,
            operation_name="X recent-search",
        )
        users_by_id = _build_users_by_id(payload)

        page_posts: list[dict[str, Any]] = []
        data = payload.get("data", [])
        if isinstance(data, list):
            for raw_post in data:
                if not isinstance(raw_post, dict):
                    continue
                normalized_post = _normalize_post(raw_post, users_by_id)
                if normalized_post is not None:
                    page_posts.append(normalized_post)
        meta = payload.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        next_token = str(meta.get("next_token", "")).strip() or None
        page = {
            "request_url": request_url,
            "result_count": int(meta.get("result_count", len(page_posts) or 0)),
            "newest_id": meta.get("newest_id"),
            "oldest_id": meta.get("oldest_id"),
            "next_token": next_token,
            "rate_limit": {
                "limit": _coerce_int(headers.get("x-rate-limit-limit")),
                "remaining": _coerce_int(headers.get("x-rate-limit-remaining")),
                "reset_unix_seconds": _coerce_int(headers.get("x-rate-limit-reset")),
            },
            "posts": page_posts,
        }
        pages.append(page)
        aggregated_posts.extend(page_posts)
        if next_token is None:
            break

    return {
        "query": str(arguments["query"]).strip(),
        "pages_returned": len(pages),
        "total_result_count": sum(page["result_count"] for page in pages),
        "pages": pages,
        "posts": aggregated_posts,
    }


def _normalize_x_status_url(url: str) -> str:
    stripped_url = str(url).strip()
    if not stripped_url:
        raise ValueError("url is required.")
    if "://" not in stripped_url and any(
        stripped_url.startswith(prefix) for prefix in ("x.com/", "www.x.com/", "twitter.com/", "www.twitter.com/", "mobile.twitter.com/")
    ):
        return f"https://{stripped_url}"
    return stripped_url


def _extract_post_id_from_url(url: str) -> str:
    normalized_url = _normalize_x_status_url(url)
    parsed = urlparse(normalized_url)
    hostname = (parsed.hostname or "").lower()
    if hostname not in _X_URL_HOSTS:
        raise ValueError("url must be an x.com or twitter.com status URL.")
    match = _STATUS_PATH_PATTERN.search(parsed.path)
    if match is None:
        raise ValueError("Could not extract a post ID from the X URL.")
    return match.group(1)


def _get_post(arguments: dict[str, Any]) -> dict[str, Any]:
    config = _load_config()
    bearer_token_candidates = _resolve_runtime_bearer_token_candidates(config)
    request_url = _build_lookup_url(post_id=str(arguments.get("post_id", "")))
    payload, headers = _fetch_runtime_json(
        request_url=request_url,
        bearer_token_candidates=bearer_token_candidates,
        operation_name="X post lookup",
    )
    users_by_id = _build_users_by_id(payload)
    data = payload.get("data", [])
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise ValueError("X post lookup returned no post data.")
    first_post = data[0]
    if not isinstance(first_post, dict):
        raise ValueError("X post lookup returned an unexpected payload shape.")
    normalized_post = _normalize_post(first_post, users_by_id)
    if normalized_post is None:
        raise ValueError("X post lookup did not contain a usable post.")
    return {
        "request_url": request_url,
        "rate_limit": {
            "limit": _coerce_int(headers.get("x-rate-limit-limit")),
            "remaining": _coerce_int(headers.get("x-rate-limit-remaining")),
            "reset_unix_seconds": _coerce_int(headers.get("x-rate-limit-reset")),
        },
        "post": normalized_post,
    }


def _get_post_by_url(arguments: dict[str, Any]) -> dict[str, Any]:
    input_url = str(arguments.get("url", "")).strip()
    post_id = _extract_post_id_from_url(input_url)
    payload = _get_post({"post_id": post_id})
    payload["input_url"] = _normalize_x_status_url(input_url)
    payload["resolved_post_id"] = post_id
    return payload


def _refresh_runtime_token(arguments: dict[str, Any]) -> dict[str, Any]:
    config = _load_config()
    bearer_token_file = _resolve_bearer_token_file(config)
    if not bearer_token_file:
        raise ValueError(
            "The X Search Doctor plugin needs bearer_token_file configured so it knows where to write the runtime token."
        )
    probe_query = str(arguments.get("probe_query", _DEFAULT_DOCTOR_PROBE_QUERY)).strip()
    if not probe_query:
        probe_query = _DEFAULT_DOCTOR_PROBE_QUERY

    bearer_token_candidates = _resolve_admin_bearer_token_candidates(config)
    auth_errors: list[str] = []
    last_auth_error: _XRequestError | None = None
    for label, bearer_token in bearer_token_candidates:
        try:
            probe = _probe_recent_search(
                bearer_token=bearer_token,
                probe_query=probe_query,
                operation_name=f"X runtime-token refresh probe ({label})",
            )
            _write_secret_to_file(
                bearer_token_file,
                label="bearer_token_file",
                secret_value=bearer_token,
            )
            resolved_path = Path(bearer_token_file).expanduser()
            return {
                "refreshed": True,
                "probe_query": probe_query,
                "source": label,
                "bearer_token_file": {
                    "path": str(resolved_path),
                    "exists": resolved_path.exists(),
                },
                "probe": probe,
            }
        except _XRequestError as exc:
            if exc.status_code not in {401, 403}:
                raise
            auth_errors.append(label)
            last_auth_error = exc

    if last_auth_error is not None:
        attempted_sources = ", ".join(auth_errors)
        raise ValueError(
            f"X runtime-token refresh failed with HTTP {last_auth_error.status_code} "
            f"after trying {len(auth_errors)} admin credential source(s): {attempted_sources}."
        )
    raise ValueError("X runtime-token refresh failed before any admin credential source could be used.")


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def _handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    plugin_mode = _resolve_plugin_mode()
    method = message.get("method")
    if not isinstance(method, str):
        raise ValueError("Missing JSON-RPC method.")
    params = message.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("JSON-RPC params must be an object.")

    if method == "initialize":
        requested_version = str(params.get("protocolVersion") or "")
        protocol_version = (
            requested_version
            if requested_version in _SUPPORTED_PROTOCOL_VERSIONS
            else _LATEST_PROTOCOL_VERSION
        )
        return {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": _resolve_server_name(), "version": _SERVER_VERSION},
            "instructions": (
                "Read-only X research tools are available in runtime mode. "
                "Authentication diagnosis and local token refresh are available in doctor mode."
            ),
        }
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": list(_tool_schemas_for_mode())}
    if method == "tools/call":
        name = str(params.get("name", "")).strip()
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object.")
        try:
            if plugin_mode == "runtime" and name == "x_recent_search":
                payload = _search_recent_posts(arguments)
            elif plugin_mode == "runtime" and name == "x_get_post":
                payload = _get_post(arguments)
            elif plugin_mode == "runtime" and name == "x_get_post_by_url":
                payload = _get_post_by_url(arguments)
            elif plugin_mode == "doctor" and name == "x_auth_doctor":
                payload = _diagnose_auth(arguments)
            elif plugin_mode == "doctor" and name == "x_refresh_runtime_token":
                payload = _refresh_runtime_token(arguments)
            else:
                raise ValueError(f"Unknown tool {name!r}.")
        except Exception as exc:  # noqa: BLE001
            return {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            }
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, indent=2, sort_keys=True),
                }
            ],
            "structuredContent": payload,
            "isError": False,
        }
    raise ValueError(f"Unsupported method {method!r}.")


def main() -> int:
    while True:
        try:
            message = _read_message()
            if message is None:
                return 0
            request_id = message.get("id")
            result = _handle_request(message)
            if request_id is not None and result is not None:
                _write_result(request_id, result)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:  # noqa: BLE001
            request_id = None
            if "message" in locals() and isinstance(message, dict):
                request_id = message.get("id")
            if request_id is not None:
                _write_error(request_id, -32000, str(exc))
            else:
                return 1


if __name__ == "__main__":
    raise SystemExit(main())
