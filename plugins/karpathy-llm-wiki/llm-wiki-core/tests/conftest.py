"""Shared fixtures for llm-wiki tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
import yaml


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "src" / "llm_wiki" / "templates"

SAMPLE_CONFIG = {
    "version": "1.0",
    "vault_root": ".",
    "paths": {
        "raw_inbox": "raw/inbox",
        "raw_sessions": "raw/sessions",
        "raw_artifacts": "raw/artifacts",
        "raw_web": "raw/web",
        "wiki_permanent": "wiki/permanent",
        "wiki_index": "wiki/_index",
        "wiki_meta": "wiki/_meta",
        "output": "output",
        "fleeting": "fleeting",
    },
    "lancedb": {
        "db_path": ".lancedb",
        "table_name": "notes",
    },
    "compile": {
        "batch_size": 10,
        "auto_link_threshold": 0.75,
    },
    "lint": {
        "orphan_threshold": 0,
        "tag_compliance": "strict",
        "index_staleness_hours": 24,
        "index_min_coverage_pct": 80,
    },
    "query": {
        "default_limit": 10,
    },
}

SAMPLE_TAXONOMY = """\
---
title: Tag Taxonomy
type: meta
updated: "2026-04-09"
---

# Tag Taxonomy

## Knowledge Types

| Type | Description |
|------|-------------|
| `fact` | Verified information |
| `pattern` | Reusable approach or technique |
| `decision` | A choice made with rationale |
| `correction` | Something previously believed wrong |
| `idea` | Unvalidated concept worth tracking |
| `design` | Architectural or system design |
| `exploration` | Open-ended investigation |

## Approved Tags

| Tag | Description |
|-----|-------------|
| `architecture` | System design |
| `testing` | Test strategies |
| `security` | Authentication, authorization |
| `performance` | Optimization |
| `api-design` | REST, GraphQL, gRPC |
| `authentication` | Identity, OAuth, JWT |
| `llm` | Large language models |
| `agent-patterns` | Autonomous agents |
| `code-quality` | Readability, refactoring |
| `databases` | SQL, NoSQL |
| `devops` | CI/CD |
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def wiki_root(tmp_path: Path) -> Path:
    """Create a minimal wiki project directory with config and taxonomy.

    Returns the root path (contains .kb-config.yml).
    """
    root = tmp_path / "wiki-project"
    root.mkdir()

    # Config
    (root / ".kb-config.yml").write_text(yaml.dump(SAMPLE_CONFIG, default_flow_style=False))

    # Directories
    for subdir in (
        "raw/inbox",
        "raw/sessions",
        "raw/artifacts",
        "raw/web",
        "wiki/permanent",
        "wiki/_index",
        "wiki/_meta",
        "output",
        "output/reports",
        "output/charts",
        "fleeting",
    ):
        (root / subdir).mkdir(parents=True, exist_ok=True)

    # Taxonomy
    (root / "wiki" / "_meta" / "tag-taxonomy.md").write_text(SAMPLE_TAXONOMY)

    # Empty manifest
    (root / "raw" / "inbox" / ".manifest.json").write_text("[]\n")

    return root


@pytest.fixture()
def wiki_root_bare(tmp_path: Path) -> Path:
    """Return a completely empty temp directory (no .kb-config.yml)."""
    root = tmp_path / "empty-project"
    root.mkdir()
    return root


@pytest.fixture()
def sample_note_content() -> str:
    """Return a well-formed permanent note with full frontmatter."""
    return """\
---
id: perm-20260409-abc12
type: permanent
knowledge_type: pattern
status: approved
confidence: high
scope: universal
tags:
  - architecture
  - api-design
source: "session-2026-04-09"
created: "2026-04-09T10:00:00"
---

# API Gateway Authentication Pattern

When designing API gateways, use a centralized authentication layer that
validates JWT tokens before routing to downstream services.

## Key Points

- Validate at the edge, not per-service
- Use short-lived access tokens with refresh rotation
- See also: [[token-refresh-strategy]]
"""


@pytest.fixture()
def sample_note_missing_fields() -> str:
    """Return a note missing required frontmatter fields."""
    return """\
---
id: perm-20260409-xyz99
type: permanent
---

# Incomplete Note

This note is missing knowledge_type, status, confidence, scope, tags, source, created.
"""


