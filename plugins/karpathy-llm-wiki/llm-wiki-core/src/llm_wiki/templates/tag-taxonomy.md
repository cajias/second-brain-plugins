---
title: Tag Taxonomy
type: meta
updated: "2026-04-09"
---

# Tag Taxonomy

## Knowledge Types

An open enum defining what kind of knowledge a note represents. Validated by `/kb-lint`.

| Type | Description |
|------|-------------|
| `fact` | Verified information — something known to be true, backed by evidence or authoritative source |
| `pattern` | Reusable approach or technique that has proven effective across multiple contexts |
| `decision` | A choice made with rationale — captures the why, alternatives considered, and tradeoffs |
| `correction` | Something previously believed wrong, now fixed — captures the before/after and what changed |
| `idea` | Unvalidated concept worth tracking — may become a pattern, decision, or dead end |
| `design` | Architectural or system design — structure, components, interfaces, data flow |
| `exploration` | Open-ended investigation or question — synthesized from queries, research, or curiosity |
| `tool` | Library/framework/service/CLI reference — captures how a tool works, when to use it, and tradeoffs |

## Approved Tags

All wiki notes must use tags from this approved list. Maximum 6 tags per note. `/kb-lint --tags` enforces compliance.

| Tag | Description |
|-----|-------------|
| `architecture` | System design, component boundaries, layering, modularity |
| `testing` | Test strategies, frameworks, coverage, TDD, property-based testing |
| `security` | Authentication, authorization, secrets management, threat modeling |
| `performance` | Optimization, profiling, caching, latency, throughput |
| `api-design` | REST, GraphQL, gRPC, contract design, versioning, error formats |
| `authentication` | Identity, OAuth, JWT, SSO, session management, credential storage |
| `observability` | Logging, metrics, tracing, alerting, dashboards, SLOs |
| `databases` | SQL, NoSQL, indexing, migrations, query optimization, replication |
| `distributed-systems` | Consensus, eventual consistency, partitioning, CAP theorem, retries |
| `devops` | CI/CD, infrastructure as code, deployment strategies, containers |
| `frontend` | UI frameworks, state management, accessibility, rendering strategies |
| `llm` | Large language models, prompting, fine-tuning, embeddings, RAG |
| `agent-patterns` | Autonomous agents, tool use, planning, memory, multi-agent coordination |
| `code-quality` | Readability, refactoring, linting, code review, naming conventions |
| `documentation` | Technical writing, API docs, architecture decision records, READMEs |
| `error-handling` | Exception strategies, retry policies, circuit breakers, graceful degradation |
| `data-modeling` | Schema design, normalization, domain modeling, event sourcing |

### Tool Tags

| Tag | Description |
|-----|-------------|
| `tool-framework` | Tool type: framework |
| `tool-library` | Tool type: library |
| `tool-cli` | Tool type: CLI |
| `tool-mcp-server` | Tool type: MCP server |
| `tool-agent` | Tool type: agent |
| `tool-skill` | Tool type: skill |
| `tool-plugin` | Tool type: plugin |
| `tool-sdk` | Tool type: SDK |
| `tool-service` | Tool type: service |
| `tool-dataset` | Tool type: dataset |

### SDLC Phase Tags

| Tag | Description |
|-----|-------------|
| `phase-planning` | SDLC phase: planning |
| `phase-design` | SDLC phase: design |
| `phase-implementation` | SDLC phase: implementation |
| `phase-code-review` | SDLC phase: code review |
| `phase-testing` | SDLC phase: testing |
| `phase-debugging` | SDLC phase: debugging |
| `phase-deployment` | SDLC phase: deployment |
| `phase-observability` | SDLC phase: observability |
| `phase-security` | SDLC phase: security |
| `phase-docs` | SDLC phase: docs |

## Adding New Tags

1. Propose the tag with a clear description
2. Add it to this file
3. Run `/kb-lint --tags` to verify no conflicts
4. Existing notes can be re-tagged as needed
