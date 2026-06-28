# Using the Wiki with Obsidian

The knowledge base is just markdown. Every permanent note is a plain `.md` file with YAML
frontmatter and `[[wikilinks]]`, stored flat in `wiki/permanent/`. So you can open the wiki
in [Obsidian](https://obsidian.md) and get its whole reading and navigation layer for free --
no export, no sync step, no plugin.

Obsidian is **optional**. The `kb` pipeline is the source of truth; Obsidian is just a nice
way to read and browse what it produces.

## Open the vault

In Obsidian: **Open folder as vault** -> select your project's `wiki/` directory.

```
my-wiki/
└── wiki/
    ├── permanent/   # every atomic note
    └── _meta/       # tag taxonomy + auto-generated stats
```

Open `wiki/` (not the project root) so the raw inbox, generated charts (under `output/`), and
the `.lancedb/` index stay out of the graph and search. Obsidian resolves `[[wikilinks]]` by filename across
the whole vault, so the flat `permanent/` layout works as-is.

What you get immediately:

- **Graph view** -- the `[[wikilink]]` backbone the compiler builds renders as an
  interactive graph.
- **Backlinks** -- every note shows which notes link *to* it (the same inlinks `kb lint`
  tracks for orphan detection).
- **Full-text search** -- Obsidian's native search over titles, bodies, tags, and frontmatter.
- **Mobile** -- the same vault opens in Obsidian on iOS and Android.

Editing a note by hand keeps working, but let the `kb` pipeline create and validate notes so
frontmatter and tags stay canonical (`kb compile --write-note`, never the editor, for new
notes).

## Drive the pipeline from Claude Code

Obsidian reads; the `kb` CLI -- via Claude Code slash commands -- does the work. After any
command that writes notes, Obsidian picks up the new files automatically. The slash command
is what you type in Claude Code; the `kb` invocation is what it runs under the hood (you can
also run it directly in a terminal).

| Task | Slash command | `kb` invocation |
|------|---------------|-----------------|
| **Ingest** raw material | `/kb-ingest file path/to/doc.md` | `kb ingest --mode file --source "path/to/doc.md"` |
| **Compile** inbox -> notes | `/kb-compile` | `kb compile --list-inbox --json`, then `kb compile --write-note ...` per idea |
| **Search / ask** | `/kb-query "your question"` | `kb search "your question" --limit 5 --json` |
| **Lint** wiki health | `/kb-lint` | `kb lint --json` |

Notes:

- **Ingest** also accepts `session <path>`, `url <url>`, and `text "..."` modes; `/kb-ingest`
  (no args) or `kb ingest --list` shows pending inbox items.
- **Compile** is LLM-driven: `/kb-compile` reads the inbox, dedups, and writes notes. After
  writing it refreshes the search index and charts (`kb index --incremental`, `kb charts`).
- **Search** powers `/kb-query`. If results look stale, rebuild the index with
  `/kb-index` (`kb index --full`) or update it incrementally (`kb index --incremental`).
- **Lint** reports frontmatter gaps, orphans, broken links, and rogue tags; `/kb-lint --fix`
  auto-repairs the safe ones.

Once a command finishes, switch to Obsidian to read, follow backlinks, and explore the graph
of what you just compiled.
