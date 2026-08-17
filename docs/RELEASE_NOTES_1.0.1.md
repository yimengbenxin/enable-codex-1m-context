# Enable Codex 1M Context v1.0.1

Released: 2026-08-17

## Why this release exists

This first public release packages a deterministic, reversible workaround for Codex Desktop installations whose local GPT-5.6 Sol model catalog reports a lower context maximum than expected.

## Shipped capabilities

- Generates an atomic fixed catalog while preserving all models and all non-target fields.
- Raises only `gpt-5.6-sol.max_context_window` values below 1,000,000.
- Preserves official/local source values of 1,000,000 or higher.
- Installs repeat synchronization through macOS `launchd` or Windows Task Scheduler.
- Supports dry runs, manual-only operation, strict verification, and conservative uninstall.
- Rejects malformed or ambiguous source catalogs without replacing the last known good output.

## Installation and update

Extract `enable-codex-1m-context-v1.0.1.zip`, install the enclosed directory as a Codex skill, then run:

```bash
python3 scripts/install_sync.py --dry-run
python3 scripts/install_sync.py
```

Fully quit and reopen Codex Desktop before runtime verification.

## Known limits

- Independent workaround; not an official OpenAI package.
- Does not modify account entitlements or server-side model behavior.
- Requires Python 3.9+, a local Codex `models_cache.json`, and macOS or Windows.
- Real Windows Task Scheduler installation was not executed during this release's verification; its command and path behavior are covered by isolated tests.

## Verification performed

```bash
python3 scripts/self_test.py
python3 -m compileall -q scripts
```

Observed result: 7 tests passed on macOS; compilation completed successfully. The release publisher also rebuilds the ZIP, audits the public surface, and verifies the downloaded remote asset hashes before publication.

## Assets

- `enable-codex-1m-context-v1.0.1.zip`: portable Codex skill.
- `v1.0.1-SHA256.txt`: publisher-generated checksum manifest.
