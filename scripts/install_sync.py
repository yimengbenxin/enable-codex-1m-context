#!/usr/bin/env python3
"""Install the portable Sol 1M catalog sync and its platform scheduler."""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from context_sync_common import (
    MAC_LABEL,
    VERSION,
    WINDOWS_TASK_NAME,
    SyncError,
    atomic_write_bytes,
    atomic_write_text,
    config_path,
    install_state_path,
    load_install_state,
    output_catalog_path,
    patch_config_text,
    resolve_codex_home,
    runtime_dir,
    save_install_state,
    source_catalog_path,
    sync_catalog,
    utc_now,
    write_config_backup,
)


RUNTIME_FILES = (
    "context_sync_common.py",
    "sync_catalog.py",
    "verify_install.py",
    "uninstall_sync.py",
)


def normalized_platform(requested: str) -> str:
    if requested != "auto":
        return requested
    current = platform.system().lower()
    if current == "darwin":
        return "macos"
    if current == "windows":
        return "windows"
    raise SyncError(f"Unsupported operating system: {platform.system()}")


def copy_runtime_files(destination: Path) -> None:
    source_dir = Path(__file__).resolve().parent
    destination.mkdir(parents=True, exist_ok=True)
    for name in RUNTIME_FILES:
        source = source_dir / name
        if not source.exists():
            raise SyncError(f"Bundled runtime file is missing: {source}")
        target = destination / name
        shutil.copy2(source, target)
        try:
            target.chmod(0o700)
        except OSError:
            pass


def mac_launch_agent_payload(
    python_executable: Path,
    sync_script: Path,
    codex_home: Path,
    log_path: Path,
) -> dict[str, Any]:
    return {
        "Label": MAC_LABEL,
        "ProgramArguments": [
            str(python_executable),
            str(sync_script),
            "--codex-home",
            str(codex_home),
            "--quiet",
            "--log-file",
            str(log_path),
        ],
        "RunAtLoad": True,
        "StartInterval": 180,
        "WatchPaths": [str(source_catalog_path(codex_home))],
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }


def mac_launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def windows_task_action(
    python_executable: Path,
    sync_script: Path,
    codex_home: Path,
    log_path: Path,
) -> str:
    return subprocess.list2cmdline(
        [
            str(python_executable),
            str(sync_script),
            "--codex-home",
            str(codex_home),
            "--quiet",
            "--log-file",
            str(log_path),
        ]
    )


