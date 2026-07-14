---
name: x-api
description: Search recent public X posts through the local X API MCP server. Use when the user wants live recent discussion, topical research, or the latest public posts from X.
---

# X API

This legacy skill entry is kept so older client sessions that still route to
`x-api` continue to resolve into the same local X plugin bundle.

It is runtime-only now and should use the same local bearer-token file as
`x-search`.

For `x_recent_search`, remember that X recent search is a rolling last-7-days
window. Prefer leaving time bounds unset for "latest discussion" requests, and
avoid pinning `start_time` exactly at the 7-day boundary because that timestamp
can already be out of range by the time the request runs.

If the runtime token fails or is missing, stop and switch to the separate
`x-search-doctor` plugin instead of trying to repair auth through `x-api`.
