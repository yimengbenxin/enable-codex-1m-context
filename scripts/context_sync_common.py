#!/usr/bin/env python3
"""Shared deterministic helpers for the Codex Sol context catalog sync skill."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "1.0.1"
MODEL_SLUG = "gpt-5.6-sol"
TARGET_MAX_CONTEXT_WINDOW = 1_000_000
MODEL_CONTEXT_WINDOW = 1_000_000
AUTO_COMPACT_TOKEN_LIMIT = 900_000
RUNTIME_DIRNAME = "sol-context-sync"
SOURCE_CATALOG_NAME = "models_cache.json"
OUTPUT_CATALOG_NAME = "model-catalog-fixed.json"
STATUS_NAME = "sync-status.json"
INSTALL_STATE_NAME = "install-state.json"
CONFIG_NAME = "config.toml"
MAC_LABEL = "com.openai.codex-sol-context-sync"
WINDOWS_TASK_NAME = "CodexSolContextSync"
TARGET_KEYS = (
    "model",
    "model_context_window",
    "model_auto_compact_token_limit",
    "model_catalog_json",
)

_KEY_RE = re.compile(
    r"^\s*(model|model_context_window|model_auto_compact_token_limit|model_catalog_json)\s*="
)
_SECTION_RE = re.compile(r"^\s*\[\[?")


class SyncError(RuntimeError):
    """Raised when an input is unsafe to apply."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_codex_home(explicit: str | os.PathLike[str] | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def runtime_dir(codex_home: Path) -> Path:
    return codex_home / RUNTIME_DIRNAME


def source_catalog_path(codex_home: Path) -> Path:
    return codex_home / SOURCE_CATALOG_NAME


def output_catalog_path(codex_home: Path) -> Path:
    return codex_home / OUTPUT_CATALOG_NAME


def config_path(codex_home: Path) -> Path:
    return codex_home / CONFIG_NAME


def status_path(codex_home: Path) -> Path:
    return runtime_dir(codex_home) / STATUS_NAME


