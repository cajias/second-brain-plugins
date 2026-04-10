---
description: Run health checks on the knowledge base wiki
---

# /kb-lint -- Wiki Health Checker

You are the knowledge base linter. Your job is to run mechanical checks on the wiki and produce a clear, actionable report.

> **Skills used**: Invoke `lint-and-repair` for scanning and fixing. Invoke `gap-analysis` for `--explore` mode. Invoke `search-and-link` for orphan connection suggestions.

## Step 1: Run the scanner

Run the lint scanner to get raw data:

```bash
kb lint --json
```

Parse the JSON output. See the `lint-and-repair` skill for the full schema of returned sections.

## Step 2: Interpret flags from $ARGUMENTS

Parse the user's arguments: `$ARGUMENTS`

### Default (no flags): Full Health Check

Produce a human-readable health report covering ALL checks. Write it to `output/reports/lint-YYYY-MM-DD.md`.

Follow the `lint-and-repair` skill's report format for structure.

### --orphans flag

Focus only on orphan analysis:
1. For each orphan, invoke the `search-and-link` skill to find 2-3 related notes
2. Suggest specific wikilink additions that would connect each orphan

### --tags flag

Focus only on tag compliance:
1. Show which files use rogue tags
2. Suggest closest approved tag (per the `lint-and-repair` skill's tag compliance rules)
3. Show tag distribution (overused vs underused)

### --fix flag

Auto-repair mode. Follow the `lint-and-repair` skill's auto-repair guidelines:
1. Fix what's clearly wrong (missing fields, rogue tags with close matches)
2. Flag ambiguous cases for human review
3. Re-run scanner to confirm improvements
4. Refresh charts:
   ```bash
   kb charts
   ```
5. Report what was fixed vs. what still needs attention

### --explore flag

Knowledge gap analysis. Invoke the `gap-analysis` skill:
1. Gather stats from lint output
2. Identify underrepresented tags, knowledge types, and missing bridges
3. Generate 5-10 research questions
4. Write exploration to `output/reports/explorations-YYYY-MM-DD.md`

## Important Notes

- The scanner handles an empty wiki gracefully.
- Notes use `[[wikilink]]` syntax for internal links.
- Configuration comes from `.kb-config.yml` in the project root.
