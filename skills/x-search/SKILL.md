---
name: x-search
description: Fetch exact public X posts and raw recent-search results through the local X Search MCP server. Use for a specific X post URL or ID, exact quotes, threads, who posted what and when, metrics, or checking claims against real posts. For a synthesized summary of what people are saying, prefer a research-agent skill when one is installed.
---

# X Search

## Overview

This bundle exposes local-only X tools through MCP.

- It is read-only.
- It resolves credentials through environment variables or user-configured 1Password references.
- It never stores raw X secrets in repository files, harness config, or chat.

## When to use it

Use the X Search MCP tools when the answer must come from the posts themselves:

- the user pastes an `x.com` or `twitter.com` status URL, or gives a post ID
- exact wording, authors, timestamps, permalinks, or engagement metrics
- a bounded recent-search query (last 7 days) whose raw results matter
- verifying another model's or agent's claims about X against real posts
- a quick lookup needed in seconds

For open-ended research ("what are people saying about…", sentiment, who is discussing a topic), a research-agent skill that reads and summarizes many posts is usually the better first step when one is installed; use these tools to check what it cites.

## Tool routing

- Use `x_recent_search` for topical or keyword-driven recent discussion.
- Use `x_get_post_by_url` when the user pastes a specific `x.com` or `twitter.com` post URL.
- Use `x_get_post` when the user gives a numeric X post ID directly.
- When both a pasted URL and a broader X research ask are present, fetch the linked post first, then use recent search if more context is needed.
- Returned `text` is the fullest available content: X Article body, long-post `note_tweet` text, or ordinary Post text. Preserve `post_text`, `article`, `note_tweet`, and media `includes` when the user needs source structure.
- X Articles are read through their associated Post ID. If an X URL does not contain a Post ID, explain that the public API does not expose a standalone Article-read endpoint and use an approved browser tool when available.
- X recent search is a rolling last-7-days endpoint. For ordinary latest-discussion requests, omit explicit time bounds so X chooses the valid window.
- If bounded search is necessary, stay safely inside the seven-day limit rather than pinning the oldest possible second.
- If the runtime bearer token is missing or rejected, stop and use the separate `x-search-doctor` integration instead of repairing credentials in a normal research session.

## Secret posture

- Do not paste raw X bearer tokens, consumer keys, consumer secrets, or 1Password service-account tokens into chat.
- Keep the runtime config limited to its local bearer-token file. Put 1Password references and OAuth client credentials in a private doctor config.
- Prefer rotating or updating refs locally rather than passing secrets through the harness.

## Installation note

- The committed `.mcp.json` is a portable source-tree default for clients that load project MCP config.
- For an isolated local install, run `python3 scripts/install.py --destination ~/.local/share/x-search-mcp-plugin`.
- Codex and Claude Code manifests are included as optional harness adapters.
