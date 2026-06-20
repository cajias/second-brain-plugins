---
name: lint-and-repair
description: Reusable skill for running wiki health checks, interpreting lint results, and conservatively auto-repairing frontmatter, tags, and link issues
---

# Lint and Repair

Shared knowledge for validating wiki health and fixing issues. Used by `/kb-lint` (interactively) and `quality-reviewer` agent (autonomously).

## Running the Scanner

```bash
kb lint --json
```

Returns structured data with these sections:

| Section | What it contains |
|---------|-----------------|
| `frontmatter` | Per-file frontmatter completeness and validity |
| `orphans` | Notes with zero inlinks (no other note links to them) |
| `broken_links` | Wikilinks pointing to non-existent files |
| `tag_compliance` | Rogue tags not in approved taxonomy, over-limit files |
| `note_count` | Total permanent notes |
| `link_graph` | Node/edge counts and per-note link data |

## Frontmatter Validation

Frontmatter follows a **tiered** model. Lint only errors on the required tier; the
recommended tier is auto-repairable but does not block a clean lint.

**Required** (a missing one is a lint error):

| Field | Valid values | Default if missing |
|-------|-------------|-------------------|
| knowledge type | fact, pattern, decision, correction, idea, design, exploration | Flag for review |
| `tags` | Up to 6 from approved taxonomy | Flag for review |
| `source` | Free text | Flag for review |
| `created` | `YYYY-MM-DD` | File modification date |

The knowledge type is satisfied by **either** `knowledge_type` **or** `type` holding a
knowledge-type value (simplified schema where `type` doubles as `knowledge_type`).

**Recommended** (canonical schema, but absence is not a lint error):

| Field | Valid values | Default if missing |
|-------|-------------|-------------------|
| `id` | `perm-YYYYMMDD-XXXXX` | Generate from date + random hex |
| `type` | `permanent` | `permanent` |
| `status` | pending, approved, archived | `pending` |
| `confidence` | high, medium, low | `low` |
| `scope` | universal, project, temporal | `universal` |

Enum values above and the 6-tag cap are still strictly validated whenever the field is
present. Legacy simplified-schema notes can be upgraded to the canonical schema with
`kb migrate-frontmatter` (dry-run by default; add `--apply` to write changes).

## Tag Compliance

- Only tags from the approved taxonomy are valid (17 tags -- check via `kb lint --tags` or `_meta/tag-taxonomy.md`)
- Maximum 6 tags per note
- For rogue tags: replace with the closest approved tag using string similarity
- Flag ambiguous replacements for human review

## Orphan Detection

Notes with zero inlinks are orphans. For each orphan:
1. Read its title and tags
2. Identify 2-3 existing notes that are thematically related
3. Suggest specific wikilink additions (or make them, if autonomous)

Use the `search-and-link` skill to find and add connections.

## Auto-Repair Guidelines

Be conservative -- only change what's clearly wrong:

| Issue | Auto-fix? | Action |
|-------|-----------|--------|
| Missing `id` | Yes | Generate `perm-YYYYMMDD-XXXXX` |
| Missing `created` | Yes | Use file modification date |
| Missing `status` | Yes | Set `pending` |
| Missing `confidence` | Yes | Set `low` |
| Missing `scope` | Yes | Set `universal` |
| Rogue tag (close match) | Yes | Replace with closest approved tag |
| Rogue tag (ambiguous) | No | Flag for human review |
| Missing `knowledge_type` | No | Flag for human review |
| Wrong `knowledge_type` | No | Flag for human review (subjective) |
| Broken wikilink | No | Flag -- target may need to be created |

After auto-repairs, re-run the scanner to confirm:

```bash
kb lint --json
```

Then refresh charts:

```bash
kb charts
```

## Confidence Calibration

When reviewing notes (quality-reviewer use case):

- `confidence: high` should have strong evidence or be a well-established pattern
- `confidence: low` should be speculative or from a single source
- If the evidence doesn't match the confidence level, adjust it

## Report Format

```
## Lint Summary

- Notes scanned: N
- Issues found: N (by category)
- Auto-fixed: N
- Flagged for human review: N (with reasons)

### Issues by Category
- Frontmatter: N
- Orphans: N
- Broken links: N
- Rogue tags: N

### Recommendations
Prioritized list of actions to improve wiki health.
```
