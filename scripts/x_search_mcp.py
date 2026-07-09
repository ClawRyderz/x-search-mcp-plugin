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


_SERVER_NAME = "x-search-local"
_SERVER_VERSION = "1.0.0"
_DEFAULT_PROTOCOL_VERSION = "2024-11-05"
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
_CONFIG_ENV_VAR = "X_SEARCH_PLUGIN_CONFIG_FILE"
_LEGACY_CONFIG_ENV_VAR = "X_API_PLUGIN_CONFIG_FILE"
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "provider_refs.json"
_OP_AUTH_ENV_KEYS = frozenset(
    {
        "OP_CONNECT_HOST",
        "OP_CONNECT_TOKEN",
        "OP_SERVICE_ACCOUNT_TOKEN",
        "OP_SERVICE_ACCOUNT_TOKEN_FILE",
    }
)
_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "name": "x_recent_search",
        "description": "Search recent public posts on X and return posts, permalinks, authors, and rate-limit metadata.",
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
        "description": "Fetch one public X post by post ID and return its text, author, permalink, and rate-limit metadata.",
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
        "description": "Fetch one public X post from an x.com or twitter.com status URL.",
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


def _read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\n", b"\r\n"):
            break
        decoded = line.decode("utf-8").strip()
        if ":" not in decoded:
            continue
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    content_length = headers.get("content-length")
    if content_length is None:
        raise ValueError("Missing Content-Length header.")
    try:
        expected_length = int(content_length)
    except ValueError as exc:
        raise ValueError("Invalid Content-Length header.") from exc
    payload = sys.stdin.buffer.read(expected_length)
    if len(payload) != expected_length:
        raise ValueError("Incomplete JSON-RPC payload.")
    return json.loads(payload.decode("utf-8"))


def _write_message(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


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
    config_env_value = _first_env_value(_CONFIG_ENV_VAR, _LEGACY_CONFIG_ENV_VAR)
    config_path = Path(config_env_value or str(_DEFAULT_CONFIG_PATH)).expanduser()
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("X Search plugin config must contain a JSON object.")
    return payload


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


def _read_secret_from_1password(reference: str, *, service_account_token_file: str | None) -> str:
    if not reference.strip():
        raise ValueError("1Password reference must be non-empty.")
    env = {key: value for key, value in os.environ.items() if key not in _OP_AUTH_ENV_KEYS}
    token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN", "").strip()
    token_file = service_account_token_file or os.environ.get("OP_SERVICE_ACCOUNT_TOKEN_FILE", "").strip()
    resolved_token_file = Path(token_file).expanduser() if token_file else None
    if not token and resolved_token_file is not None and resolved_token_file.exists():
        token = resolved_token_file.read_text(encoding="utf-8").strip()
    if token:
        env["OP_SERVICE_ACCOUNT_TOKEN"] = token
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


def _resolve_candidate_refs(
    config: dict[str, Any],
    *,
    env_single: str,
    env_many: str,
    config_key: str,
) -> list[str]:
    single = _first_env_value(env_single)
    if single:
        return [single]
    many = _first_env_value(env_many)
    if many:
        return [value.strip() for value in many.split(",") if value.strip()]
    sources = config.get("credential_sources")
    if sources is None:
        return []
    if not isinstance(sources, dict):
        raise ValueError("credential_sources must be an object when present.")
    return _normalize_ref_list(sources.get(config_key), field_name=config_key)


def _resolve_bearer_token(config: dict[str, Any]) -> str:
    return _resolve_bearer_token_candidates(config)[0][1]


def _resolve_bearer_token_candidates(config: dict[str, Any]) -> list[tuple[str, str]]:
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


def _read_first_resolved_secret(
    references: list[str],
    *,
    service_account_token_file: str | None,
    label: str,
) -> str:
    last_error: str | None = None
    for reference in references:
        try:
            return _read_secret_from_1password(
                reference,
                service_account_token_file=service_account_token_file,
            )
        except ValueError as exc:
            last_error = str(exc)
    raise ValueError(last_error or f"No usable references were configured for {label}.")


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
            "User-Agent": "codex-x-search-plugin/1.0",
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
            "User-Agent": "codex-x-search-plugin/1.0",
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
) -> tuple[dict[str, Any], Any]:
    auth_errors: list[str] = []
    last_auth_error: _XRequestError | None = None
    for label, bearer_token in bearer_token_candidates:
        try:
            return _fetch_json_once(
                request_url=request_url,
                bearer_token=bearer_token,
                operation_name=operation_name,
            )
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
    bearer_token_candidates = _resolve_bearer_token_candidates(config)
    pages_to_fetch = int(arguments.get("pages", 1))
    next_token: str | None = None
    pages: list[dict[str, Any]] = []
    aggregated_posts: list[dict[str, Any]] = []

    for _ in range(pages_to_fetch):
        request_url = _build_search_url(arguments, next_token=next_token)
        payload, headers = _fetch_json(
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
    bearer_token_candidates = _resolve_bearer_token_candidates(config)
    request_url = _build_lookup_url(post_id=str(arguments.get("post_id", "")))
    payload, headers = _fetch_json(
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
    method = message.get("method")
    if not isinstance(method, str):
        raise ValueError("Missing JSON-RPC method.")
    params = message.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("JSON-RPC params must be an object.")

    if method == "initialize":
        protocol_version = str(params.get("protocolVersion") or _DEFAULT_PROTOCOL_VERSION)
        return {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": _SERVER_NAME, "version": _SERVER_VERSION},
        }
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": list(_TOOL_SCHEMAS)}
    if method == "tools/call":
        name = str(params.get("name", "")).strip()
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object.")
        try:
            if name == "x_recent_search":
                payload = _search_recent_posts(arguments)
            elif name == "x_get_post":
                payload = _get_post(arguments)
            elif name == "x_get_post_by_url":
                payload = _get_post_by_url(arguments)
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
