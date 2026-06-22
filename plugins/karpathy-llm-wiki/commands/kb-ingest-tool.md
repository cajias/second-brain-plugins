---
description: Ingest a tool (library/framework/service/repo) from any URL into the knowledge base
---

# /kb-ingest-tool -- Tool Ingestion (URL-agnostic)

You ingest a *tool* from any URL into the inbox so it can be compiled into one
`knowledge_type: tool` note.

## Step 1: Parse arguments

Input: `$ARGUMENTS`. Each item is a tool URL or a bare `owner/repo` GitHub ref.

Accepted forms:
- `https://github.com/owner/repo` — full GitHub URL
- `owner/repo` — bare GitHub ref (no scheme)
- `https://deepeval.com` — any HTTPS product/docs page
- Multiple items separated by whitespace or newlines

## Step 2: Ingest each tool (SERIALLY)

The inbox manifest is non-atomic — never run two `kb ingest-tool` at once.

For each item in order:

```bash
kb ingest-tool "https://github.com/owner/repo"
kb ingest-tool "owner/repo"
kb ingest-tool "https://deepeval.com"
```

Routing rules:
- **GitHub URL or bare `owner/repo`**: uses the GitHub REST API to fetch the README
  and repository metadata (name, description, stars, language, topics). Richest signal.
- **Any other HTTPS URL**: fetches the page as HTML and extracts main content via
  trafilatura. Suitable for product sites, docs pages, and blog posts.

Both paths set `source:` to the original URL and `source_class` to `tool`.

Optional flag:
- `--json` / `-j` — emit result as JSON (useful in scripts/workflows)

## Step 3: Report results

After each ingestion, tell the user:

1. **What was ingested**: source URL, destination path
2. **Manifest ID**: the ID assigned (`ingest-xxxxxxxx`)
3. **Next step**: suggest running `/kb-compile` to process the inbox

For multiple items, report a summary:

```
Ingested 2 tools:
  [1] https://github.com/confident-ai/deepeval -> raw/inbox/20260622-deepeval.md (ingest-a1b2c3d4)
  [2] https://deepeval.com -> raw/inbox/20260622-deepeval-com.md (ingest-e5f6g7h8)

Run /kb-compile to process these into permanent notes.
```

## Important Notes

- GitHub rate limit: unauthenticated requests are limited to 60/hour. Set `$GITHUB_TOKEN`
  or run `gh auth login` first to raise the limit to 5000/hour. The token is read at call
  time and never stored.
- Ingested items land in `raw/inbox/` — they are NOT yet wiki notes.
- For batch ingestion of many tools, use the `ingest-tools` workflow (serial).
- If `kb` is not found, tell the user to install the llm-wiki CLI tool.
