---
name: x-search
description: Search recent public X posts through the local X Search MCP server. Use for live public discussion, topical research, or a specific X post URL.
---

# X Search

## Overview

This bundle exposes local-only X tools through MCP.

- It is read-only.
- It resolves credentials through environment variables or user-configured 1Password references.
- It never stores raw X secrets in repository files, harness config, or chat.

## When to use it

Use the X Search MCP tools first when:

- recent public discussion on X about a topic
- live social chatter around a company, event, or person
- a bounded recent-search query with timestamps, rate-limit context, and permalinks
- the user says "search X", "search on X", or asks for "the latest on X"
- the user pastes an `x.com` or `twitter.com` status URL

## Tool routing

- Use `x_recent_search` for topical or keyword-driven recent discussion.
- Use `x_get_post_by_url` when the user pastes a specific `x.com` or `twitter.com` post URL.
- Use `x_get_post` when the user gives a numeric X post ID directly.
- When both a pasted URL and a broader X research ask are present, fetch the linked post first, then use recent search if more context is needed.

## Secret posture

- Do not paste raw X bearer tokens, consumer keys, consumer secrets, or 1Password service-account tokens into chat.
- If auth fails, check the local environment variables or update the installed bundle's `config/provider_refs.json`.
- Prefer rotating or updating refs locally rather than passing secrets through the harness.

## Installation note

- The committed `.mcp.json` is a portable source-tree default for clients that load project MCP config.
- For an isolated local install, run `python3 scripts/install.py --destination ~/.local/share/x-search-mcp`.
- Codex and Claude Code manifests are included as optional harness adapters.
