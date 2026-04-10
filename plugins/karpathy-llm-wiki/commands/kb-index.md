---
description: Rebuild the knowledge base vector index
---

# /kb-index -- Rebuild Vector Index

Rebuild or update the vector index that powers semantic search across the wiki.

## Step 1: Parse arguments

The user's input is: `$ARGUMENTS`

Determine the mode:

- **No args or `--full`**: Full rebuild -- drop and recreate the index from all permanent notes
- **`--incremental`**: Only index files modified since the last run
- **`--stats`**: Show index statistics (note counts, tag distribution, knowledge types)

## Step 2: Execute

Run the appropriate command based on user input:

```bash
# Full rebuild (default)
kb index --full

# Incremental update
kb index --incremental

# Statistics only
kb index --stats
```

## Step 3: Report results

- For `--full` or `--incremental`: report how many notes were indexed, how long it took, and note that the stats file has been updated.
- For `--stats`: display the statistics in a readable format:

```
## Index Statistics

- Total notes indexed: N
- Last updated: YYYY-MM-DD HH:MM:SS

### Tag Distribution
| Tag | Count |
|-----|-------|
| architecture | 12 |
| llm | 8 |
| ...  | ... |

### Knowledge Type Distribution
| Type | Count |
|------|-------|
| pattern | 15 |
| fact | 10 |
| ... | ... |
```

## Important Notes

- The index uses vector embeddings for semantic search.
- Configuration is in `.kb-config.yml`.
- The search functionality is used by `/kb-query` via `kb search` -- you don't need to expose search directly here.
- After a full rebuild, suggest running `/kb-lint --explore` to check for knowledge gaps.
