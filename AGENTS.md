# X Search MCP Plugin agent instructions

A portable, read-only stdio MCP server for searching and reading public posts on
X, with optional Claude Code and Codex plugin adapters. See `README.md` for the
tools, install flow and key paths.

## Worktree discipline

- One session owns each working checkout. Keep the base clone on `main` and
  perform branch work in a dedicated session-owned worktree.
- Inspect existing worktrees before overlapping work. Follow the repository's
  branch convention and start from the appropriate current base revision.
- If the base clone is dirty or on another branch, preserve it and use an
  isolated worktree. Do not reset, stash, or switch someone else's working copy.
- Clean up owned worktrees after integration when their work is preserved and
  removal is authorized; never remove unrelated work.

## This repository

- Checks: `python3 -m pytest tests -q` (needs `pytest`); CI workflow `Verify`,
  job `tests`, runs the same on Python 3.12.
- This repository is public. Never commit credentials, bearer tokens, private
  1Password vault or item names, or personal config; the templates in `config/`
  stay placeholder-only.
- Keep the runtime tools read-only. Write-capable tools belong only in the
  separate doctor mode.
- Tests mock the X API; no real API calls.
