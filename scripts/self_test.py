#!/usr/bin/env python3
"""Run isolated portability tests without touching the real Codex configuration."""

from __future__ import annotations

import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from context_sync_common import (
    SyncError,
    TARGET_MAX_CONTEXT_WINDOW,
    extract_top_level_config_lines,
    managed_config_lines,
    patch_config_text,
    restore_config_text,
    sync_catalog,
)
from install_sync import mac_launch_agent_payload, windows_task_action


class PortableContextSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sol-context-sync-test-")
        self.codex_home = Path(self.temporary.name) / ".codex"
        self.codex_home.mkdir(parents=True)
        self.source = self.codex_home / "models_cache.json"
        self.source.write_text(
            json.dumps(
                {
                    "etag": "test-etag",
                    "models": [
                        {
                            "slug": "gpt-5.6-sol",
                            "context_window": 272000,
                            "max_context_window": 272000,
                            "effective_context_window_percent": 95,
                            "description": "keep this field",
                        },
                        {
                            "slug": "gpt-5.6-luna",
                            "context_window": 272000,
                            "max_context_window": 872000,
                            "effective_context_window_percent": 95,
                        },
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_sync_changes_only_sol_maximum(self) -> None:
        result = sync_catalog(self.codex_home)
        output = json.loads((self.codex_home / "model-catalog-fixed.json").read_text(encoding="utf-8"))
        self.assertEqual(list(output), ["models"])
        sol = next(model for model in output["models"] if model["slug"] == "gpt-5.6-sol")
        luna = next(model for model in output["models"] if model["slug"] == "gpt-5.6-luna")
        self.assertEqual(sol["max_context_window"], TARGET_MAX_CONTEXT_WINDOW)
        self.assertEqual(sol["description"], "keep this field")
        self.assertEqual(luna["max_context_window"], 872000)
        self.assertEqual(result["expected_effective_window"], 950000)
        self.assertTrue(result["override_applied"])
        self.assertFalse(result["official_support_detected"])

    def test_native_one_million_is_preserved_and_later_drop_is_overridden(self) -> None:
        source = json.loads(self.source.read_text(encoding="utf-8"))
        sol = next(model for model in source["models"] if model["slug"] == "gpt-5.6-sol")
        sol["max_context_window"] = 1_050_000
        self.source.write_text(json.dumps(source), encoding="utf-8")
        native_result = sync_catalog(self.codex_home)
        native_output = json.loads((self.codex_home / "model-catalog-fixed.json").read_text(encoding="utf-8"))
        native_sol = next(model for model in native_output["models"] if model["slug"] == "gpt-5.6-sol")
        self.assertEqual(native_sol["max_context_window"], 1_050_000)
        self.assertFalse(native_result["override_applied"])
        self.assertTrue(native_result["official_support_detected"])

        sol["max_context_window"] = 272000
        self.source.write_text(json.dumps(source), encoding="utf-8")
        fallback_result = sync_catalog(self.codex_home)
        fallback_output = json.loads((self.codex_home / "model-catalog-fixed.json").read_text(encoding="utf-8"))
        fallback_sol = next(model for model in fallback_output["models"] if model["slug"] == "gpt-5.6-sol")
        self.assertEqual(fallback_sol["max_context_window"], TARGET_MAX_CONTEXT_WINDOW)
        self.assertTrue(fallback_result["override_applied"])

    def test_config_patch_and_safe_restore(self) -> None:
        original = (
            "# keep this comment\n"
            'model = "gpt-5.6-luna"\n'
            "model_context_window = 500000\n"
            "notify = [\"example\"]\n\n"
            "[features]\n"
            "hooks = true\n"
        )
        output_path = self.codex_home / "model-catalog-fixed.json"
        patched, previous, managed = patch_config_text(original, output_path)
        found = extract_top_level_config_lines(patched)
        for key, expected in managed.items():
            self.assertEqual(found[key], expected)
            self.assertEqual(patched.count(f"{key} ="), 1)
        self.assertIn("# keep this comment", patched)
        self.assertIn("[features]", patched)

        restored, skipped = restore_config_text(patched, previous, managed)
        self.assertFalse(skipped)
        restored_lines = extract_top_level_config_lines(restored)
        self.assertEqual(restored_lines["model"], 'model = "gpt-5.6-luna"')
        self.assertEqual(restored_lines["model_context_window"], "model_context_window = 500000")
        self.assertIsNone(restored_lines["model_catalog_json"])

        user_modified = patched.replace('model = "gpt-5.6-sol"', 'model = "gpt-5.6-terra"', 1)
        restored_modified, skipped_modified = restore_config_text(user_modified, previous, managed)
        self.assertIn("model", skipped_modified)
        self.assertIn('model = "gpt-5.6-terra"', restored_modified)
        self.assertNotIn('model = "gpt-5.6-luna"', restored_modified)

    def test_invalid_source_preserves_last_known_good_output(self) -> None:
        sync_catalog(self.codex_home)
        output_path = self.codex_home / "model-catalog-fixed.json"
        original_output = output_path.read_bytes()
        self.source.write_text('{"models": []}', encoding="utf-8")
        with self.assertRaises(SyncError):
            sync_catalog(self.codex_home)
        self.assertEqual(output_path.read_bytes(), original_output)

    def test_windows_paths_are_toml_escaped(self) -> None:
        windows_path = Path(r"C:\Codex Data\.codex\model-catalog-fixed.json")
        line = managed_config_lines(windows_path)["model_catalog_json"]
        self.assertIn(r"C:\\Codex Data", line)

    def test_scheduler_payloads_use_resolved_paths(self) -> None:
        python_path = Path("/runtime/python3")
        sync_script = Path("/stable path/sync_catalog.py")
        log_path = self.codex_home / "sol-context-sync" / "sync.log"
        payload = mac_launch_agent_payload(python_path, sync_script, self.codex_home, log_path)
        encoded = plistlib.dumps(payload)
        decoded = plistlib.loads(encoded)
        self.assertEqual(decoded["StartInterval"], 180)
        self.assertEqual(decoded["WatchPaths"], [str(self.source)])
        action = windows_task_action(python_path, sync_script, self.codex_home, log_path)
        self.assertIn("sync_catalog.py", action)
        self.assertIn("--codex-home", action)

    def test_installer_dry_runs_for_both_platforms(self) -> None:
        installer = Path(__file__).resolve().parent / "install_sync.py"
        for target in ("macos", "windows"):
            result = subprocess.run(
                [
                    sys.executable,
                    str(installer),
                    "--codex-home",
                    str(self.codex_home),
                    "--platform",
                    target,
                    "--dry-run",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["ok"])
            self.assertEqual(report["platform"], target)
        self.assertFalse((self.codex_home / "model-catalog-fixed.json").exists())
        self.assertFalse((self.codex_home / "sol-context-sync").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
