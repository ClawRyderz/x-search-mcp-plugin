#!/usr/bin/env python3

"""Render an absolute-path MCP config for the current X Search install location."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_mcp_payload(
    bundle_root: Path,
    *,
    server_name: str,
    mode: str,
    config_relative_path: str = "config/provider_refs.json",
) -> dict[str, object]:
    return {
        "mcpServers": {
            server_name: {
                "command": "python3",
                "args": [str(bundle_root / "scripts" / "x_search_mcp.py")],
                "env": {
                    "PYTHONUNBUFFERED": "1",
                    "X_SEARCH_CONFIG_FILE": str(bundle_root / config_relative_path),
                    "X_SEARCH_PLUGIN_MODE": mode,
                },
            }
        }
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rewrite .mcp.json with absolute paths for the installed server bundle."
    )
    parser.add_argument(
        "--bundle-root",
        "--plugin-root",
        dest="bundle_root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Root directory of the installed server bundle.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for the rendered .mcp.json. Defaults to <bundle-root>/.mcp.json.",
    )
    parser.add_argument(
        "--mode",
        choices=("runtime", "doctor"),
        default="runtime",
        help="Logical mode exposed by this MCP server entry.",
    )
    parser.add_argument(
        "--server-name",
        default=None,
        help="Optional MCP server name override.",
    )
    parser.add_argument(
        "--config-relative-path",
        default="config/provider_refs.json",
        help="Bundle-relative provider configuration path.",
    )
    args = parser.parse_args(argv)

    raw_bundle_root = Path(args.bundle_root).expanduser()
    bundle_root = raw_bundle_root if raw_bundle_root.is_absolute() else raw_bundle_root.resolve()
    if args.output:
        raw_output_path = Path(args.output).expanduser()
        output_path = raw_output_path if raw_output_path.is_absolute() else raw_output_path.resolve()
    else:
        output_path = bundle_root / ".mcp.json"
    server_name = args.server_name or (
        "x-search-doctor-local" if args.mode == "doctor" else "x-search-local"
    )
    payload = build_mcp_payload(
        bundle_root,
        server_name=server_name,
        mode=args.mode,
        config_relative_path=args.config_relative_path,
    )
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
