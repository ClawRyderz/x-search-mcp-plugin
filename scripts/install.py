#!/usr/bin/env python3

"""Install the X Search MCP bundle and render an absolute stdio config."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from render_mcp_config import main as render_mcp_config_main  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the X Search MCP server into a local directory."
    )
    parser.add_argument(
        "--bundle-root",
        "--plugin-root",
        dest="bundle_root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Source bundle root directory.",
    )
    parser.add_argument(
        "--destination",
        required=True,
        help="Destination directory for the installed server bundle.",
    )
    parser.add_argument(
        "--compat-alias-destination",
        default=None,
        help=(
            "Optional compatibility alias path to point at the installed bundle. "
            "Defaults to a sibling path named x-api when the destination is named x-search."
        ),
    )
    parser.add_argument(
        "--no-compat-alias",
        action="store_true",
        help="Skip creating the legacy x-api compatibility alias.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing destination directory.",
    )
    args = parser.parse_args(argv)

    bundle_root = Path(args.bundle_root).expanduser().resolve()
    raw_destination = Path(args.destination).expanduser()
    destination = raw_destination if raw_destination.is_absolute() else raw_destination.resolve()
    compat_alias_destination = _resolve_compat_alias_destination(
        destination=destination,
        explicit_value=args.compat_alias_destination,
        disable_alias=args.no_compat_alias,
    )
    if not bundle_root.is_dir():
        raise ValueError(f"Bundle root does not exist: {bundle_root}")
    if destination.exists():
        if not args.force:
            raise ValueError(
                f"Destination already exists: {destination}. Use --force to replace it."
            )
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
        else:
            shutil.rmtree(destination)

    shutil.copytree(
        bundle_root,
        destination,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"),
    )
    render_mcp_config_main(
        [
            "--bundle-root",
            str(destination),
            "--output",
            str(destination / ".mcp.json"),
        ]
    )
    if compat_alias_destination is not None:
        _install_compat_alias(
            installed_destination=destination,
            compat_alias_destination=compat_alias_destination,
            force=args.force,
        )
    print(str(destination))
    return 0


def _resolve_compat_alias_destination(
    *,
    destination: Path,
    explicit_value: str | None,
    disable_alias: bool,
) -> Path | None:
    if disable_alias:
        return None
    if explicit_value:
        raw_alias = Path(explicit_value).expanduser()
        return raw_alias if raw_alias.is_absolute() else raw_alias.resolve()
    if destination.name == "x-search":
        return destination.with_name("x-api")
    return None


def _install_compat_alias(
    *,
    installed_destination: Path,
    compat_alias_destination: Path,
    force: bool,
) -> None:
    if compat_alias_destination == installed_destination:
        return
    if compat_alias_destination.exists() or compat_alias_destination.is_symlink():
        if not force:
            raise ValueError(
                f"Compatibility alias already exists: {compat_alias_destination}. Use --force to replace it."
            )
        if compat_alias_destination.is_symlink() or compat_alias_destination.is_file():
            compat_alias_destination.unlink()
        else:
            shutil.rmtree(compat_alias_destination)
    compat_alias_destination.parent.mkdir(parents=True, exist_ok=True)
    compat_alias_destination.symlink_to(installed_destination, target_is_directory=True)


if __name__ == "__main__":
    raise SystemExit(main())
