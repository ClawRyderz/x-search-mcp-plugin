---
name: x-search-doctor
description: Diagnose and refresh the local X Search runtime token. Use when the normal X Search plugin says the bearer-token file is missing, stale, or invalid.
---

# X Search Doctor

## Overview

This plugin is the admin and repair side of the local X Search setup.

- It is not for normal X research.
- It is the only plugin that should read 1Password-backed X credential refs.
- It can diagnose auth problems and refresh the runtime bearer-token file used by `x-search`.

## When to use it

Use the X Search Doctor plugin when:

- the runtime `x-search` plugin says the bearer-token file is missing
- the runtime `x-search` plugin says the bearer token was rejected or looks stale
- you rotated X credentials and need to refresh the local runtime token cache
- you need to verify whether vault visibility, bearer refs, or client credentials are broken

## Tool routing

- Use `x_auth_doctor` to diagnose vault visibility, bearer refs, and OAuth client-credentials health without exposing secrets.
- Use `x_refresh_runtime_token` to mint or read a fresh bearer token from admin credential sources, write it to the runtime bearer-token file, and verify it with a small probe query.
- After `x_refresh_runtime_token` succeeds, switch back to the normal `x-search` plugin for day-to-day searches.

## Secret posture

- Do not paste raw X bearer tokens, consumer keys, consumer secrets, or 1Password service-account tokens into chat.
- Keep 1Password refs in the doctor plugin only, not in the runtime plugin.
- Treat `~/plugins/x-search-doctor/config/provider_refs.json` as the admin config surface.
- Treat `~/plugins/x-search/config/provider_refs.json` as the runtime-only config surface.
- Keep vault names, item names, and field references in a private doctor config supplied at installation time or through the documented environment variables.
- The public template uses `~/.config/x-search-mcp/op-service-account-token`; override that path in private configuration when needed.

## Install note

- Run `python3 scripts/install_local_plugin.py --destination ~/plugins/x-search` to install both bundles together.
- The installer creates `~/plugins/x-search` for normal searches and `~/plugins/x-search-doctor` for admin repair work.
- If you want the clean zero-approval posture for normal X searches, disable or remove the older `x-api` plugin entry from Codex after moving to this split setup.
