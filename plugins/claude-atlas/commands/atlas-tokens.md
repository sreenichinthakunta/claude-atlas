---
description: Show a token-consumption breakdown by model, project, or session — in the terminal, no browser.
argument-hint: "[model|project|session] [--top N]"
allowed-tools: Bash(python3:*)
---

Print the token report in the terminal.

Pick the grouping from `$ARGUMENTS` (default `model`), then run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report.py" --by model
```

- `project` in `$ARGUMENTS` → `--by project`
- `session` in `$ARGUMENTS` → `--by session`
- `--top N` in `$ARGUMENTS` → pass it through

The report already renders its own bars and totals. Show its output, then add
at most two lines of interpretation — for example which model or project
dominates spend, or whether the cache hit rate is carrying the cost down.

Every cost is an estimate computed from `pricing.json`, not a billed amount.
Say so if the user asks what they owe.
