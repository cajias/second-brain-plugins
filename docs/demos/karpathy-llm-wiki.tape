# Render from the repo root:
#   vhs docs/demos/karpathy-llm-wiki.tape
# (The tape resolves $CORE relative to $PWD, so CWD must be the repo root.)

Output docs/demos/karpathy-llm-wiki.gif

Set Shell zsh
Set FontSize 14
Set Width 1000
Set Height 600
Set Theme "Dracula"
Set TypingSpeed 60ms
Set PlaybackSpeed 1.0

# --- Setup: clean, deterministic scratch dir ---
Hide
Type "export DEMO=/tmp/kb-vhs-demo && rm -rf $DEMO && mkdir -p $DEMO" Enter
Type "export CORE=$PWD/plugins/karpathy-llm-wiki/llm-wiki-core" Enter
Type "export HF_HUB_DISABLE_PROGRESS_BARS=1 TRANSFORMERS_VERBOSITY=error TOKENIZERS_PARALLELISM=false HF_HUB_DISABLE_TELEMETRY=1" Enter
Type "alias kb='uv run --project $CORE kb'" Enter
Type "clear" Enter
Show

# --- 1. Initialize a wiki ---
Type "kb init /tmp/kb-vhs-demo" Enter
Sleep 2s

Type "cd /tmp/kb-vhs-demo" Enter
Sleep 800ms

Type "clear" Enter
Sleep 300ms

# --- 2. Ingest a markdown stub ---
Type `kb ingest --mode text --source "Functional options pattern in Go uses variadic closures to configure structs without breaking the API."`
Enter
Sleep 2s

Type "kb ingest --list" Enter
Sleep 2s

Type "clear" Enter
Sleep 300ms

# --- 3. Compile inbox note into a permanent wiki entry ---
Type `kb compile --write-note \`
Enter
Type `  --title "Functional Options Pattern" \`
Enter
Type `  --knowledge-type pattern \`
Enter
Type `  --tags "code-quality,api-design" \`
Enter
Type `  --confidence high \`
Enter
Type `  --source "demo" \`
Enter
Type `  --body "Functional options use variadic closures to configure structs without breaking the API. Common in Go libraries for extensibility."`
Enter
Sleep 2500ms

Type "clear" Enter
Sleep 300ms

# --- 4. Build the vector index ---
Type "kb index --full" Enter
Sleep 4s

Type "clear" Enter
Sleep 300ms

# --- 5. Semantic search -- the payoff ---
Type `kb search "how do I configure a Go struct without breaking API" --limit 3`
Enter
Sleep 5s
