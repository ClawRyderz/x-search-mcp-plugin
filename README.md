# X Search MCP Plugin

A portable, read-only MCP server for searching recent public posts on X.

The core server is harness-neutral. It speaks standard newline-delimited stdio MCP and can run in Claude Code, Codex, or any MCP client that can launch a local command. Native Claude Code and Codex plugin manifests are included as optional adapters.

## Tools

| Tool | Purpose |
| --- | --- |
| `x_recent_search` | Search recent public posts by keyword or X query syntax. |
| `x_get_post` | Fetch one public post by numeric post ID. |
| `x_get_post_by_url` | Fetch one public post from an `x.com` or `twitter.com` URL. |

The optional doctor mode adds `x_auth_doctor` for redacted diagnostics and
`x_refresh_runtime_token` for refreshing the local bearer-token cache. Normal
search sessions do not receive those admin tools.

The three runtime tools advertise read-only, non-destructive MCP annotations.
The doctor refresh tool is explicitly marked as a local write operation.

## Compatibility

| Harness | Integration |
| --- | --- |
| Any stdio MCP client | Run `scripts/x_search_mcp.py` with Python. |
| Claude Code | Use `.claude-plugin/plugin.json`, `claude mcp add`, or the root `.mcp.json`. |
| Codex | Use `.codex-plugin/plugin.json`, `codex mcp add`, or the root `.mcp.json`. |

The server negotiates MCP protocol versions `2024-11-05`, `2025-03-26`, and `2025-06-18`. Standard JSONL framing is the default; legacy `Content-Length` framing remains supported for older clients.

## Requirements

