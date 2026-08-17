#!/usr/bin/env python3
"""Copy the latest Codex model cache and override only Sol's max context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from context_sync_common import SyncError, resolve_codex_home, sync_catalog, utc_now


def append_log(path: Path | None, record: dict[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", help="Codex home directory; defaults to CODEX_HOME or ~/.codex")
    parser.add_argument("--source", help="Override the source models_cache.json path")
    parser.add_argument("--output", help="Override the fixed catalog output path")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without writing")
    parser.add_argument("--quiet", action="store_true", help="Suppress successful stdout output")
    parser.add_argument("--log-file", help="Append one JSON record per run")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    codex_home = resolve_codex_home(args.codex_home)
    log_path = Path(args.log_file).expanduser().resolve() if args.log_file else None
    try:
        result = sync_catalog(
            codex_home,
            source_path=Path(args.source).expanduser().resolve() if args.source else None,
            output_path=Path(args.output).expanduser().resolve() if args.output else None,
            dry_run=args.dry_run,
        )
    except (OSError, SyncError) as exc:
        result = {"ok": False, "synced_at": utc_now(), "error": str(exc)}
        append_log(log_path, result)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 2

    append_log(log_path, result)
    if not args.quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
