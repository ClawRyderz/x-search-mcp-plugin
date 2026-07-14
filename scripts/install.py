#!/usr/bin/env python3

"""Install harness-neutral X Search runtime and doctor MCP bundles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from render_mcp_config import build_mcp_payload  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the X Search runtime and doctor MCP bundles."
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
        help="Destination directory for the runtime bundle.",
    )
    parser.add_argument(
        "--doctor-destination",
        default=None,
        help=(
            "Optional destination for the doctor bundle. Defaults to a sibling "
            "x-search-doctor directory when the runtime destination is named x-search."
        ),
    )
    parser.add_argument(
        "--no-doctor-bundle",
        action="store_true",
        help="Skip creating a companion doctor bundle.",
    )
    parser.add_argument(
        "--runtime-config",
        default=None,
        help="Optional private runtime provider-refs JSON copied into the installed bundle.",
    )
    parser.add_argument(
        "--doctor-config",
        default=None,
        help="Optional private doctor provider-refs JSON copied into the installed bundle.",
    )
    parser.add_argument(
        "--compat-alias-destination",
        default=None,
        help=(
            "Optional x-api compatibility alias. Defaults to a sibling x-api path "
            "when the runtime destination is named x-search."
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
        help="Replace existing destination directories.",
    )
    args = parser.parse_args(argv)

    bundle_root = _resolve_path(args.bundle_root)
    destination = _resolve_path(args.destination)
    doctor_destination = _resolve_doctor_destination(
        destination=destination,
        explicit_value=args.doctor_destination,
        disabled=args.no_doctor_bundle,
    )
    compat_alias_destination = _resolve_compat_alias_destination(
        destination=destination,
        explicit_value=args.compat_alias_destination,
        disabled=args.no_compat_alias,
    )
    runtime_config = _resolve_optional_path(args.runtime_config)
    doctor_config = _resolve_optional_path(args.doctor_config)
    if not bundle_root.is_dir():
        raise ValueError(f"Bundle root does not exist: {bundle_root}")

    _install_runtime_bundle(
        source=bundle_root,
        destination=destination,
        force=args.force,
        private_config=runtime_config,
    )
    if doctor_destination is not None:
        _install_doctor_bundle(
            source=bundle_root,
            destination=doctor_destination,
            force=args.force,
            private_config=doctor_config,
        )
    if compat_alias_destination is not None:
        _install_compat_alias(
            installed_destination=destination,
            compat_alias_destination=compat_alias_destination,
            force=args.force,
        )

    print(str(destination))
    return 0


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else path.resolve()


def _resolve_optional_path(value: str | None) -> Path | None:
    return _resolve_path(value) if value else None


def _resolve_doctor_destination(
    *, destination: Path, explicit_value: str | None, disabled: bool
) -> Path | None:
    if disabled:
        return None
    if explicit_value:
        return _resolve_path(explicit_value)
    if destination.name == "x-search":
        return destination.with_name("x-search-doctor")
    return None


def _resolve_compat_alias_destination(
    *, destination: Path, explicit_value: str | None, disabled: bool
) -> Path | None:
    if disabled:
        return None
    if explicit_value:
        return _resolve_path(explicit_value)
    if destination.name == "x-search":
        return destination.with_name("x-api")
    return None


def _replace_path(path: Path, *, force: bool) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if not force:
        raise ValueError(f"Destination already exists: {path}. Use --force to replace it.")
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def _copy_bundle(*, source: Path, destination: Path, force: bool) -> None:
    _replace_path(destination, force=force)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"),
    )


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _install_private_config(destination: Path, private_config: Path | None) -> None:
    if private_config is None:
        return
    if not private_config.is_file():
        raise ValueError(f"Private config does not exist: {private_config}")
    payload = json.loads(private_config.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Private config must contain a JSON object: {private_config}")
    _write_json(destination / "config" / "provider_refs.json", payload)


def _render_mcp(destination: Path, *, mode: str, server_name: str) -> None:
    payload = build_mcp_payload(
        destination,
        server_name=server_name,
        mode=mode,
    )
    _write_json(destination / ".mcp.json", payload)


def _install_runtime_bundle(
    *, source: Path, destination: Path, force: bool, private_config: Path | None
) -> None:
    _copy_bundle(source=source, destination=destination, force=force)
    for relative in (
        "config/provider_refs.admin.json",
        "skills/x-search-doctor",
        "scripts/x_search_doctor.py",
    ):
        _remove(destination / relative)
    _install_private_config(destination, private_config)
    _render_mcp(destination, mode="runtime", server_name="x-search-local")


def _prepare_doctor_manifests(destination: Path) -> None:
    codex_path = destination / ".codex-plugin" / "plugin.json"
    if codex_path.exists():
        payload = json.loads(codex_path.read_text(encoding="utf-8"))
        payload["name"] = "x-search-doctor"
        payload["description"] = "Diagnose and refresh the local X Search runtime token."
        interface = payload.get("interface")
        if isinstance(interface, dict):
            interface["displayName"] = "X Search Doctor"
            interface["shortDescription"] = "Repair the X Search runtime token"
            interface["capabilities"] = ["Interactive", "Write"]
        _write_json(codex_path, payload)

    claude_path = destination / ".claude-plugin" / "plugin.json"
    if claude_path.exists():
        payload = json.loads(claude_path.read_text(encoding="utf-8"))
        payload["name"] = "x-search-doctor"
        payload["description"] = "Diagnose and refresh the local X Search runtime token."
        payload["mcpServers"] = build_mcp_payload(
            Path("${CLAUDE_PLUGIN_ROOT}"),
            server_name="x-search-doctor-local",
            mode="doctor",
        )["mcpServers"]
        _write_json(claude_path, payload)


def _install_doctor_bundle(
    *, source: Path, destination: Path, force: bool, private_config: Path | None
) -> None:
    _copy_bundle(source=source, destination=destination, force=force)
    for relative in ("skills/x-search", "skills/x-api"):
        _remove(destination / relative)
    admin_path = destination / "config" / "provider_refs.admin.json"
    if not admin_path.is_file():
        raise ValueError(f"Doctor config template is missing: {admin_path}")
    (destination / "config" / "provider_refs.json").write_text(
        admin_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    admin_path.unlink()
    _install_private_config(destination, private_config)
    _prepare_doctor_manifests(destination)
    _render_mcp(destination, mode="doctor", server_name="x-search-doctor-local")


def _install_compat_alias(
    *, installed_destination: Path, compat_alias_destination: Path, force: bool
) -> None:
    if compat_alias_destination == installed_destination:
        return
    _replace_path(compat_alias_destination, force=force)
    compat_alias_destination.parent.mkdir(parents=True, exist_ok=True)
    compat_alias_destination.symlink_to(installed_destination, target_is_directory=True)


if __name__ == "__main__":
    raise SystemExit(main())
