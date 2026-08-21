#!/usr/bin/env python3
"""Build a deterministic release ZIP for this Codex skill."""
from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "codex-project-context"
FIXED_TIMESTAMP = (2026, 8, 21, 0, 0, 0)
INCLUDED_FILES = (
    "SKILL.md",
    "README.md",
    "LICENSE",
    "agents/openai.yaml",
    "scripts/project_context_common.py",
    "scripts/reset_project_context.py",
    "scripts/self_test.py",
    "scripts/set_project_context.py",
    "scripts/status_project_context.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    return parser.parse_args()


def source_version() -> str:
    source = (ROOT / "scripts/project_context_common.py").read_text(encoding="utf-8")
    match = re.search(r'^VERSION = "([^"]+)"$', source, re.MULTILINE)
    if not match:
        raise SystemExit("VERSION not found in scripts/context_sync_common.py")
    return match.group(1)


def main() -> int:
    args = parse_args()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version):
        raise SystemExit("--version must use X.Y.Z format")
    actual_version = source_version()
    if args.version != actual_version:
        raise SystemExit(f"requested version {args.version} does not match source {actual_version}")

    missing = [relative for relative in INCLUDED_FILES if not (ROOT / relative).is_file()]
    if missing:
        raise SystemExit("missing release inputs: " + ", ".join(missing))

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    output = dist / f"{PACKAGE_NAME}-v{args.version}.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in INCLUDED_FILES:
            source = ROOT / relative
            info = zipfile.ZipInfo(f"{PACKAGE_NAME}/{relative}", FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if source.suffix == ".py" else 0o644) << 16
            archive.writestr(info, source.read_bytes())
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
