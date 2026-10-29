#!/usr/bin/env python3

"""Command-line access to the read-only X Search tools, for shells without MCP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from x_search_mcp import _get_post, _get_post_by_url, _search_recent_posts  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch public X posts or run a recent search. Prints JSON."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    post = commands.add_parser("post", help="Fetch one post by x.com/twitter.com URL or numeric ID.")
    post.add_argument("target", help="Status URL or numeric post ID.")

    search = commands.add_parser("search", help="Search public posts from the last seven days.")
    search.add_argument("query", help="X recent-search query string.")
    search.add_argument("--max-results", type=int, default=10)
    search.add_argument("--pages", type=int, default=1)
    search.add_argument("--sort-order", choices=("recency", "relevancy"), default="recency")

    args = parser.parse_args(argv)
    try:
        if args.command == "post":
            target = args.target.strip()
            if target.isdigit():
                result = _get_post({"post_id": target})
            else:
                result = _get_post_by_url({"url": target})
        else:
            result = _search_recent_posts(
                {
                    "query": args.query,
                    "max_results": args.max_results,
                    "pages": args.pages,
                    "sort_order": args.sort_order,
                }
            )
    except ValueError as exc:
        print(f"x-search: {exc}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
