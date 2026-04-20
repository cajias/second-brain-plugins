---
description: Run health checks on the knowledge base wiki
---

# /kb-lint -- Wiki Health Checker

You are the command dispatcher for wiki health checks. Your job is to run the scanner for baseline data, then dispatch the appropriate agent based on flags.

> **Agents used**: `quality-reviewer` (default and `--fix`), `wikilink-agent` (`--orphans --fix`), `gap-researcher` (`--explore --fix`).

## Step 1: Run the scanner

Run the lint scanner to get raw data:

```bash
kb lint --json
```

Parse the JSON output. This provides: frontmatter checks, tag compliance, orphan count, broken wikilinks.

## Step 2: Interpret flags from $ARGUMENTS

Parse the user's arguments: `$ARGUMENTS`

### Default (no flags): Full Health Check

Dispatch the `quality-reviewer` agent with the lint data. The agent audits notes for frontmatter completeness, tag accuracy, knowledge type accuracy, confidence calibration, and wikilink quality.

Display the agent's report and write it to `output/reports/lint-YYYY-MM-DD.md`.

### --orphans flag

Display the orphan list from the lint data. For each orphan, show the note title and tags.

If `--fix` is also passed: dispatch the `wikilink-agent` to reduce orphans using hub-and-spoke strategy. Report the orphan rate before and after.

### --tags flag

Focus only on tag compliance from the lint data:
1. Show which files use rogue tags
2. Suggest closest approved tag
3. Show tag distribution (overused vs underused)

This is a mechanical check — no agent dispatch needed.

### --fix flag (without other flags)

Dispatch the `quality-reviewer` agent with auto-repair instructions:
1. Fix what's clearly wrong (missing fields, rogue tags with close matches)
2. Flag ambiguous cases for human review
3. Re-run scanner to confirm improvements
4. Refresh charts: `kb charts`
5. Report what was fixed vs. what still needs attention

### --explore flag

Dispatch the `gap-researcher` agent to:
1. Analyze tag distribution, knowledge type distribution, and missing bridges from the lint data
2. Generate research questions for identified gaps
3. Write exploration to `output/reports/explorations-YYYY-MM-DD.md`

If `--fix` is also passed: the agent autonomously creates notes to fill the highest-priority gaps.

## Step 3: Display results

After the agent completes, display its summary to the user:
- Key findings and metrics
- Report file path
- Suggested next steps

## Important Notes

- The scanner handles an empty wiki gracefully.
- Notes use `[[wikilink]]` syntax for internal links.
- Configuration comes from `.kb-config.yml` in the project root.