- Python 3.10 or newer
- X API credentials with access to the endpoints you want to use
- Optional: the [1Password CLI](https://developer.1password.com/docs/cli/) for local Secret Reference resolution

## Install

Clone the repository and create an isolated local bundle:

```bash
git clone https://github.com/ClawRyderz/x-search-mcp-plugin.git
cd x-search-mcp-plugin
python3 scripts/install.py \
  --destination ~/.local/share/x-search-mcp-plugin
```

The installer copies the bundle, excludes repository history and caches, and renders an absolute-path `.mcp.json`. Re-run it with `--force` to replace an existing installation.

When the destination is named `x-search`, the installer also creates sibling
`x-search-doctor` and legacy `x-api` entries. For another layout, pass
`--doctor-destination`, `--compat-alias-destination`, or disable either one.

## Configure credentials

No credentials or private 1Password references are included. Configure the installed copy at `~/.local/share/x-search-mcp-plugin/config/provider_refs.json`, use an external config through `X_SEARCH_CONFIG_FILE`, or provide credentials through environment variables.

Private config files can also be supplied without modifying the checkout:

```bash
python3 scripts/install.py \
  --destination ~/plugins/x-search \
  --runtime-config ~/.config/x-search-mcp/runtime.json \
  --doctor-config ~/.config/x-search-mcp/doctor.json
```

The public templates intentionally contain no vault or item names.

### Environment variable

Provide an existing bearer token through `X_SEARCH_BEARER_TOKEN`. The legacy name `X_API_BEARER_TOKEN` is also supported.

Set it only in the trusted environment that launches your MCP client. Do not commit it to a repository or MCP manifest.

### 1Password Secret References

```json
{
  "credential_sources": {
    "bearer_token_ref_candidates": [
      "op://YOUR_VAULT/YOUR_X_BEARER_TOKEN_ITEM/password"
    ],
    "api_key_ref_candidates": [],
    "api_secret_ref_candidates": []
  }
}
```

You can instead provide an X app key and secret. The server exchanges the pair for an app-only bearer token:

```json
{
  "credential_sources": {
    "bearer_token_ref_candidates": [],
    "api_key_ref_candidates": [
      "op://YOUR_VAULT/YOUR_X_API_KEY_ITEM/password"
    ],
    "api_secret_ref_candidates": [
      "op://YOUR_VAULT/YOUR_X_API_SECRET_ITEM/password"
    ]
  }
}
```

Authenticate the 1Password CLI normally, or use `OP_SERVICE_ACCOUNT_TOKEN`. For a protected token file, set `OP_SERVICE_ACCOUNT_TOKEN_FILE` or `X_SEARCH_OP_SERVICE_ACCOUNT_TOKEN_FILE`.

## Connect a harness

### Claude Code

Load the native plugin for one session:

```bash
claude --plugin-dir ~/.local/share/x-search-mcp-plugin
```

This loads the bundled skill and MCP server. For a persistent user-level MCP registration without the skill:

```bash
claude mcp add x-search --scope user \
  -e X_SEARCH_CONFIG_FILE=$HOME/.local/share/x-search-mcp-plugin/config/provider_refs.json \
  -- python3 $HOME/.local/share/x-search-mcp-plugin/scripts/x_search_mcp.py
```

See [Claude Code's MCP documentation](https://code.claude.com/docs/en/mcp) for scopes and project `.mcp.json` approval behavior.

### Codex

Register the stdio server directly:

```bash
codex mcp add x-search \
  --env X_SEARCH_CONFIG_FILE=$HOME/.local/share/x-search-mcp-plugin/config/provider_refs.json \
  -- python3 $HOME/.local/share/x-search-mcp-plugin/scripts/x_search_mcp.py
```

The bundle also includes `.codex-plugin/plugin.json` and the `x-search` skill for Codex marketplace packaging. See the official [Codex plugin guide](https://learn.chatgpt.com/docs/plugins).

### Other MCP clients

Use the absolute-path `.mcp.json` produced by the installer, or adapt this entry to your client's config format:

```json
{
  "mcpServers": {
    "x-search": {
      "command": "python3",
      "args": [
        "/ABSOLUTE/PATH/x-search-mcp-plugin/scripts/x_search_mcp.py"
      ],
      "env": {
        "X_SEARCH_CONFIG_FILE": "/ABSOLUTE/PATH/x-search-mcp-plugin/config/provider_refs.json"
      }
    }
  }
}
```

## Use

Ask your harness naturally, for example:

- “Search X for recent posts about MCP security.”
- “Find recent English-language posts matching `from:OpenAI Codex`.”
- “Fetch `https://x.com/openai/status/…`.”
- “Get X post ID `1234567890`.”

Recent search supports `max_results`, up to five pages, `recency` or `relevancy` sorting, and optional ISO-8601 `start_time` and `end_time` bounds. Availability and query limits depend on your X API access.

## Security and privacy

- The server runs locally over standard input/output.
- It is read-only and cannot post, like, follow, or modify X data.
- Raw credentials are not stored in repository files or tool responses.
- 1Password Secret References are resolved locally at runtime.
- X requests go directly to `api.x.com`; X's terms and privacy policy apply.

Treat config files containing private vault or item names as sensitive even when they contain references rather than secret values.

For the recommended split install, keep the runtime config limited to its local
bearer-token file and put 1Password refs or OAuth client credentials in the
doctor config. This preserves an approval-free read path while keeping repair
capabilities isolated. Single-bundle MCP clients retain the existing environment
and user-configured Secret Reference fallbacks for compatibility.

## Development

```bash
python3 -m pytest tests -q
```

Key paths:

- `scripts/x_search_mcp.py` — harness-neutral MCP server
- `scripts/x_search_doctor.py` — redacted command-line auth diagnostics
- `scripts/mcp_stdio.py` — standard JSONL stdio transport with legacy compatibility
- `.mcp.json` — portable source-tree MCP config
- `.claude-plugin/plugin.json` — Claude Code adapter
- `.codex-plugin/plugin.json` — Codex adapter
- `skills/x-search/SKILL.md` — cross-compatible agent skill
- `scripts/install.py` — generic local installer

## License

[MIT](LICENSE)
