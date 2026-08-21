#!/usr/bin/env python3
"""Show and verify one project's Codex context configuration without changing it."""

from __future__ import annotations

import argparse
import json

from project_context_common import (
    ContextConfigError,
    count_top_level_config_keys,
    extract_top_level_config_lines,
    load_project_state,
    project_config_path,
    project_state_path,
    resolve_project_root,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, help="Absolute target project root")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when static checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    failures = []
    checks = {}
    try:
        project_root = resolve_project_root(args.project_root)
        config_file = project_config_path(project_root)
        state = load_project_state(project_root)
        expected = (
            state.get("managed_config_lines")
            if state and isinstance(state.get("managed_config_lines"), dict)
            else None
        )
        if config_file.exists():
            raw = config_file.read_text(encoding="utf-8")
            found = extract_top_level_config_lines(raw)
            counts = count_top_level_config_keys(raw)
            mismatches = [
                key for key, value in (expected or {}).items()
                if (found.get(key) or "").strip() != value.strip()
            ]
            duplicates = [key for key, count in counts.items() if count != 1]
            missing = [key for key, value in found.items() if value is None]
            config_ok = not mismatches and not duplicates and not missing
            checks["project_config"] = {
                "ok": config_ok,
                "path": str(config_file),
                "observed_values": found,
                "mismatched_keys": mismatches,
                "non_singleton_keys": duplicates,
                "missing_keys": missing,
            }
            if not config_ok:
                failures.append("project_config")
        else:
            checks["project_config"] = {"ok": False, "path": str(config_file), "error": "missing"}
            failures.append("project_config")

        state_ok = bool(
            state
            and state.get("project_root") == str(project_root)
            and state.get("project_config") == str(config_file)
            and isinstance(state.get("previous_config_lines"), dict)
            and isinstance(state.get("managed_config_lines"), dict)
        )
        checks["rollback_state"] = {
            "ok": state_ok,
            "path": str(project_state_path(project_root)),
        }
        if not state_ok:
            failures.append("rollback_state")

        checks["project_trust"] = {
            "ok": None,
            "manual_confirmation_required": True,
            "reason": "Codex ignores project .codex layers until the project is trusted",
        }
        result = {
            "ok": not failures,
            "project_root": str(project_root),
            "managed_by_skill": state_ok,
            "context_window": (
                (checks.get("project_config", {}).get("observed_values", {}).get("model_context_window") or "")
                .partition("=")[2]
                .strip()
                or None
            ),
            "auto_compact_token_limit": (
                (checks.get("project_config", {}).get("observed_values", {}).get("model_auto_compact_token_limit") or "")
                .partition("=")[2]
                .strip()
                or None
            ),
            "checks": checks,
            "failures": sorted(set(failures)),
            "runtime_verification_required": True,
            "app_restart_required_after_change": True,
            "reopen_same_conversation": True,
            "new_task_required": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if args.strict and failures else 0
    except (OSError, UnicodeError, ContextConfigError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
