---
description: Run a comprehensive wiki health audit and optionally fix issues
---

# /kb-health -- Wiki Health Audit

You are the wiki health auditor. Your job is to run a comprehensive diagnostic across the knowledge base — staleness, gaps, orphans, and link quality — and produce an actionable report.

> **Agent used**: Dispatch the `wiki-health` agent for the full diagnostic. For targeted fixes, dispatch `wikilink-agent`, `gap-researcher`, or `quality-reviewer` as needed.

## Step 1: Parse arguments

Parse the user's arguments: `$ARGUMENTS`

### Default (no flags): Full Diagnostic

Dispatch the `wiki-health` agent to run all 5 phases:
1. Baseline metrics (`kb lint --json`)
2. Tag staleness (flags tags with no new notes in 30+ days)
3. Knowledge gaps (underrepresented tags/types, missing bridges)
4. Link health (orphan list + wikilink suggestions via embedding search)
5. Structured report to `output/reports/wiki-health-YYYY-MM-DD.md`

After the report, display the Summary table and Recommended Actions to the user.

### --fix flag

Run the full diagnostic first, then dispatch fix agents based on findings:

1. **If orphan rate > 30%**: Dispatch `wikilink-agent` to reduce orphans using hub-and-spoke strategy
2. **If underrepresented types or tags exist**: Dispatch `gap-researcher` to create bridging notes
3. **If quality issues found**: Dispatch `quality-reviewer` to audit recent notes

Report what each agent changed.

### --links flag

Focus only on link health:
1. Run `kb lint --json` to get orphan list
2. For top 10 orphans, run `kb search "<title>" --limit 5 --json`
3. Suggest wikilinks for results with score >= 0.7
4. Dispatch `wikilink-agent` if `--fix` is also passed

### --gaps flag

Focus only on knowledge gaps:
1. Run the gap-analysis skill (tag distribution, type distribution, missing bridges)
2. Cross-reference with tag staleness
3. Generate research questions
4. Dispatch `gap-researcher` if `--fix` is also passed

### --stale flag

Focus only on tag staleness:
1. Check `created` dates per tag
2. Flag tags with no new notes in 30+ days
3. Rank by days since last note

## Step 2: Display results

Always end with a summary for the user:
- Point to the report file path
- List the top 3 recommended actions
- If `--fix` was used, summarize what was changed

## Important Notes

- Without `--fix`, this command is **read-only** — it diagnoses but does not modify notes.
- The wiki-health agent writes its report to `output/reports/wiki-health-YYYY-MM-DD.md`.
- Configuration comes from `.kb-config.yml` in the project root.
- `KARPATHY_WIKI_ROOT` env var is used if set; otherwise walks up from cwd.
