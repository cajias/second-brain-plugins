---
description: Ingest raw documents into the knowledge base pipeline
---

# /kb-ingest -- Raw Document Ingestion

You are the knowledge base ingestion handler. Your job is to route raw documents into the pipeline so they can later be compiled into permanent wiki notes.

## Step 1: Parse arguments

The user's input is: `$ARGUMENTS`

Determine the mode and source:

- **`session <path>`**: Ingest a Claude Code session log (`.jsonl` file)
- **`file <path>`**: Ingest a document (PDF, markdown, text, code, etc.)
- **`url <url>`**: Ingest a web article by fetching its content
- **`text "content"`**: Ingest a quick text snippet inline
- **`list`** or no arguments: Show pending inbox items

If the mode is ambiguous, infer from context:
- A path ending in `.jsonl` -> session
- A string starting with `http` -> url
- A path to an existing file -> file
- Bare text with no path -> text

## Step 2: Execute the ingest

Run the appropriate command:

```bash
kb ingest --mode MODE --source "SOURCE"
```

Replace `MODE` with: session, file, url, or text.
Replace `SOURCE` with the path, URL, or text content (properly shell-escaped).

For listing pending items:

```bash
kb ingest --list
```

## Step 3: Report results

After ingestion, tell the user:

1. **What was ingested**: source, type, destination path
2. **Manifest ID**: the ID assigned to this inbox entry
3. **Next step**: suggest running `/kb-compile` to process the inbox into permanent notes

If listing, display the pending items in a readable table format.

## Step 4: Batch ingest (special case)

If the user provides multiple items (e.g., "ingest these 3 URLs"), run the ingest command for each one sequentially and report a summary:

```
Ingested 3 items:
  [1] url -> raw/web/20260409-example-com.md (ingest-a1b2c3d4)
  [2] url -> raw/web/20260409-blog-post.md (ingest-e5f6g7h8)
  [3] text -> raw/inbox/20260409-quick-note.md (ingest-i9j0k1l2)

Run /kb-compile to process these into permanent notes.
```

## Important Notes

- Ingested items land in `raw/` subdirectories -- they are NOT yet wiki notes.
- The manifest tracks all pending items for `/kb-compile`.
- For `url` mode: the CLI extracts text from HTML. If the result is poor quality, suggest the user try a manual copy instead.
- If `kb` is not found, tell the user to install the llm-wiki CLI tool.