def run_checked(command: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode and not allow_failure:
        detail = (result.stderr or result.stdout).strip()
        raise SyncError(f"Command failed ({result.returncode}): {' '.join(command)}\n{detail}")
    return result


def install_macos_scheduler(
    python_executable: Path,
    sync_script: Path,
    codex_home: Path,
    log_path: Path,
) -> dict[str, Any]:
    plist_path = mac_launch_agent_path()
    payload = mac_launch_agent_payload(python_executable, sync_script, codex_home, log_path)
    atomic_write_bytes(plist_path, plistlib.dumps(payload, sort_keys=True), mode=0o644)
    domain = f"gui/{os.getuid()}"
    run_checked(["launchctl", "bootout", domain, str(plist_path)], allow_failure=True)
    run_checked(["launchctl", "bootstrap", domain, str(plist_path)])
    run_checked(["launchctl", "kickstart", "-k", f"{domain}/{MAC_LABEL}"], allow_failure=True)
    return {"kind": "launchd", "label": MAC_LABEL, "path": str(plist_path)}


def install_windows_scheduler(
    python_executable: Path,
    sync_script: Path,
    codex_home: Path,
    log_path: Path,
) -> dict[str, Any]:
    executable = shutil.which("schtasks.exe") or shutil.which("schtasks")
    if not executable:
        raise SyncError("Windows Task Scheduler command schtasks.exe was not found")
    action = windows_task_action(python_executable, sync_script, codex_home, log_path)
    run_checked(
        [
            executable,
            "/Create",
            "/TN",
            WINDOWS_TASK_NAME,
            "/TR",
            action,
            "/SC",
            "MINUTE",
            "/MO",
            "3",
            "/RL",
            "LIMITED",
            "/F",
        ]
    )
    run_checked([executable, "/Run", "/TN", WINDOWS_TASK_NAME], allow_failure=True)
    return {"kind": "task-scheduler", "name": WINDOWS_TASK_NAME, "action": action}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", help="Codex home; defaults to CODEX_HOME or ~/.codex")
    parser.add_argument(
        "--platform",
        choices=("auto", "macos", "windows"),
        default="auto",
        help="Override platform detection; non-native overrides require --dry-run",
    )
    parser.add_argument("--no-schedule", action="store_true", help="Install files and config without automation")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the plan without writing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if sys.version_info < (3, 9):
        print("Python 3.9 or newer is required", file=sys.stderr)
        return 2

    try:
        chosen_platform = normalized_platform(args.platform)
        actual = platform.system().lower()
        if not args.dry_run and args.platform != "auto":
            expected = "darwin" if chosen_platform == "macos" else "windows"
            if actual != expected:
                raise SyncError("A non-native --platform override is allowed only with --dry-run")

        codex_home = resolve_codex_home(args.codex_home)
        source = source_catalog_path(codex_home)
        if not source.exists():
            raise SyncError(f"{source} does not exist; open Codex once so it can fetch the model catalog")

        runtime = runtime_dir(codex_home)
        binary_dir = runtime / "bin"
        installed_sync = binary_dir / "sync_catalog.py"
        log_path = runtime / "sync.log"
        output = output_catalog_path(codex_home)
        config_file = config_path(codex_home)
        original_config = config_file.read_text(encoding="utf-8") if config_file.exists() else ""
        patched_config, current_previous, managed = patch_config_text(original_config, output)
        existing_state = load_install_state(codex_home)
        previous_lines = (
            existing_state.get("previous_config_lines")
            if isinstance(existing_state, dict) and isinstance(existing_state.get("previous_config_lines"), dict)
            else current_previous
        )
        sync_result = sync_catalog(codex_home, dry_run=args.dry_run)

        scheduler_plan: dict[str, Any]
        if args.no_schedule:
            scheduler_plan = {"kind": "none"}
        elif chosen_platform == "macos":
            scheduler_plan = {
                "kind": "launchd",
                "label": MAC_LABEL,
                "path": str(mac_launch_agent_path()),
                "watch_path": str(source),
                "interval_seconds": 180,
            }
        else:
            scheduler_plan = {
                "kind": "task-scheduler",
                "name": WINDOWS_TASK_NAME,
                "interval_minutes": 3,
                "action": windows_task_action(Path(sys.executable), installed_sync, codex_home, log_path),
            }

        if args.dry_run:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "dry_run": True,
                        "platform": chosen_platform,
                        "codex_home": str(codex_home),
                        "runtime": str(runtime),
                        "config_changed": patched_config != original_config,
                        "sync": sync_result,
                        "scheduler": scheduler_plan,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        copy_runtime_files(binary_dir)
        backup = None
        if patched_config != original_config:
            backup = write_config_backup(codex_home, original_config)
            atomic_write_text(config_file, patched_config)

        state = {
            "version": VERSION,
            "installed_at": utc_now(),
            "platform": chosen_platform,
            "codex_home": str(codex_home),
            "runtime": str(runtime),
            "source": str(source),
            "output": str(output),
            "config": str(config_file),
            "config_backup": str(backup) if backup else existing_state.get("config_backup") if existing_state else None,
            "previous_config_lines": previous_lines,
            "managed_config_lines": managed,
            "scheduler": scheduler_plan,
        }
        save_install_state(codex_home, state)

        try:
            if args.no_schedule:
                scheduler = scheduler_plan
            elif chosen_platform == "macos":
                scheduler = install_macos_scheduler(Path(sys.executable), installed_sync, codex_home, log_path)
            else:
                scheduler = install_windows_scheduler(Path(sys.executable), installed_sync, codex_home, log_path)
        except SyncError as exc:
            state["scheduler_error"] = str(exc)
            save_install_state(codex_home, state)
            raise

        state["scheduler"] = scheduler
        state.pop("scheduler_error", None)
        save_install_state(codex_home, state)
        print(
            json.dumps(
                {
                    "ok": True,
                    "installed": True,
                    "restart_required": True,
                    "platform": chosen_platform,
                    "codex_home": str(codex_home),
                    "sync": sync_result,
                    "scheduler": scheduler,
                    "state": str(install_state_path(codex_home)),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (OSError, SyncError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
