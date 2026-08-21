#!/usr/bin/env python3
"""Set or switch one project's Codex context window."""

from __future__ import annotations

import argparse
import json
import sys

from project_context_common import (
    ContextConfigError,
    VERSION,
    atomic_write_text,
    load_project_state,
    normalize_context_settings,
    patch_project_config_text,
    project_config_path,
    project_state_path,
    resolve_project_root,
    save_project_state,
    utc_now,
    write_project_backup,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, help="Absolute target project root")
    parser.add_argument("--context", required=True, help="Context window, such as 258k, 600k, or 1m")
    parser.add_argument(
        "--auto-compact",
        help="Automatic compaction threshold; defaults to 90 percent of context",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report the plan without writing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if sys.version_info < (3, 9):
        print(json.dumps({"ok": False, "error": "Python 3.9 or newer is required"}))
        return 2

    try:
        project_root = resolve_project_root(args.project_root)
        context_window, auto_compact = normalize_context_settings(args.context, args.auto_compact)
        config_file = project_config_path(project_root)
        config_existed = config_file.exists()
        original = config_file.read_text(encoding="utf-8") if config_existed else ""
        patched, current_previous, managed = patch_project_config_text(
            original,
            context_window,
            auto_compact,
        )
        existing_state = load_project_state(project_root)
        if existing_state and existing_state.get("project_root") != str(project_root):
            raise ContextConfigError("Existing state belongs to a different project")
        previous = (
            existing_state.get("previous_config_lines")
            if existing_state and isinstance(existing_state.get("previous_config_lines"), dict)
            else current_previous
        )
        existed_before = (
            bool(existing_state.get("config_existed_before"))
            if existing_state
            else config_existed
        )
        changed = patched != original
        report = {
            "ok": True,
            "version": VERSION,
            "dry_run": bool(args.dry_run),
            "project_root": str(project_root),
            "project_config": str(config_file),
            "context_window": context_window,
            "auto_compact_token_limit": auto_compact,
            "config_changed": changed,
            "managed_values": managed,
            "touches_user_config": False,
            "app_restart_required": changed,
            "reopen_same_conversation_required": changed,
            "new_task_required": False,
            "project_must_be_trusted": True,
        }
        if args.dry_run:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        backup = None
        if changed:
            backup = write_project_backup(project_root, original, "before-set")
            atomic_write_text(config_file, patched)
        state = {
            "version": VERSION,
            "installed_at": (
                existing_state.get("installed_at") if existing_state else utc_now()
            ),
            "updated_at": utc_now(),
            "project_root": str(project_root),
            "project_config": str(config_file),
            "config_existed_before": existed_before,
            "config_backup": (
                str(backup)
                if backup
                else existing_state.get("config_backup") if existing_state else None
            ),
            "previous_config_lines": previous,
            "managed_config_lines": managed,
        }
        try:
            save_project_state(project_root, state)
        except Exception:
            if changed:
                if config_existed:
                    atomic_write_text(config_file, original)
                elif config_file.exists():
                    config_file.unlink()
            raise

        report.update({"applied": True, "state": str(project_state_path(project_root))})
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeError, ContextConfigError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
