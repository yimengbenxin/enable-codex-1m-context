#!/usr/bin/env python3
"""Run isolated tests for the project-scoped Codex context skill."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from project_context_common import (
    ContextConfigError,
    extract_top_level_config_lines,
    normalize_context_settings,
    parse_token_value,
    patch_project_config_text,
    resolve_project_root,
    restore_managed_config_text,
)


SCRIPTS = Path(__file__).resolve().parent


class ProjectContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-project-context-test-")
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.fake_home = self.root / "home"
        self.fake_home.mkdir()
        self.user_config = self.fake_home / ".codex" / "config.toml"
        self.user_config.parent.mkdir()
        self.user_config.write_text('model = "gpt-5.6-luna"\n', encoding="utf-8")
        self.environment = dict(os.environ)
        self.environment["HOME"] = str(self.fake_home)
        self.environment.pop("CODEX_HOME", None)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_script(self, name: str, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *arguments],
            text=True,
            capture_output=True,
            check=False,
            env=self.environment,
        )

    def test_patch_and_restore_preserve_unrelated_project_config(self) -> None:
        original = (
            "# project comment\n"
            'model = "gpt-5.6-luna"\n'
            "notify = [\"example\"]\n\n"
            "[features]\n"
            "hooks = true\n"
        )
        patched, previous, managed = patch_project_config_text(original, 600_000, 540_000)
        found = extract_top_level_config_lines(patched)
        self.assertEqual(found, managed)
        self.assertIn("# project comment", patched)
        self.assertIn("[features]", patched)
        restored, skipped = restore_managed_config_text(patched, previous, managed)
        self.assertFalse(skipped)
        self.assertEqual(extract_top_level_config_lines(restored)["model"], 'model = "gpt-5.6-luna"')

    def test_set_status_reset_is_project_only(self) -> None:
        dry_run = self.run_script(
            "set_project_context.py",
            "--project-root", str(self.project),
            "--context", "600k",
            "--dry-run",
        )
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        self.assertFalse((self.project / ".codex").exists())

        apply_result = self.run_script(
            "set_project_context.py",
            "--project-root", str(self.project),
            "--context", "600k",
        )
        self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
        apply_report = json.loads(apply_result.stdout)
        self.assertTrue(apply_report["app_restart_required"])
        self.assertTrue(apply_report["reopen_same_conversation_required"])
        self.assertFalse(apply_report["new_task_required"])
        project_config = self.project / ".codex" / "config.toml"
        self.assertTrue(project_config.exists())
        project_text = project_config.read_text(encoding="utf-8")
        self.assertIn("model_context_window = 600000", project_text)
        self.assertIn("model_auto_compact_token_limit = 540000", project_text)
        self.assertEqual(self.user_config.read_text(encoding="utf-8"), 'model = "gpt-5.6-luna"\n')

        status = self.run_script(
            "status_project_context.py", "--project-root", str(self.project), "--strict"
        )
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        status_report = json.loads(status.stdout)
        self.assertTrue(status_report["ok"])
        self.assertEqual(status_report["context_window"], "600000")
        self.assertTrue(status_report["reopen_same_conversation"])
        self.assertFalse(status_report["new_task_required"])

        switch = self.run_script(
            "set_project_context.py",
            "--project-root", str(self.project),
            "--context", "1m",
            "--auto-compact", "900k",
        )
        self.assertEqual(switch.returncode, 0, switch.stderr)
        switched_text = project_config.read_text(encoding="utf-8")
        self.assertIn("model_context_window = 1000000", switched_text)
        self.assertIn("model_auto_compact_token_limit = 900000", switched_text)

        reset_dry = self.run_script(
            "reset_project_context.py", "--project-root", str(self.project), "--dry-run"
        )
        self.assertEqual(reset_dry.returncode, 0, reset_dry.stderr)
        self.assertTrue(project_config.exists())

        reset = self.run_script("reset_project_context.py", "--project-root", str(self.project))
        self.assertEqual(reset.returncode, 0, reset.stderr)
        self.assertFalse(project_config.exists())
        self.assertEqual(self.user_config.read_text(encoding="utf-8"), 'model = "gpt-5.6-luna"\n')

    def test_reset_preserves_user_modified_managed_key(self) -> None:
        apply_result = self.run_script(
            "set_project_context.py",
            "--project-root", str(self.project),
            "--context", "600k",
        )
        self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
        project_config = self.project / ".codex" / "config.toml"
        changed = project_config.read_text(encoding="utf-8").replace(
            'model = "gpt-5.6-sol"', 'model = "gpt-5.6-terra"', 1
        )
        project_config.write_text(changed, encoding="utf-8")
        reset = self.run_script("reset_project_context.py", "--project-root", str(self.project))
        self.assertEqual(reset.returncode, 0, reset.stderr)
        report = json.loads(reset.stdout)
        self.assertIn("model", report["skipped_user_modified_keys"])
        self.assertIn('model = "gpt-5.6-terra"', project_config.read_text(encoding="utf-8"))

    def test_token_parsing_and_bounds(self) -> None:
        self.assertEqual(parse_token_value("600k"), 600_000)
        self.assertEqual(parse_token_value("0.6m"), 600_000)
        self.assertEqual(normalize_context_settings("600k"), (600_000, 540_000))
        self.assertEqual(normalize_context_settings("1m", "900k"), (1_000_000, 900_000))
        with self.assertRaises(ContextConfigError):
            normalize_context_settings("2m")
        with self.assertRaises(ContextConfigError):
            normalize_context_settings("600k", "600k")

    def test_runtime_scripts_do_not_reference_global_codex_config(self) -> None:
        runtime_files = [
            SCRIPTS / "project_context_common.py",
            SCRIPTS / "set_project_context.py",
            SCRIPTS / "status_project_context.py",
            SCRIPTS / "reset_project_context.py",
        ]
        forbidden = ("CODEX_HOME", "models_cache.json", "model-catalog-fixed.json")
        for runtime_file in runtime_files:
            source = runtime_file.read_text(encoding="utf-8")
            for marker in forbidden:
                self.assertNotIn(marker, source, f"{marker} found in {runtime_file}")

    def test_broad_project_roots_are_rejected(self) -> None:
        with self.assertRaises(ContextConfigError):
            resolve_project_root(Path(self.project.anchor))


if __name__ == "__main__":
    unittest.main(verbosity=2)
