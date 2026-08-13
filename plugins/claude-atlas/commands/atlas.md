---
description: Build and open the Claude Atlas dashboard — folder navigation for chats and code projects with a right-side token panel.
argument-hint: "[--no-tree] [--no-open]"
allowed-tools: Bash(python3:*)
---

Build the Claude Atlas dashboard and open it in the browser.

Run exactly this, adapting only for the flags in `$ARGUMENTS`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard.py" --open
```

Flag handling:
- `--no-tree` in `$ARGUMENTS` → add `--no-tree` (skips the filesystem walk; much faster on large repos)
- `--no-open` in `$ARGUMENTS` → drop `--open` and just report the output path

The dashboard writes to `~/.claude/atlas/dashboard.html` and is fully
self-contained — no network access, safe to move or share.

After it runs, report back to the user in two or three lines:
- the output path
- total sessions, projects, tokens, and the estimated cost
- one genuinely notable thing from the scan output (for example, if cache
  reads dominate token count, say so — it usually means the raw token
  number looks alarming while the actual cost is much lower)

Do not re-summarize the whole dashboard; the user is about to look at it.
