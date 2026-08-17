#!/usr/bin/env python3
"""Verify the portable Sol context-sync installation without changing it."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
from pathlib import Path

from context_sync_common import (
    MAC_LABEL,
    MODEL_SLUG,
    TARGET_MAX_CONTEXT_WINDOW,
    WINDOWS_TASK_NAME,
    SyncError,
    config_path,
    expected_effective_window,
    extract_top_level_config_lines,
    find_sol_model,
    install_state_path,
    load_install_state,
    load_json,
    managed_config_lines,
    output_catalog_path,
    resolve_codex_home,
    runtime_dir,
    source_catalog_path,
    status_path,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", help="Codex home; defaults to CODEX_HOME or ~/.codex")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when installation checks fail")
    parser.add_argument("--no-scheduler-check", action="store_true")
    return parser.parse_args()


def scheduler_check(state: dict[str, object] | None) -> dict[str, object]:
    if not state:
        return {"ok": False, "reason": "install state is missing"}
    scheduler = state.get("scheduler")
    if not isinstance(scheduler, dict):
        return {"ok": False, "reason": "scheduler state is missing"}
    kind = scheduler.get("kind")
    if kind == "none":
        return {"ok": True, "kind": "none"}
    if kind == "launchd":
        configured_path = scheduler.get("path")
        path = Path(str(configured_path)) if configured_path else Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"
        return {"ok": path.exists(), "kind": kind, "path": str(path)}
    if kind == "task-scheduler":
        executable = shutil.which("schtasks.exe") or shutil.which("schtasks")
        if platform.system().lower() != "windows" or not executable:
            return {"ok": False, "kind": kind, "reason": "Task Scheduler is unavailable"}
        result = subprocess.run(
            [executable, "/Query", "/TN", WINDOWS_TASK_NAME],
            text=True,
            capture_output=True,
            check=False,
        )
        return {"ok": result.returncode == 0, "kind": kind, "name": WINDOWS_TASK_NAME}
    return {"ok": False, "reason": f"unknown scheduler kind: {kind}"}


def main() -> int:
    args = parse_args()
    codex_home = resolve_codex_home(args.codex_home)
    checks: dict[str, object] = {}
    failures: list[str] = []

    try:
        output = output_catalog_path(codex_home)
        sol = find_sol_model(output)
        catalog_value = sol.get("max_context_window")
        catalog_ok = isinstance(catalog_value, int) and catalog_value >= TARGET_MAX_CONTEXT_WINDOW
        checks["catalog"] = {
            "ok": catalog_ok,
            "path": str(output),
            "model": MODEL_SLUG,
            "max_context_window": catalog_value,
            "effective_context_window_percent": sol.get("effective_context_window_percent"),
            "expected_effective_window": expected_effective_window(sol),
        }
        if not catalog_ok:
            failures.append("catalog")
    except (OSError, SyncError) as exc:
        checks["catalog"] = {"ok": False, "error": str(exc)}
        failures.append("catalog")

    config_file = config_path(codex_home)
    if config_file.exists():
        raw = config_file.read_text(encoding="utf-8")
        found = extract_top_level_config_lines(raw)
        expected = managed_config_lines(output_catalog_path(codex_home))
        mismatches = [
            key for key, value in expected.items() if (found.get(key) or "").strip() != value.strip()
        ]
        checks["config"] = {
            "ok": not mismatches,
            "path": str(config_file),
            "mismatched_keys": mismatches,
        }
        if mismatches:
            failures.append("config")
    else:
        checks["config"] = {"ok": False, "error": f"Missing {config_file}"}
        failures.append("config")

    state = load_install_state(codex_home)
    checks["state"] = {"ok": state is not None, "path": str(install_state_path(codex_home))}
    if state is None:
        failures.append("state")

    source = source_catalog_path(codex_home)
    try:
        source_sol = find_sol_model(source)
        source_maximum = source_sol.get("max_context_window")
        checks["source"] = {
            "ok": True,
            "path": str(source),
            "max_context_window": source_maximum,
            "official_support_detected": (
                isinstance(source_maximum, int) and source_maximum >= TARGET_MAX_CONTEXT_WINDOW
            ),
        }
    except (OSError, SyncError) as exc:
        checks["source"] = {"ok": False, "path": str(source), "error": str(exc)}
        failures.append("source")
    runtime_path = runtime_dir(codex_home)
    required_runtime = [
        "context_sync_common.py",
        "sync_catalog.py",
        "verify_install.py",
        "uninstall_sync.py",
    ]
    missing_runtime = [name for name in required_runtime if not (runtime_path / "bin" / name).exists()]
    runtime_exists = runtime_path.exists() and not missing_runtime
    checks["runtime"] = {"ok": runtime_exists, "path": str(runtime_path), "missing": missing_runtime}
    if not runtime_exists:
        failures.append("runtime")
    last_sync_file = status_path(codex_home)
    if last_sync_file.exists():
        try:
            last_sync = load_json(last_sync_file)
            checks["last_sync"] = {
                "ok": bool(last_sync.get("ok")),
                "path": str(last_sync_file),
                "synced_at": last_sync.get("synced_at"),
                "override_applied": last_sync.get("override_applied"),
                "official_support_detected": last_sync.get("official_support_detected"),
            }
        except SyncError as exc:
            checks["last_sync"] = {"ok": False, "path": str(last_sync_file), "error": str(exc)}
    else:
        checks["last_sync"] = {"ok": False, "path": str(last_sync_file)}
    if not checks["last_sync"].get("ok"):
        failures.append("last_sync")

    if not args.no_scheduler_check:
        scheduler = scheduler_check(state)
        checks["scheduler"] = scheduler
        if not scheduler.get("ok"):
            failures.append("scheduler")

    result = {
        "ok": not failures,
        "codex_home": str(codex_home),
        "checks": checks,
        "failures": sorted(set(failures)),
        "restart_required_after_catalog_change": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if args.strict and failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
