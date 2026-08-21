#!/usr/bin/env python3
"""Safely reset one project's managed Codex context values."""

from __future__ import annotations

import argparse
import json

from project_context_common import (
    ContextConfigError,
    atomic_write_text,
    load_project_state,
    project_config_path,
    project_state_path,
    resolve_project_root,
    restore_managed_config_text,
    write_project_backup,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, help="Absolute target project root")
    parser.add_argument("--dry-run", action="store_true", help="Report the plan without writing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        project_root = resolve_project_root(args.project_root)
        state = load_project_state(project_root)
        if not state:
            raise ContextConfigError("Project context state is missing; refusing to guess rollback values")
        if state.get("project_root") != str(project_root):
            raise ContextConfigError("Project install state belongs to a different project")
        previous = state.get("previous_config_lines")
        managed = state.get("managed_config_lines")
        if not isinstance(previous, dict) or not isinstance(managed, dict):
            raise ContextConfigError("Project install state lacks safe rollback data")

        config_file = project_config_path(project_root)
        if not config_file.exists():
            raise ContextConfigError(f"Project config is missing: {config_file}")
        current = config_file.read_text(encoding="utf-8")
        restored, skipped = restore_managed_config_text(current, previous, managed)
        config_existed_before = bool(state.get("config_existed_before"))
        remove_config = not config_existed_before and not restored.strip()
        changed = remove_config or restored != current
        report = {
            "ok": True,
            "dry_run": bool(args.dry_run),
            "project_root": str(project_root),
            "project_config": str(config_file),
            "config_changed": changed,
            "config_will_be_removed": remove_config,
            "skipped_user_modified_keys": skipped,
            "touches_user_config": False,
            "app_restart_required": changed,
            "reopen_same_conversation_required": changed,
            "new_task_required": False,
        }
        if args.dry_run:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        backup = None
        if changed:
            backup = write_project_backup(project_root, current, "before-reset")
            if remove_config:
                config_file.unlink()
            else:
                atomic_write_text(config_file, restored)
        state_file = project_state_path(project_root)
        if state_file.exists():
            state_file.unlink()
        report.update({"reset": True, "backup": str(backup) if backup else None})
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeError, ContextConfigError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
