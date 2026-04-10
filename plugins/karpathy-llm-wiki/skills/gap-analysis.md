---
name: gap-analysis
description: Reusable skill for identifying knowledge gaps in the wiki by analyzing tag distribution, knowledge type coverage, and topic cluster connectivity
---

# Gap Analysis

Shared knowledge for finding and filling knowledge gaps. Used by `/kb-lint --explore` (interactive report) and `gap-researcher` agent (autonomous research and note creation).

## Gathering Data

Start with the lint scanner for raw stats:

```bash
kb lint --json
```

Key metrics to extract:
- Tag distribution (count per tag)
- Knowledge type distribution (count per type)
- Orphan count and rate
- Link graph density

## Identifying Gaps

### Underrepresented Tags

Tags with fewer than 5 notes are underrepresented. Compare against the full taxonomy:

```
architecture, testing, security, performance, api-design,
authentication, observability, databases, distributed-systems,
devops, frontend, llm, agent-patterns, code-quality,
documentation, error-handling, data-modeling
```

Priority: tags with 0-2 notes need the most attention.

### Underrepresented Knowledge Types

Knowledge types below 5% of total notes are underrepresented:

| Type | Typical underrepresentation |
|------|----------------------------|
| exploration | Often missing -- wikis tend to be pattern-heavy |
| decision | Often missing -- people record what, not why |
| correction | Often missing -- people don't document mistakes |
| idea | Often missing -- untested hypotheses get filtered out |

Priority: explorations and decisions add the most value because they capture reasoning.

### Missing Bridges

Tag pairs with zero co-occurring notes represent missing bridges. For example, if no note has both `security` and `llm` tags, that's a gap worth filling.

To find bridges: look at all tag pairs and find those with no notes containing both tags.

### Disconnected Clusters

Groups of notes that only link to each other but not to the broader wiki. These form "islands" in the knowledge graph.

## Generating Research Questions

For each gap, formulate a specific question:

- **Underrepresented tag**: "What are the key patterns in [TAG] that relate to [DOMINANT_TAG]?"
- **Missing bridge**: "How does [TAG_A] intersect with [TAG_B] in practice?"
- **Missing knowledge type**: "What are common mistakes (corrections) when implementing [TOPIC]?"
- **Disconnected cluster**: "How does [CLUSTER_TOPIC] connect to [MAIN_WIKI_TOPIC]?"

### Prioritization

1. Questions that connect underrepresented tags to the dominant cluster
2. Questions that add underrepresented knowledge types (explorations, decisions)
3. Questions that bridge disconnected topic clusters
4. Questions that reduce the orphan rate

## Filling Gaps (autonomous mode)

When creating notes to fill gaps:

1. Research the answer using available knowledge
2. Check for duplicates first (invoke `compile-note` skill's dedup step)
3. Find related notes for wikilinks (invoke `search-and-link` skill)
4. Each note should bridge at least 2 underrepresented tags
5. Include [[wikilinks]] to 3-5 existing notes
6. Prefer explorations and decisions over patterns
7. Be specific and actionable -- avoid vague overviews

Write notes via:

```bash
kb compile --write-note \
  --title "..." \
  --knowledge-type exploration \
  --tags "underrep-tag1,underrep-tag2,connected-tag" \
  --confidence medium \
  --body "Content with [[wikilinks]] to existing notes."
```

## Post-Analysis Refresh

After creating gap-filling notes:

```bash
kb index --incremental
kb charts
```

## Report Format

```
# Knowledge Gap Analysis -- YYYY-MM-DD

## Current Coverage
Tag distribution table and knowledge_type distribution table.

## Identified Gaps
Numbered list of underrepresented areas with severity.

## Missing Bridges
Tag pairs with no co-occurring notes.

## Suggested Research Questions
5-10 specific questions with expected tags/types for resulting notes.

## Cluster Analysis
Groups of related notes and connections between them.
```
