#!/usr/bin/env python3

"""Redacted local diagnostics for the X Search plugin."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
ADMIN_CONFIG_PATH = SCRIPT_DIR.parent / "config" / "provider_refs.admin.json"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from x_search_mcp import (  # noqa: E402
    _CONFIG_ENV_VAR,
    _DEFAULT_DOCTOR_PROBE_QUERY,
    _LEGACY_CONFIG_ENV_VAR,
    _diagnose_auth,
    _resolve_config_path,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose local X Search auth without exposing secrets. "
            "Reports config path, candidate refs, 1Password vault visibility, "
            "and live bearer/client-credentials probe results."
        )
    )
    parser.add_argument(
        "--config-file",
        default=None,
        help="Optional path to the provider refs JSON file.",
    )
    parser.add_argument(
        "--probe-query",
        default=_DEFAULT_DOCTOR_PROBE_QUERY,
        help="Recent-search query used for the live auth probe.",
    )
    args = parser.parse_args(argv)

    if args.config_file:
        os.environ[_CONFIG_ENV_VAR] = str(Path(args.config_file).expanduser())
        os.environ.pop(_LEGACY_CONFIG_ENV_VAR, None)
    elif ADMIN_CONFIG_PATH.exists():
        os.environ[_CONFIG_ENV_VAR] = str(ADMIN_CONFIG_PATH)
        os.environ.pop(_LEGACY_CONFIG_ENV_VAR, None)

    payload = _diagnose_auth({"probe_query": args.probe_query})
    payload["resolved_config_file"] = str(_resolve_config_path())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("healthy") else 1


if __name__ == "__main__":
    raise SystemExit(main())
