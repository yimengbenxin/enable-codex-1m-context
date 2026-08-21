# Codex Project Context v2.1.0

Released: 2026-08-21

## Why this release exists

This update moves the repository's active skill from global model-catalog synchronization to explicit project-local context management. It is designed for users who want different trusted Codex projects to use different context budgets without changing global Codex configuration.

## Shipped capabilities

- Set or switch one project to a context window from 64k through 1m.
- Accept integer, `k`, and `m` token notation.
- Default automatic compaction to 90% of the selected context, or accept an explicit lower threshold.
- Preview changes with `--dry-run`.
- Inspect project state with strict static checks.
- Reset only still-managed values while preserving later user edits.
- Store backups and rollback state inside the target project.
- Refuse broad or unsafe project roots and invalid configuration values.

## Breaking scope change

v2.1.0 does not read or write global `~/.codex/config.toml`, `models_cache.json`, scheduler definitions, or authentication files. Existing v1.0.1 users should treat this as a project-scoped successor, not an in-place global synchronizer.

## Installation and usage

Extract `codex-project-context-v2.1.0.zip`, install the enclosed directory as a Codex skill, then preview and apply a project-local change:

```bash
python3 scripts/set_project_context.py \
  --project-root "/absolute/path/to/project" \
  --context 1m \
  --auto-compact 900k \
  --dry-run
python3 scripts/set_project_context.py \
  --project-root "/absolute/path/to/project" \
  --context 1m \
  --auto-compact 900k
```

Restart Codex Desktop and reopen the same existing conversation in the trusted project before checking runtime behavior.

## Known limits

- Independent skill; not an official OpenAI package.
- Project trust and runtime activation require Codex Desktop actions.
- Real Windows Codex Desktop runtime was not executed for this release; path and configuration behavior are covered by isolated tests.
- No API, telemetry, scheduler, or global configuration access is included.

## Verification performed

```bash
python3 scripts/self_test.py
python3 -m compileall -q scripts
```

Observed result: 6 isolated tests passed and compilation completed successfully. The release publisher also rebuilds the ZIP and verifies downloaded remote asset hashes.

## Assets

- `codex-project-context-v2.1.0.zip`: portable project-context Codex skill.
- `v2.1.0-SHA256.txt`: publisher-generated checksum manifest.
