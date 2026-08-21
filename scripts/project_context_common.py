#!/usr/bin/env python3
"""Deterministic helpers for project-scoped Codex 1M context configuration."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Optional, Union


VERSION = "2.1.0"
MODEL_SLUG = "gpt-5.6-sol"
MIN_CONTEXT_WINDOW = 64_000
MAX_CONTEXT_WINDOW = 1_000_000
DEFAULT_AUTO_COMPACT_PERCENT = 90
STATE_NAME = "codex-project-context-state.json"
BACKUP_DIRNAME = "codex-project-context-backups"
PROJECT_KEYS = (
    "model",
    "model_context_window",
    "model_auto_compact_token_limit",
)

_ASSIGNMENT_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=")
_SECTION_RE = re.compile(r"^\s*\[\[?")


class ContextConfigError(RuntimeError):
    """Raised when a requested configuration change cannot be applied safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_project_root(
    explicit: Optional[Union[str, os.PathLike[str]]] = None,
) -> Path:
    candidate = Path(explicit).expanduser() if explicit else Path.cwd()
    candidate = candidate.resolve()
    if not candidate.exists():
        raise ContextConfigError(f"Project root does not exist: {candidate}")
    if not candidate.is_dir():
        raise ContextConfigError(f"Project root is not a directory: {candidate}")
    if candidate == Path(candidate.anchor):
        raise ContextConfigError(f"Refusing to use filesystem root as a project: {candidate}")
    if candidate == Path.home().resolve():
        raise ContextConfigError(f"Refusing to use the home directory as a project: {candidate}")
    if candidate.name == ".codex":
        raise ContextConfigError("Pass the project root, not its .codex directory")
    return candidate


def project_codex_dir(project_root: Path) -> Path:
    return project_root / ".codex"


def project_config_path(project_root: Path) -> Path:
    return project_codex_dir(project_root) / "config.toml"


def project_state_path(project_root: Path) -> Path:
    return project_codex_dir(project_root) / STATE_NAME


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
        raise ContextConfigError(f"Missing required file: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContextConfigError(f"Cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContextConfigError(f"Expected a JSON object in {path}")
    return value


def _split_config(text: str) -> tuple[list[str], list[str], str]:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    section_index = next((index for index, line in enumerate(lines) if _SECTION_RE.match(line)), len(lines))
    return lines[:section_index], lines[section_index:], newline


def line_key(line: str) -> Optional[str]:
    match = _ASSIGNMENT_RE.match(line)
    return match.group(1) if match else None


def extract_top_level_config_lines(
    text: str,
    keys: Iterable[str] = PROJECT_KEYS,
) -> dict[str, Optional[str]]:
    selected = tuple(keys)
    allowed = set(selected)
    found: dict[str, Optional[str]] = {key: None for key in selected}
    top, _, _ = _split_config(text)
    for line in top:
        key = line_key(line)
        if key in allowed and found[key] is None:
            found[key] = line
    return found


def count_top_level_config_keys(text: str, keys: Iterable[str] = PROJECT_KEYS) -> dict[str, int]:
    selected = tuple(keys)
    allowed = set(selected)
    counts = {key: 0 for key in selected}
    top, _, _ = _split_config(text)
    for line in top:
        key = line_key(line)
        if key in allowed:
            counts[key] += 1
    return counts


def parse_token_value(value: Union[str, int]) -> int:
    if isinstance(value, bool):
        raise ContextConfigError("Token value must be a number, not a boolean")
    if isinstance(value, int):
        result = value
    else:
        normalized = str(value).strip().lower().replace("_", "").replace(",", "")
        multiplier = 1
        if normalized.endswith("k"):
            normalized = normalized[:-1]
            multiplier = 1_000
        elif normalized.endswith("m"):
            normalized = normalized[:-1]
            multiplier = 1_000_000
        try:
            decimal_value = Decimal(normalized)
        except InvalidOperation as exc:
            raise ContextConfigError(f"Invalid token value: {value}") from exc
        expanded = decimal_value * multiplier
        if expanded != expanded.to_integral_value():
            raise ContextConfigError(f"Token value must resolve to a whole number: {value}")
        result = int(expanded)
    if result <= 0:
        raise ContextConfigError(f"Token value must be positive: {value}")
    return result


def normalize_context_settings(
    context_value: Union[str, int],
    auto_compact_value: Optional[Union[str, int]] = None,
) -> tuple[int, int]:
    context_window = parse_token_value(context_value)
    if context_window < MIN_CONTEXT_WINDOW or context_window > MAX_CONTEXT_WINDOW:
        raise ContextConfigError(
            f"Context window must be between {MIN_CONTEXT_WINDOW} and {MAX_CONTEXT_WINDOW} tokens"
        )
    auto_compact = (
        parse_token_value(auto_compact_value)
        if auto_compact_value is not None
        else context_window * DEFAULT_AUTO_COMPACT_PERCENT // 100
    )
    if auto_compact >= context_window:
        raise ContextConfigError("Auto-compaction threshold must be lower than the context window")
    return context_window, auto_compact


def managed_project_lines(context_window: int, auto_compact_token_limit: int) -> dict[str, str]:
    return {
        "model": f'model = "{MODEL_SLUG}"',
        "model_context_window": f"model_context_window = {context_window}",
        "model_auto_compact_token_limit": (
            f"model_auto_compact_token_limit = {auto_compact_token_limit}"
        ),
    }


def patch_project_config_text(
    text: str,
    context_window: int,
    auto_compact_token_limit: int,
) -> tuple[str, dict[str, Optional[str]], dict[str, str]]:
    top, sections, newline = _split_config(text)
    previous = extract_top_level_config_lines(text)
    managed = managed_project_lines(context_window, auto_compact_token_limit)
    target_keys = set(PROJECT_KEYS)
    retained = [line for line in top if line_key(line) not in target_keys]
    while retained and not retained[0].strip():
        retained.pop(0)

    rebuilt = [managed[key] for key in PROJECT_KEYS]
    if retained:
        rebuilt.extend(["", *retained])
    if sections:
        if rebuilt and rebuilt[-1].strip():
            rebuilt.append("")
        rebuilt.extend(sections)
    return newline.join(rebuilt).rstrip() + newline, previous, managed


def restore_managed_config_text(
    text: str,
    previous: dict[str, Optional[str]],
    managed: dict[str, str],
) -> tuple[str, list[str]]:
    top, sections, newline = _split_config(text)
    managed_keys = set(managed)
    retained: list[str] = []
    restored: list[str] = []
    skipped: list[str] = []

    for line in top:
        key = line_key(line)
        if key not in managed_keys:
            retained.append(line)
            continue
        if line.strip() == str(managed.get(key, "")).strip():
            old_line = previous.get(key)
            if old_line is not None:
                restored.append(old_line)
        else:
            retained.append(line)
            skipped.append(str(key))

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
    result = newline.join(rebuilt).rstrip()
    return (result + newline if result else ""), sorted(set(skipped))


def write_project_backup(project_root: Path, original: str, reason: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = project_codex_dir(project_root) / BACKUP_DIRNAME / f"config.toml.{reason}.{stamp}.bak"
    atomic_write_text(backup, original)
    return backup


def save_project_state(project_root: Path, state: dict[str, Any]) -> None:
    atomic_write_text(
        project_state_path(project_root),
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
    )


def load_project_state(project_root: Path) -> Optional[dict[str, Any]]:
    path = project_state_path(project_root)
    if not path.exists():
        return None
    return load_json(path)
