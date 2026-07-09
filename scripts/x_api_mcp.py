#!/usr/bin/env python3

"""Backward-compatible entrypoint for older x-api plugin launchers."""

from x_search_mcp import main


if __name__ == "__main__":
    raise SystemExit(main())
