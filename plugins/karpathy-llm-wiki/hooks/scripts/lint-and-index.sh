#!/usr/bin/env bash
# Post-edit pipeline for wiki/permanent notes:
#   1. kb lint --file <path>      (blocking: exit 2 on schema violations)
#   2. kb index --incremental     (background: refreshes LanceDB embeddings)
set -euo pipefail

file_path=$(echo "${CLAUDE_TOOL_INPUT:-}" | grep -oE 'wiki/permanent/[^"[:space:]]+\.md' | head -n1 || true)

if [ -z "$file_path" ]; then
  exit 0
fi

cd "${KARPATHY_WIKI_ROOT:-$CLAUDE_PROJECT_DIR}"

if ! kb lint --file "$file_path"; then
  exit 2
fi

kb index --incremental 2>/dev/null &
disown || true

exit 0
