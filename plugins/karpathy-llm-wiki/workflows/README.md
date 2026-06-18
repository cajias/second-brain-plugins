# Workflows

Deterministic multi-agent orchestrations for the karpathy-llm-wiki pipeline,
run via Claude Code's `Workflow` tool (opt-in, billed per agent). These are an
alternative to the markdown agents in `../agents/` for the heavy, fan-out-shaped
jobs — the agent stays the human-facing entry point; the workflow is the engine.

## compile-inbox-batch.js

Parallel replacement for the sequential `compile-agent`. Shape:

```
Extract (parallel, 1 agent/item)
   → Dedup (1 batched agent, --check-dedup-batch)
   → Write (parallel, 1 agent/unique note, handed the full batch title list
            for sibling [[wikilinks]])
   → Finalize (1 agent: batched --mark-processed + index --incremental + charts)
```

### Why a workflow (vs the markdown compile-agent)

- Per-item extract and per-note write run concurrently (cap ~10–16) instead of
  one-at-a-time.
- "Plan all titles, then write in parallel with the full list" produces better
  intra-batch links than sequential title accumulation — and removes the
  ordering dependency that made the sequential approach inherently serial.
- Dedup and mark-processed are single batched `kb` processes (one model load,
  one manifest write) via the `--check-dedup-batch` and batched `--mark-processed`
  CLI flags.

### Usage (hybrid: scout inline, then fan out)

1. Scout the work-list inline (cheap, deterministic):

   ```bash
   cd <wiki-root> && kb compile --list-inbox --json
   ```

   (or `--candidates-only` after a pre-filter pass).

2. Invoke with the scouted list:

   ```js
   Workflow({
     name: "compile-inbox-batch",            // if registered (see below)
     args: { wikiRoot: "<abs wiki root>", items: [{ id, file }, /* ... */] }
   })
   ```

   or run the file directly without registering:

   ```js
   Workflow({ scriptPath: "<repo>/plugins/karpathy-llm-wiki/workflows/compile-inbox-batch.js",
              args: { wikiRoot, items } })
   ```

### Registering as a named workflow

Named invocation requires the script on the workflow search path. Symlink it into
a `.claude/workflows/` dir at the project root:

```bash
mkdir -p .claude/workflows
ln -s ../../plugins/karpathy-llm-wiki/workflows/compile-inbox-batch.js \
      .claude/workflows/compile-inbox-batch.js
```

### Caveats

- Running a workflow is an explicit opt-in and consumes tokens per agent — it is
  not auto-invoked by a slash command.
- Writers each create a distinct new note file (no race). The shared manifest and
  index are touched only in Finalize.
- `args` must be passed as a real JSON object, not a JSON-encoded string.
