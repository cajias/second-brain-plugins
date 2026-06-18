# Workflows

Deterministic multi-agent orchestrations for the karpathy-llm-wiki pipeline, run via
Claude Code's `Workflow` tool (opt-in, billed per agent). They are the engine behind
the markdown agents in `../agents/` for the heavy, fan-out jobs — the agent stays the
human-facing entry point; the workflow does the parallel work.

All workflows require `args.workingDir` = the absolute path to the wiki root (the dir
containing `.kb-config.yml`). Pass `args` as a real JSON object, never a JSON-encoded
string.

## compile-inbox-batch.js

Compile the next N pending inbox items into atomic notes, then de-orphan and index —
7 phases, parallel where safe:

```
Discover     1 agent  — list the next N pending inbox items
Compile      ~6 agents (parallel) — per chunk: scope-judge, dedup, normalize, write-note
Finalize     1 agent  — batched mark-processed (one atomic manifest write); no index here
Find Orphans 1 agent  — kb lint -> list freshly-orphaned notes
Plan Links   parallel (read-only) — pick an inbound source per orphan (sibling-first)
De-orphan    parallel, partitioned by SOURCE file — append inbound backlinks (race-free)
Verify       1 agent  — the single kb index --incremental + kb charts --all pass
```

Args: `{ workingDir, count=100, chunkSize?, compileAgents=6 }`.

Notes:
- Uses the batched `kb compile --mark-processed "id1,id2,..."` flag (atomic; one manifest
  write for the whole batch).
- Reads approved tags / knowledge_types from the wiki's `wiki/_meta/tag-taxonomy.md` — no
  hardcoded taxonomy.
- Preserves web-origin source URLs (frontmatter `source:` + a body `Source:` line).
- De-orphan groups edits by the source file being edited, so parallel editors never touch
  the same file.

## ingest-notion-cited-sources.js

Extract cited external Source URLs from a set of Notion pages and ingest each into the
inbox. Requires the Notion MCP server.

```
Extract  parallel — read each Notion page, pull URLs from its Sources section
Ingest   sequential slices — kb ingest --mode url per URL (manifest-safe)
Report   summarize ingested / failed / deduped
```

Args: `{ workingDir, pages:[{id,title,number}] | urls:[...], extractOnly?, ingestChunk=15 }`.
Pass `extractOnly:true` to get the deduped URL list without ingesting (workingDir then optional).

## Usage (hybrid: scout inline, then fan out)

```js
// 1. (optional) scout: cd <wiki-root> && kb compile --list-inbox --json
// 2. invoke:
Workflow({ name: "compile-inbox-batch", args: { workingDir: "/abs/wiki", count: 50 } })
```

### Registering as named workflows

Named invocation needs the scripts on the workflow search path — symlink them into a
`.claude/workflows/` dir at your project/vault root:

```bash
mkdir -p .claude/workflows
ln -s <plugin>/workflows/compile-inbox-batch.js         .claude/workflows/
ln -s <plugin>/workflows/ingest-notion-cited-sources.js .claude/workflows/
```

Or run a file directly: `Workflow({ scriptPath: "<plugin>/workflows/compile-inbox-batch.js", args })`.

### Caveats

- Running a workflow is an explicit opt-in and consumes tokens per agent.
- These were generalized from a working vault setup; review the prompts against your
  taxonomy before first run.
