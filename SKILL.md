---
name: enable-codex-1m-context
description: Use when a user wants to enable, install, synchronize, repair, verify, or completely uninstall a temporary 1M-token Codex context workaround for GPT-5.6 Sol on macOS or Windows, especially when Desktop shows 258K or 828K, model catalog values drift, or the setup must be shared across computers.
---

# Enable Codex 1M Context

Treat this as a temporary compatibility workaround for a locally observed model-catalog inconsistency. Remove it when the official Sol catalog consistently provides the requested context.

Use the bundled deterministic scripts. Do not generate, rewrite, or personalize their code for each computer.

## Scope and requirements

- Support macOS and Windows Codex Desktop installations with Python 3.9 or newer.
- Resolve Codex home from `--codex-home`, then `CODEX_HOME`, then the current user's `.codex` directory.
- Read only the official local `models_cache.json`; never read authentication files or call private model-catalog endpoints.
- Preserve every model entry and every field inside each model entry. Cache-envelope metadata is not required in the generated model catalog. Override `gpt-5.6-sol.max_context_window` to exactly `1000000` only when the current cloud value is lower; preserve a cloud value of `1000000` or higher unchanged.
- Treat scheduler installation and global `config.toml` edits as authorized only when the user asks to install or enable the workaround. Diagnosis and status requests are read-only.

If Python, `models_cache.json`, or a supported scheduler is unavailable, stop with the exact preflight error. Do not patch the bundled scripts to work around an unsupported environment.

## Locate the bundled scripts

Set `<skill-root>` to the directory containing this `SKILL.md`. Invoke scripts from `<skill-root>/scripts/` with a Python 3.9+ interpreter discovered on the target computer. Never substitute the author's installation path.

## Install

Run a dry-run first:

```text
<python> <skill-root>/scripts/install_sync.py --dry-run
```

Review the reported Codex home, source cache, fixed catalog, platform, and scheduler. Then run:

```text
<python> <skill-root>/scripts/install_sync.py
```

The installer must:

1. Copy fixed runtime scripts to `<codex-home>/sol-context-sync/bin/`.
2. Copy the latest cloud-backed cache and raise only Sol's `max_context_window` to `1000000` when the cloud value is lower.
3. Atomically write `<codex-home>/model-catalog-fixed.json` and retain the last known good file on failure.
4. Back up and minimally patch top-level config values:

```toml
model = "gpt-5.6-sol"
model_context_window = 1000000
model_auto_compact_token_limit = 900000
model_catalog_json = "<resolved absolute fixed-catalog path>"
```

5. Install a non-AI system trigger:
   - macOS: `launchd` watches `models_cache.json` and also checks every 180 seconds.
   - Windows: Task Scheduler runs every 3 minutes.

Use `--no-schedule` only when the user explicitly prefers manual synchronization.

## Synchronize and inspect

Run one deterministic synchronization without reinstalling:

```text
<python> <skill-root>/scripts/sync_catalog.py
```

Check installation state without changes:

```text
<python> <skill-root>/scripts/verify_install.py --strict
```

The synchronizer must copy every current cloud field and every other model unchanged. A malformed cache, missing Sol entry, or duplicate Sol entry must fail without replacing the last known good fixed catalog.

When `official_support_detected` is `true`, leave the cloud Sol entry unchanged and keep monitoring. Do not uninstall or disable synchronization automatically. If a later cloud refresh drops below `1000000`, apply the override again on that sync cycle.

## Activate and verify the model window

`model_catalog_json` is loaded at app startup. After installation or a changed fixed catalog:

1. Fully quit and reopen Codex Desktop.
2. Open the same task or a new task with GPT-5.6 Sol.
3. Send one short message and wait for the reply.
4. Pair the nearest `turn_context.payload.model` with the corresponding `task_started.payload.model_context_window` or `token_count.payload.info.model_context_window` in the same session transcript.

Acceptance requires:

- model `gpt-5.6-sol`;
- fixed `max_context_window` at least `1000000`;
- effective runtime window consistent with the cloud `effective_context_window_percent` value. At 95 percent, expect approximately `950000`, not a literal UI value of one million; keep the configured values `1000000` and `900000` unchanged.
- a completed model reply, not config-file evidence alone.

Do not attribute another model's window to Sol. Do not claim that writing the JSON hot-updates already running tasks.

## Completely uninstall

Only when the user explicitly requests removal, run:

```text
<python> <skill-root>/scripts/uninstall_sync.py --remove-skill
```

The uninstaller must:

1. Remove the macOS launchd job or Windows scheduled task.
2. Restore only config keys that still match installer-managed values; leave user-modified keys untouched and report them.
3. Remove the generated fixed catalog and stable runtime directory.
4. Validate the Skill directory name and required files before deleting the Skill itself.
5. Leave a pre-uninstall config backup under Codex home and require an app restart.

If Windows prevents deletion of the currently executing Skill, report the exact directory for deletion after Codex closes. Do not broaden the deletion target.

## Validate the packaged Skill

Run isolated tests without touching the real Codex home:

```text
<python> <skill-root>/scripts/self_test.py
```

Report platform, resolved Codex home, scheduler type, source and output paths, source and target Sol maxima, expected effective window, restart requirement, same-turn runtime evidence, and whether official support is now detected.

Never trigger uninstall solely because one cloud refresh reports `1000000` or higher; the source may regress on a later refresh.
