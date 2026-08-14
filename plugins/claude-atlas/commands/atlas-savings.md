---
description: Find sessions that could have run on a cheaper Claude model, with the evidence behind each suggestion.
argument-hint: "[--top N]"
allowed-tools: Bash(python3:*)
---

Show cheaper-model suggestions and non-model cost levers.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report.py" --by savings
```

Pass `--top N` through if it appears in `$ARGUMENTS`.

The report prints its own bars, savings, and evidence. After it runs, add at
most three lines:

- the headline number (total potential saving, and what share of spend it is)
- whether the suggestions are mostly high or low confidence, and what that means
- the single biggest **actionable** lever, if there is one

**Be honest about what these suggestions are.** Atlas scores observable
behaviour — turns, reply length, how often reasoning was engaged, read vs
write tool mix. It cannot see whether a task was actually hard. A
low-confidence row rests on one signal and may well be wrong. Never tell the
user they "wasted" money; frame it as sessions worth trialling on a cheaper
model.

If the report shows no candidates, say so plainly — for reasoning-heavy
agentic work that is the correct result, not a failure.
