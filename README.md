# Second Brain Plugins

A collection of [Claude Code](https://claude.ai/code) plugins for personal knowledge management.

## Available Plugins

| Plugin | Description | Install |
|--------|-------------|---------|
| [karpathy-llm-wiki](plugins/karpathy-llm-wiki/) | Karpathy-style knowledge wiki — ingest, compile, search, and maintain a semantic knowledge base | `claude plugin add cajias/second-brain-plugins --plugin karpathy-llm-wiki` |

## What is this?

These plugins implement different strategies for building and maintaining a **personal knowledge base** using Claude Code as the engine. Each plugin is a self-contained system with its own workflow, data model, and commands.

The goal: turn your scattered notes, articles, papers, and conversations into a structured, searchable, interconnected knowledge graph — with AI doing the heavy lifting.

## Quick Start

```bash
# Install a plugin
claude plugin add cajias/second-brain-plugins --plugin karpathy-llm-wiki

# Initialize a wiki in any directory
cd ~/my-wiki
/kb-init

# Start building knowledge
/kb-ingest file paper.pdf
/kb-compile
/kb-query "What patterns exist for X?"
```

## Contributing

Have a knowledge management strategy you'd like to implement as a plugin? Open an issue or PR. Each plugin should:

1. Live in `plugins/<name>/`
2. Include a `.claude-plugin/plugin.json` manifest
3. Include a `README.md` with install and usage instructions
4. Be self-contained (no cross-plugin dependencies)

## License

MIT
