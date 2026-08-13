---
description: Show the folder structure of a Claude code project alongside its chat sessions.
argument-hint: "[project name or path fragment]"
allowed-tools: Bash(python3:*)
---

Show the folder structure and session list for a project.

Run the collector and filter to the project matching `$ARGUMENTS` (match
case-insensitively against both the project name and its path; if
`$ARGUMENTS` is empty, list every project and stop):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/collect.py" --out - --tree-depth 3
```

The output is a single JSON object. For the matched project, present:

1. Its path, session count, total tokens, and estimated cost.
2. Its `tree` rendered as an indented folder listing, directories first.
   Collapse any directory with more than 20 children to a count.
   Nodes carrying `"truncated": true` were cut off by the scan budget — say
   so rather than implying the directory is empty.
3. Its sessions, newest first: title, tokens, estimated cost.

If several projects match, list the candidates and ask which one.
If none match, list the available project names.

For a clickable, navigable version of the same thing, point the user at
`/atlas`.
