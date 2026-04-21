# karpathy-llm-wiki — Demo
# Run from llm-wiki-core/: vhs ../demo.tape

Output ../demo.gif

Set Shell zsh
Set FontSize 14
Set Width 1200
Set Height 650
Set Padding 12
Set Theme "Catppuccin Mocha"
Set TypingSpeed 30ms
Set PlaybackSpeed 1.8

# ── Hidden setup ───────────────────────────────────────
Hide
Type "export KARPATHY_WIKI_ROOT=/tmp/kb-demo-$$"
Enter
Type "rm -rf $KARPATHY_WIKI_ROOT 2>/dev/null"
Enter
Sleep 300ms
Show

# ── Install ────────────────────────────────────────────
Type "echo '━━ Install ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Sleep 500ms
Type "# Install from your GitLab repo (or any marketplace):"
Enter
Sleep 500ms
Type "claude plugin add code.aws.dev/.../second-brain-plugins"
Sleep 1.5s
Enter
Sleep 1s

# ── Env var ────────────────────────────────────────────
Type "echo '━━ Configure ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Sleep 500ms
Type "# Set KARPATHY_WIKI_ROOT so the CLI finds your wiki from anywhere:"
Enter
Sleep 500ms
Type 'export KARPATHY_WIKI_ROOT=~/Projects/my-wiki   # add to .envrc'
Sleep 1.5s
Enter
Sleep 1s

# ── Init ───────────────────────────────────────────────
Type "echo '━━ Initialize ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Sleep 500ms
Type "uv run kb init $KARPATHY_WIKI_ROOT"
Enter
Sleep 2s

# ── Ingest ─────────────────────────────────────────────
Type "echo '━━ Ingest ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Sleep 500ms
Type 'uv run kb ingest --mode text --source "Transformers use self-attention to weigh input tokens, enabling parallelism and long-range dependencies."'
Enter
Sleep 1.5s
Type 'uv run kb ingest --mode text --source "RAG grounds LLM outputs in retrieved documents, reducing hallucination."'
Enter
Sleep 1.5s

# ── Compile ────────────────────────────────────────────
Type "echo '━━ Compile (Claude Code) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Sleep 500ms
Type "# In Claude Code, the compile agent extracts atomic ideas:"
Enter
Sleep 500ms
Type "echo '> /kb-compile'"
Enter
Type "echo '  ✓ 2 notes extracted, 0 duplicates, 2 written to wiki/permanent/'"
Enter
Sleep 2s

# ── Switch to real wiki for search/lint ────────────────
Hide
Type "export KARPATHY_WIKI_ROOT=/Users/cajias/Projects/llm-wiki"
Enter
Sleep 300ms
Show

# ── Search ─────────────────────────────────────────────
Type "echo '━━ Search ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Sleep 500ms
Type 'uv run kb search "how should agents authenticate" --limit 3'
Enter
Sleep 5s

# ── Lint ───────────────────────────────────────────────
Type "echo '━━ Lint ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Sleep 500ms
Type "uv run kb lint 2>&1 | head -25"
Enter
Sleep 3s

# ── Maintenance ────────────────────────────────────────
Type "echo '━━ Maintenance ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Sleep 500ms
Type "uv run kb maintenance status"
Enter
Sleep 1.5s

# ── Health ─────────────────────────────────────────────
Type "echo '━━ Health Audit (Claude Code) ━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Sleep 500ms
Type "echo '> /kb-health          # full diagnostic: staleness, gaps, orphans'"
Enter
Type "echo '> /kb-health --fix    # auto-dispatch agents to repair issues'"
Enter
Sleep 2s

# ── Fin ────────────────────────────────────────────────
Sleep 500ms
Type "echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Type "echo 'Your knowledge always adds up. ✨'"
Enter
Sleep 3s