def install_state_path(codex_home: Path) -> Path:
    return runtime_dir(codex_home) / INSTALL_STATE_NAME


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary_path, mode)
        except OSError:
            pass
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), mode=mode)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SyncError(f"Missing required file: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"Cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SyncError(f"Expected a JSON object in {path}")
    return value


def build_fixed_catalog(source: dict[str, Any]) -> tuple[dict[str, Any], int, int, bool]:
    models = source.get("models")
    if not isinstance(models, list) or not models:
        raise SyncError("Source catalog must contain a non-empty models array")

    copied_models = json.loads(json.dumps(models, ensure_ascii=False))
    matches = [model for model in copied_models if isinstance(model, dict) and model.get("slug") == MODEL_SLUG]
    if len(matches) != 1:
        raise SyncError(f"Expected exactly one {MODEL_SLUG} entry; found {len(matches)}")

    selected = matches[0]
    previous_value = selected.get("max_context_window")
    if not isinstance(previous_value, int) or previous_value <= 0:
        raise SyncError(f"{MODEL_SLUG}.max_context_window is not a positive integer")
    override_applied = previous_value < TARGET_MAX_CONTEXT_WINDOW
    if override_applied:
        selected["max_context_window"] = TARGET_MAX_CONTEXT_WINDOW
    return {"models": copied_models}, previous_value, selected["max_context_window"], override_applied


def expected_effective_window(model: dict[str, Any]) -> int:
    maximum = model.get("max_context_window")
    percent = model.get("effective_context_window_percent", 95)
    if not isinstance(maximum, int) or not isinstance(percent, int):
        raise SyncError("Model context metadata must use integer values")
    raw_window = min(MODEL_CONTEXT_WINDOW, maximum)
    return raw_window * percent // 100


def sync_catalog(
    codex_home: Path,
    *,
    source_path: Path | None = None,
    output_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    source_path = source_path or source_catalog_path(codex_home)
    output_path = output_path or output_catalog_path(codex_home)
    source_bytes = source_path.read_bytes() if source_path.exists() else b""
    try:
        source = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"Cannot read valid JSON from {source_path}: {exc}") from exc
    if not isinstance(source, dict):
        raise SyncError(f"Expected a JSON object in {source_path}")
    fixed, source_maximum, output_maximum, override_applied = build_fixed_catalog(source)
    fixed_bytes = (json.dumps(fixed, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    current_bytes = output_path.read_bytes() if output_path.exists() else None
    changed = current_bytes != fixed_bytes

    sol = next(model for model in fixed["models"] if model.get("slug") == MODEL_SLUG)
    result = {
        "ok": True,
        "version": VERSION,
        "synced_at": utc_now(),
        "source": str(source_path),
        "output": str(output_path),
        "source_sha256": sha256_bytes(source_bytes),
        "output_sha256": sha256_bytes(fixed_bytes),
        "source_max_context_window": source_maximum,
        "minimum_target_max_context_window": TARGET_MAX_CONTEXT_WINDOW,
        "output_max_context_window": output_maximum,
        "override_applied": override_applied,
        "official_support_detected": source_maximum >= TARGET_MAX_CONTEXT_WINDOW,
        "effective_context_window_percent": sol.get("effective_context_window_percent"),
        "expected_effective_window": expected_effective_window(sol),
        "changed": changed,
        "dry_run": dry_run,
    }

    if not dry_run:
        if changed:
            atomic_write_bytes(output_path, fixed_bytes)
        atomic_write_text(status_path(codex_home), json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def managed_config_lines(output_path: Path) -> dict[str, str]:
    return {
        "model": f'model = "{MODEL_SLUG}"',
        "model_context_window": f"model_context_window = {MODEL_CONTEXT_WINDOW}",
        "model_auto_compact_token_limit": (
            f"model_auto_compact_token_limit = {AUTO_COMPACT_TOKEN_LIMIT}"
        ),
        "model_catalog_json": f"model_catalog_json = {json.dumps(str(output_path), ensure_ascii=False)}",
    }


def _split_config(text: str) -> tuple[list[str], list[str], str]:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    section_index = next((index for index, line in enumerate(lines) if _SECTION_RE.match(line)), len(lines))
    return lines[:section_index], lines[section_index:], newline


def extract_top_level_config_lines(text: str) -> dict[str, str | None]:
    top, _, _ = _split_config(text)
    found: dict[str, str | None] = {key: None for key in TARGET_KEYS}
    for line in top:
        match = _KEY_RE.match(line)
        if match and found[match.group(1)] is None:
            found[match.group(1)] = line
    return found


def patch_config_text(text: str, output_path: Path) -> tuple[str, dict[str, str | None], dict[str, str]]:
    top, sections, newline = _split_config(text)
    previous = extract_top_level_config_lines(text)
    managed = managed_config_lines(output_path)
    retained = [line for line in top if not _KEY_RE.match(line)]
    while retained and not retained[0].strip():
        retained.pop(0)

    rebuilt = [managed[key] for key in TARGET_KEYS]
    if retained:
        rebuilt.extend(["", *retained])
    if sections:
        if rebuilt and rebuilt[-1].strip():
            rebuilt.append("")
        rebuilt.extend(sections)
    return newline.join(rebuilt).rstrip() + newline, previous, managed


def restore_config_text(
    text: str,
    previous: dict[str, str | None],
    managed: dict[str, str],
) -> tuple[str, list[str]]:
    top, sections, newline = _split_config(text)
    retained: list[str] = []
    restored: list[str] = []
    skipped: list[str] = []

    for line in top:
        match = _KEY_RE.match(line)
        if not match:
            retained.append(line)
            continue
        key = match.group(1)
        if line.strip() == managed.get(key, "").strip():
            old_line = previous.get(key)
            if old_line is not None:
                restored.append(old_line)
        else:
            retained.append(line)
            skipped.append(key)

    while retained and not retained[0].strip():
        retained.pop(0)
    rebuilt = restored[:]
    if restored and retained:
        rebuilt.append("")
    rebuilt.extend(retained)
    if sections:
        if rebuilt and rebuilt[-1].strip():
            rebuilt.append("")
        rebuilt.extend(sections)
    return newline.join(rebuilt).rstrip() + newline, sorted(set(skipped))


def write_config_backup(codex_home: Path, original: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = runtime_dir(codex_home) / "backups" / f"config.toml.{stamp}.bak"
    atomic_write_text(backup, original)
    return backup


def save_install_state(codex_home: Path, state: dict[str, Any]) -> None:
    atomic_write_text(
        install_state_path(codex_home),
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
    )


def load_install_state(codex_home: Path) -> dict[str, Any] | None:
    path = install_state_path(codex_home)
    if not path.exists():
        return None
    return load_json(path)


def find_sol_model(path: Path) -> dict[str, Any]:
    value = load_json(path)
    models = value.get("models")
    if not isinstance(models, list):
        raise SyncError(f"No models array in {path}")
    matches = [model for model in models if isinstance(model, dict) and model.get("slug") == MODEL_SLUG]
    if len(matches) != 1:
        raise SyncError(f"Expected exactly one {MODEL_SLUG} entry in {path}")
    return matches[0]