@pytest.fixture()
def sample_note_rogue_tags() -> str:
    """Return a note whose tags are not in the approved taxonomy."""
    return """\
---
id: perm-20260409-rogue1
type: permanent
knowledge_type: fact
status: approved
confidence: medium
scope: universal
tags:
  - architecture
  - not-a-real-tag
  - also-invalid
source: "manual"
created: "2026-04-09T12:00:00"
---

# Note With Rogue Tags

This note has invalid tags that should be caught by lint.
"""


@pytest.fixture()
def populated_wiki(wiki_root: Path, sample_note_content: str) -> Path:
    """Create a wiki with several permanent notes for testing search/index/lint."""
    permanent = wiki_root / "wiki" / "permanent"

    # Note 1 -- the sample_note_content (has [[token-refresh-strategy]] wikilink)
    (permanent / "api-gateway-auth-pattern.md").write_text(sample_note_content)

    # Note 2
    (permanent / "token-refresh-strategy.md").write_text("""\
---
id: perm-20260408-def34
type: permanent
knowledge_type: pattern
status: approved
confidence: high
scope: universal
tags:
  - security
  - authentication
source: "session-2026-04-08"
created: "2026-04-08T09:00:00"
---

# Token Refresh Strategy

Use rotating refresh tokens with absolute expiry. See [[api-gateway-auth-pattern]].
""")

    # Note 3 -- orphan (no one links to it)
    (permanent / "orphan-note.md").write_text("""\
---
id: perm-20260407-ghi56
type: permanent
knowledge_type: idea
status: pending
confidence: low
scope: project
tags:
  - llm
source: "manual"
created: "2026-04-07T08:00:00"
---

# Orphan Note

Nobody links here.
""")

    return wiki_root


@pytest.fixture()
def manifest_with_entries(wiki_root: Path) -> Path:
    """Create a .manifest.json with two entries, one pending, one processed."""
    manifest_path = wiki_root / "raw" / "inbox" / ".manifest.json"
    entries = [
        {
            "id": "ingest-aaa11111",
            "file": "raw/inbox/20260409-test-note.md",
            "type": "text",
            "source": "inline-text",
            "date": "2026-04-09T10:00:00Z",
            "status": "pending",
        },
        {
            "id": "ingest-bbb22222",
            "file": "raw/inbox/20260408-old-note.md",
            "type": "text",
            "source": "inline-text",
            "date": "2026-04-08T09:00:00Z",
            "status": "processed",
        },
    ]
    manifest_path.write_text(json.dumps(entries, indent=2))
    return wiki_root


@pytest.fixture()
def mock_embedding_model(monkeypatch):
    """Mock sentence-transformers so tests don't download a 90MB model.

    Returns a mock model whose encode() produces random 384-dim vectors.
    The vectors are deterministic per-input so similarity comparisons
    are repeatable within a test.
    """
    model = MagicMock()

    def _encode(texts, **kwargs):
        vecs = []
        for text in texts:
            rng = np.random.RandomState(seed=hash(text) % (2**31))
            vec = rng.randn(384).astype(np.float32)
            vec = vec / np.linalg.norm(vec)
            vecs.append(vec)
        return np.array(vecs)

    model.encode = _encode

    # Patch the module-level cache in embeddings.py
    import llm_wiki.core.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "_model", model)
    # Also patch get_model to return our mock
    monkeypatch.setattr(emb_mod, "get_model", lambda: model)

    return model


@pytest.fixture()
def sample_pdf_path(tmp_path: Path) -> Path:
    """Create a small two-page PDF with known text for ingest tests.

    Uses pypdf's own writer to avoid pulling reportlab into test deps.
    The PDF has obvious whitespace anomalies so the normalizer is exercised.
    """
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length 60>>stream\n"
        b"BT /F1 12 Tf 50 700 Td (h e l l o   w o r l d) Tj ET\n"
        b"endstream endobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"xref\n0 6\n"
        b"0000000000 65535 f\n"
        b"0000000009 00000 n\n"
        b"0000000052 00000 n\n"
        b"0000000095 00000 n\n"
        b"0000000175 00000 n\n"
        b"0000000245 00000 n\n"
        b"trailer<</Size 6/Root 1 0 R>>\n"
        b"startxref\n304\n%%EOF\n"
    )
    p = tmp_path / "sample.pdf"
    p.write_bytes(pdf_bytes)
    return p
