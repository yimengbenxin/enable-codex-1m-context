#!/usr/bin/env python3
"""Remove the Sol context-sync scheduler and safely restore managed config keys."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from context_sync_common import (
    MAC_LABEL,
    WINDOWS_TASK_NAME,
    SyncError,
    atomic_write_text,
    config_path,
    load_install_state,
    output_catalog_path,
    resolve_codex_home,
    restore_config_text,
    runtime_dir,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", help="Codex home; defaults to CODEX_HOME or ~/.codex")
    parser.add_argument("--keep-config", action="store_true", help="Leave config.toml unchanged")
    parser.add_argument("--keep-generated-files", action="store_true", help="Keep runtime and fixed catalog files")
    parser.add_argument(
        "--remove-skill",
        action="store_true",
        help="Also delete the installed enable-codex-1m-context skill directory",
    )
    parser.add_argument("--skill-root", help="Override the skill directory used by --remove-skill")
    return parser.parse_args()


def validated_skill_root(explicit: str | None) -> Path:
    candidate = Path(explicit).expanduser().resolve() if explicit else Path(__file__).resolve().parent.parent
    if candidate.name != "enable-codex-1m-context":
        raise SyncError(f"Refusing to delete unexpected skill directory: {candidate}")
    if not (candidate / "SKILL.md").is_file() or not (candidate / "scripts" / "uninstall_sync.py").is_file():
        raise SyncError(f"Refusing to delete an unrecognized skill directory: {candidate}")
    if candidate == Path(candidate.anchor) or candidate == Path.home().resolve():
        raise SyncError(f"Refusing to delete broad path: {candidate}")
    return candidate


def remove_scheduler(state: dict[str, object]) -> dict[str, object]:
    scheduler = state.get("scheduler")
    if not isinstance(scheduler, dict):
        return {"ok": True, "kind": "none", "note": "no scheduler state"}
    kind = scheduler.get("kind")
    if kind == "none":
        return {"ok": True, "kind": "none"}
    if kind == "launchd":
        configured = scheduler.get("path")
        plist_path = Path(str(configured)) if configured else Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"
        domain = f"gui/{os.getuid()}" if hasattr(os, "getuid") else "gui"
        subprocess.run(
            ["launchctl", "bootout", domain, str(plist_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        if plist_path.exists():
            plist_path.unlink()
        return {"ok": True, "kind": kind, "path": str(plist_path)}
    if kind == "task-scheduler":
        executable = shutil.which("schtasks.exe") or shutil.which("schtasks")
        if executable:
            subprocess.run(
                [executable, "/Delete", "/TN", WINDOWS_TASK_NAME, "/F"],
                text=True,
                capture_output=True,
                check=False,
            )
        return {"ok": True, "kind": kind, "name": WINDOWS_TASK_NAME}
    return {"ok": False, "kind": str(kind), "error": "unknown scheduler kind"}


def main() -> int:
    args = parse_args()
    codex_home = resolve_codex_home(args.codex_home)
    try:
        state = load_install_state(codex_home)
        if not state:
            raise SyncError("Install state is missing; refusing to guess which config values to restore")
        scheduler_result = remove_scheduler(state)

        config_result: dict[str, object] = {"changed": False}
        config_file = config_path(codex_home)
        if not args.keep_config and config_file.exists():
            previous = state.get("previous_config_lines")
            managed = state.get("managed_config_lines")
            if not isinstance(previous, dict) or not isinstance(managed, dict):
                raise SyncError("Install state does not contain safe config restoration data")
            current = config_file.read_text(encoding="utf-8")
            restored, skipped = restore_config_text(current, previous, managed)
            if restored != current:
                backup = codex_home / (
                    "config.toml.before-sol-context-sync-uninstall."
                    + datetime.now().strftime("%Y%m%d-%H%M%S")
                    + ".bak"
                )
                atomic_write_text(backup, current)
                atomic_write_text(config_file, restored)
                config_result = {"changed": True, "backup": str(backup), "skipped_modified_keys": skipped}
            else:
                config_result = {"changed": False, "skipped_modified_keys": skipped}

        removed: list[str] = []
        if not args.keep_generated_files:
            output = output_catalog_path(codex_home)
            if output.exists() and output.parent.resolve() == codex_home.resolve():
                output.unlink()
                removed.append(str(output))
            runtime = runtime_dir(codex_home)
            if runtime.exists() and runtime.parent.resolve() == codex_home.resolve():
                shutil.rmtree(runtime)
                removed.append(str(runtime))

        removed_skill = None
        skill_cleanup_error = None
        if args.remove_skill:
            skill_root = validated_skill_root(args.skill_root)
            try:
                shutil.rmtree(skill_root)
                removed_skill = str(skill_root)
            except OSError as exc:
                skill_cleanup_error = (
                    f"Could not remove {skill_root}: {exc}. Close Codex and delete this directory manually."
                )

        print(
            json.dumps(
                {
                    "ok": bool(scheduler_result.get("ok")),
                    "scheduler": scheduler_result,
                    "config": config_result,
                    "removed": removed,
                    "removed_skill": removed_skill,
                    "skill_cleanup_error": skill_cleanup_error,
                    "restart_required": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if scheduler_result.get("ok") and not skill_cleanup_error else 2
    except (OSError, SyncError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
