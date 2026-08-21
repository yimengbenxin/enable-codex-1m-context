---
name: codex-project-context
description: View, set, switch, or reset the GPT-5.6 Sol context window for one trusted Codex project. Use when the user asks to change the current project's context to values such as 258k, 600k, or 1m without reading or changing global Codex configuration.
---

# Manage Codex Context Per Project

Provide a natural-language control surface backed by deterministic local scripts.
Apply context settings only through the target project's `.codex/config.toml`.
Never read or write `~/.codex/config.toml`, read or patch `models_cache.json`,
generate a replacement model catalog, install a scheduler, or perform global
migration or cleanup.

## Interpret requests

- “把当前项目切到 600k” means set the context window to `600000` and set
  automatic compaction to 90 percent (`540000`) unless the user provides a
  different compaction threshold.
- “切到 1m，900k 压缩” means context `1000000`, compaction `900000`.
- “查看当前项目上下文” is read-only status.
- “恢复默认” or “移除项目覆盖” means safely reset this project's managed
  values to their pre-install state.

Supported context values are `64k` through `1m`. Accept integer tokens or `k` /
`m` suffixes. Reject a compaction threshold that is not lower than the context
window.

## Resolve scope

- Resolve the exact target project root before any write.
- Pass its absolute path with `--project-root` on every command.
- Project configuration is loaded only for trusted projects. If the project is
  untrusted, explain that Codex will ignore its `.codex/` layer.
- A direct user command to switch or reset the current project authorizes that
  reversible project-local change. Do not add an extra confirmation unless the
  project is ambiguous.
- Preserve unrelated project configuration and comments.

## Set or switch context

For an explicit request such as “把当前项目切到 600k” run:

```text
<python> <skill-root>/scripts/set_project_context.py --project-root "<absolute-project-root>" --context 600k
```

When the user supplies an explicit threshold:

```text
<python> <skill-root>/scripts/set_project_context.py --project-root "<absolute-project-root>" --context 1m --auto-compact 900k
```

Use `--dry-run` for ambiguous scope, review, or diagnosis. The setter changes
only `<project-root>/.codex/config.toml`, maintains one rollback state across
repeated switches, and stores backups inside the same project `.codex/`
directory.

## Status

```text
<python> <skill-root>/scripts/status_project_context.py --project-root "<absolute-project-root>"
```

Use `--strict` when validating the package or installation. Static acceptance
requires exactly one project-level `model`, `model_context_window`, and
`model_auto_compact_token_limit` plus valid project-local rollback state.

## Reset the project override

```text
<python> <skill-root>/scripts/reset_project_context.py --project-root "<absolute-project-root>"
```

The resetter restores only values still matching the most recent managed
settings. It preserves later user edits and retains backups under the project
`.codex/` directory.

## Activation and runtime verification

Changing a project config does not resize an already-running task. After a set,
switch, or reset:

1. Fully restart Codex.
2. Reopen the same existing conversation in the trusted target project; do not
   create a new task merely to activate the change.
3. Confirm the active model is `gpt-5.6-sol` and runtime context evidence is
   consistent with the configured budget.

The project override applies to conversations in that project when they are
loaded or resumed; it is not a hot per-thread update and does not affect global
defaults. Increasing the window does not reconstruct detail lost in an earlier
compaction. Do not claim runtime activation from config-file evidence alone.

## Validate the packaged skill

```text
<python> <skill-root>/scripts/self_test.py
```
