# Codex X Search Plugin

A read-only Codex plugin for searching recent public posts on X through a local MCP server.

The plugin keeps X credentials on your machine, calls the X API directly, and returns post text, authors, timestamps, metrics, permalinks, and rate-limit metadata to Codex.

## What it provides

| Tool | Use it for |
| --- | --- |
| `x_recent_search` | Search recent public posts by keyword or X query syntax. |
| `x_get_post` | Fetch one public post by numeric post ID. |
| `x_get_post_by_url` | Fetch one public post from an `x.com` or `twitter.com` URL. |

The bundled `x-search` skill tells Codex when to use each tool. A legacy `x-api` skill and launcher remain available for older tasks.

## Requirements

- Codex with plugin support
- Python 3.10 or newer
- X API credentials with access to the endpoints you want to use
- Optional: the [1Password CLI](https://developer.1password.com/docs/cli/) for local Secret Reference resolution

See the official [Codex plugin guide](https://learn.chatgpt.com/docs/plugins) and [plugin authoring guide](https://learn.chatgpt.com/docs/build-plugins) for current product and marketplace behavior.

## Install

Clone the repository, then copy the plugin into a personal marketplace directory:

```bash
git clone https://github.com/ClawRyderz/codex-x-search-plugin.git
cd codex-x-search-plugin
python3 scripts/install_local_plugin.py \
  --destination ~/.agents/plugins/plugins/x-search
```

The installer copies the bundle, renders absolute paths in the installed `.mcp.json`, and creates an `x-api` compatibility alias beside `x-search`. Re-run it with `--force` to replace an existing install.

Add this entry to `~/.agents/plugins/marketplace.json`. If the file already contains other plugins, append only the `x-search` object to its existing `plugins` array.

```json
{
  "name": "personal",
  "interface": {
    "displayName": "Personal"
  },
  "plugins": [
    {
      "name": "x-search",
      "source": {
        "source": "local",
        "path": "./plugins/x-search"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Research"
    }
  ]
}
```

Restart the ChatGPT desktop app, open **Plugins**, choose **Personal**, and install **X Search**. Start a new task after installation so the bundled skill and MCP tools are loaded.

## Configure credentials

No credential or private 1Password reference is included in this repository. Configure credentials only in the installed copy or its runtime environment.

### Option 1: environment variable

Provide an existing bearer token through `X_SEARCH_BEARER_TOKEN`. The legacy name `X_API_BEARER_TOKEN` is also supported.

Set the variable in the trusted environment that launches Codex. Avoid committing it to a shell profile, project file, or MCP manifest.

### Option 2: 1Password Secret References

Edit the installed file at `~/.agents/plugins/plugins/x-search/config/provider_refs.json`:

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

You can instead provide an X app key and secret. The plugin exchanges the pair for an app-only bearer token:

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

Authenticate the 1Password CLI normally, or use `OP_SERVICE_ACCOUNT_TOKEN`. If you keep the service-account token in a protected local file, point to it with `OP_SERVICE_ACCOUNT_TOKEN_FILE` or `X_SEARCH_OP_SERVICE_ACCOUNT_TOKEN_FILE`.

## Use

Ask Codex naturally, for example:

- “Search X for recent posts about OpenAI Codex.”
- “Find recent English-language posts about `from:OpenAI Codex`.”
- “Fetch `https://x.com/openai/status/…`.”
- “Get X post ID `1234567890`.”

Recent search supports `max_results`, up to five pages, `recency` or `relevancy` sorting, and optional ISO-8601 `start_time` and `end_time` bounds. Availability and query limits depend on your X API access.

## Security and privacy

- The MCP server runs locally over standard input/output.
- The plugin is read-only and does not post, like, follow, or modify X data.
- Raw credentials are not stored in the repository, plugin manifest, or tool responses.
- 1Password Secret References are resolved locally at runtime.
- X requests are sent directly to `api.x.com`; X's terms and privacy policy apply.

Treat local config files containing private vault or item names as sensitive, even when they contain references rather than secret values.

## Development

Run the test suite from the repository root:

```bash
python3 -m pytest tests -q
```

Key files:

- `.codex-plugin/plugin.json` — plugin manifest
- `.mcp.json` — portable source-tree MCP configuration
- `config/provider_refs.json` — empty, safe-to-publish credential-source template
- `scripts/x_search_mcp.py` — local MCP server
- `scripts/install_local_plugin.py` — local installer and MCP config renderer
- `skills/x-search/SKILL.md` — Codex routing guidance

## License

[MIT](LICENSE)
