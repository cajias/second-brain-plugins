---
description: Run health checks on the knowledge base wiki
---

# /kb-lint -- Wiki Health Checker

You are the knowledge base linter. Your job is to run mechanical checks on the wiki and produce a clear, actionable report.

## Step 1: Run the scanner

Run the lint scanner to get raw data:

```bash
kb lint --json
```

Parse the JSON output. This gives you:
- `frontmatter`: per-file frontmatter completeness and validity
- `orphans`: notes with zero inlinks (no other note links to them via `[[wikilinks]]`)
- `broken_links`: wikilinks pointing to non-existent files
- `tag_compliance`: rogue tags not in the approved taxonomy, over-limit files
- `note_count`: total permanent notes
- `link_graph`: node/edge counts and per-note link data

## Step 2: Interpret flags from $ARGUMENTS

Parse the user's arguments: `$ARGUMENTS`

### Default (no flags): Full Health Check

Produce a human-readable health report covering ALL checks. Write it to `output/reports/lint-YYYY-MM-DD.md` (use today's date).

Report structure:
```
# KB Lint Report -- YYYY-MM-DD

## Summary
- Total notes: N
- Frontmatter issues: N files with missing fields
- Orphan notes: N (no inlinks)
- Broken links: N
- Rogue tags: N
- Tag compliance: N/N files compliant

## Frontmatter Issues
List each file with missing or invalid fields. Group by issue type.

## Orphan Notes
List notes that no other note links to. Suggest which notes could reasonably link to each orphan.

## Broken Links
List each broken link with source file and line number.

## Tag Compliance
List rogue tags and which files use them. Suggest the closest approved tag.

## Recommendations
Prioritized list of actions to improve wiki health.
```

### --orphans flag

Focus only on orphan analysis. For each orphan:
1. Read its title and tags
2. Identify 2-3 existing notes that are thematically related
3. Suggest specific wikilink additions that would connect the orphan

### --tags flag

Focus only on tag compliance. For each rogue tag:
1. Show which files use it
2. Suggest the closest approved tag from the taxonomy
3. Show the tag distribution (which tags are overused vs underused)

### --fix flag

Auto-repair mode. For each issue found:
1. **Missing frontmatter fields**: Add sensible defaults (status: pending, confidence: low, scope: universal). For missing `id`, generate one following the pattern `perm-YYYYMMDD-XXXXX`. For missing `created`, use file modification date.
2. **Rogue tags**: Replace with the closest approved tag (use string similarity).
3. **Invalid values**: Replace with the most common valid value for that field.
4. After making fixes, re-run the scanner to confirm improvements:
   ```bash
   kb lint --json
   ```
5. Refresh charts to reflect the fixes:
   ```bash
   kb charts
   ```
6. Report what was fixed and what still needs manual attention.

For any field where you cannot determine the correct value with confidence, add it with a default and flag it with `confidence: low` in the frontmatter.

### --explore flag

Analyze the wiki for knowledge gaps:
1. Look at the tag distribution -- which topics have few notes?
2. Look at the knowledge_type distribution -- are there enough corrections? decisions?
3. Identify clusters of related notes and find gaps between clusters.
4. Generate 5-10 follow-up questions that would fill the most important gaps.
5. Write the exploration to `output/reports/explorations-YYYY-MM-DD.md`

Exploration report structure:
```
# Knowledge Gap Exploration -- YYYY-MM-DD

## Current Coverage
Tag distribution table and knowledge_type distribution table.

## Identified Gaps
Numbered list of topic areas that are underrepresented.

## Suggested Follow-up Questions
5-10 specific questions that, if researched, would strengthen the knowledge base.
Each question should note which tags/types the resulting note would likely have.

## Cluster Analysis
Groups of related notes and the connections between them.
```

## Important Notes

- The scanner handles an empty wiki gracefully -- if there are zero notes, report that and skip detailed analysis.
- Notes use `[[wikilink]]` syntax for internal links. Plain text references like `- ENABLES: some-note` are NOT counted as links by the scanner.
- The approved tag list is available via `kb lint --tags` or in the wiki's `_meta/tag-taxonomy.md`.
- Configuration comes from `.kb-config.yml` in the project root.
