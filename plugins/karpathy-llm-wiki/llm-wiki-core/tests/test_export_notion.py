"""Tests for ``kb export-notion`` — wiki → Notion manifest builder."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from llm_wiki.cli import app  # noqa: F401
from llm_wiki.commands.export_notion import (
    _build_manifest,
    _build_sources,  # noqa: F401
    _normalize_source,  # noqa: F401
)
from llm_wiki.core.config import load_config


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


def _write_note(permanent: Path, name: str, body: str) -> None:
    """Write a permanent note file (frontmatter + body) to the wiki."""
    (permanent / f"{name}.md").write_text(body, encoding="utf-8")


def _write_manifest(wiki_root: Path, entries: list[dict[str, Any]]) -> None:
    """Write the ingest manifest (a JSON list) at ``raw/inbox/.manifest.json``."""
    cfg = load_config(wiki_root)
    cfg.raw_inbox.mkdir(parents=True, exist_ok=True)
    (cfg.raw_inbox / ".manifest.json").write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def test_build_manifest_maps_all_fields(populated_wiki: Path) -> None:
    _write_manifest(
        populated_wiki,
        [
            {
                "id": "ingest-aaa111",
                "file": "raw/web/api-gw.md",
                "type": "url",
                "source": "session-2026-04-09",
                "date": "2026-04-09T08:00:00",
                "status": "processed",
                "source_class": "web",
            }
        ],
    )
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)

    by_slug = {n["slug"]: n for n in manifest["notes"]}
    note = by_slug["api-gateway-auth-pattern"]

    assert note["title"] == "API Gateway Authentication Pattern"
    assert note["knowledge_type"] == "pattern"
    assert note["status"] == "approved"
    assert note["confidence"] == "high"
    assert note["scope"] == "universal"
    assert note["tags"] == ["architecture", "api-design"]
    assert note["source"] == "session-2026-04-09"
    assert note["created"] == "2026-04-09T10:00:00"
    assert note["links"] == ["token-refresh-strategy"]
    assert "---" not in note["body_md"]
    assert note["body_md"].lstrip().startswith("# API Gateway Authentication Pattern")
    # Best-effort note->source match: the note's free-text source equals a manifest source.
    assert note["source_ref"] == "ingest-aaa111"
    assert manifest["sources"][0]["ingest_id"] == "ingest-aaa111"
    assert manifest["sources"][0]["source_class"] == "web"
