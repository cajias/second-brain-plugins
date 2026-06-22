"""Tests for ``kb export-notion`` — wiki → Notion manifest builder."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from llm_wiki.cli import app
from llm_wiki.commands.export_notion import (
    _build_manifest,
    _build_sources,
    _normalize_source,
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


def test_dangling_links_are_separated(populated_wiki: Path) -> None:
    permanent = populated_wiki / "wiki" / "permanent"
    _write_note(
        permanent,
        "links-everywhere",
        """\
---
id: perm-20260410-lll01
type: permanent
knowledge_type: idea
status: pending
confidence: low
scope: universal
tags:
  - llm
source: "manual"
created: "2026-04-10T08:00:00"
---

# Links Everywhere

Real target [[orphan-note]] and a missing one [[nonexistent-note]].
""",
    )
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)

    by_slug = {n["slug"]: n for n in manifest["notes"]}
    assert by_slug["links-everywhere"]["links"] == ["orphan-note"]
    assert {"from": "links-everywhere", "target": "nonexistent-note"} in manifest["dangling"]
    assert all(d["target"] != "orphan-note" for d in manifest["dangling"])


def test_aliased_wikilink_resolves_to_target(populated_wiki: Path) -> None:
    permanent = populated_wiki / "wiki" / "permanent"
    _write_note(
        permanent,
        "aliased-link",
        """\
---
id: perm-20260410-aaa02
type: permanent
knowledge_type: fact
status: approved
confidence: high
scope: universal
tags:
  - llm
source: "manual"
created: "2026-04-10T09:00:00"
---

# Aliased Link

See [[orphan-note|the orphan]] for details.
""",
    )
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)
    by_slug = {n["slug"]: n for n in manifest["notes"]}
    assert by_slug["aliased-link"]["links"] == ["orphan-note"]


def test_simplified_schema_type_field_supplies_knowledge_type(populated_wiki: Path) -> None:
    permanent = populated_wiki / "wiki" / "permanent"
    _write_note(
        permanent,
        "simplified-schema",
        """\
---
type: decision
status: approved
confidence: medium
scope: project
tags:
  - devops
source: "manual"
created: "2026-04-10T10:00:00"
---

# Simplified Schema Note

This note uses the simplified schema where `type` holds the knowledge type.
""",
    )
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)
    by_slug = {n["slug"]: n for n in manifest["notes"]}
    assert by_slug["simplified-schema"]["knowledge_type"] == "decision"


def test_normalize_source_strips_whitespace_and_trailing_slash() -> None:
    assert _normalize_source(" https://x/ ") == "https://x"
    assert _normalize_source("https://x") == "https://x"
    assert _normalize_source("  ") == ""


def test_build_sources_reads_manifest_list(populated_wiki: Path) -> None:
    _write_manifest(
        populated_wiki,
        [
            {
                "id": "ingest-src001",
                "file": "raw/web/a.md",
                "type": "url",
                "source": "https://example.com/a",
                "date": "2026-05-01T00:00:00",
                "status": "processed",
                "source_class": "web",
            },
            # Older entry missing some keys — read defensively with .get.
            {"id": "ingest-src002", "source": "https://example.com/b"},
        ],
    )
    cfg = load_config(populated_wiki)
    sources = _build_sources(cfg)
    assert sources[0]["ingest_id"] == "ingest-src001"
    assert sources[0]["file"] == "raw/web/a.md"
    assert sources[1]["ingest_id"] == "ingest-src002"
    assert sources[1]["type"] is None  # missing key -> None, not KeyError
    assert sources[1]["source_class"] is None


def test_build_sources_missing_manifest_is_empty(wiki_root: Path) -> None:
    cfg = load_config(wiki_root)
    assert _build_sources(cfg) == []


def test_source_ref_matches_trailing_slash_and_whitespace(populated_wiki: Path) -> None:
    permanent = populated_wiki / "wiki" / "permanent"
    _write_note(
        permanent,
        "matched-note",
        """\
---
id: perm-20260411-mmm01
type: permanent
knowledge_type: fact
status: approved
confidence: high
scope: universal
tags:
  - llm
source: " https://example.com/paper "
created: "2026-04-11T08:00:00"
---

# Matched Note

Distilled from a paper.
""",
    )
    _write_manifest(
        populated_wiki,
        [
            {
                "id": "ingest-match01",
                "file": "raw/web/paper.md",
                "type": "url",
                "source": "https://example.com/paper/",
                "date": "2026-04-10T00:00:00",
                "status": "processed",
                "source_class": "web",
            }
        ],
    )
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)
    by_slug = {n["slug"]: n for n in manifest["notes"]}
    # Trailing slash + whitespace differences still match.
    assert by_slug["matched-note"]["source_ref"] == "ingest-match01"
    # Raw source text is kept regardless of matching (YAML parses the quoted value with its spaces).
    assert by_slug["matched-note"]["source"] == " https://example.com/paper "
    assert "matched-note" not in manifest["unmatched_sources"]


def test_source_ref_no_match_lists_unmatched(populated_wiki: Path) -> None:
    permanent = populated_wiki / "wiki" / "permanent"
    _write_note(
        permanent,
        "unmatched-note",
        """\
---
id: perm-20260411-uuu01
type: permanent
knowledge_type: fact
status: approved
confidence: high
scope: universal
tags:
  - llm
source: "https://nowhere.example/none"
created: "2026-04-11T09:00:00"
---

# Unmatched Note

No manifest entry has this source.
""",
    )
    _write_manifest(
        populated_wiki,
        [
            {
                "id": "ingest-other01",
                "file": "raw/web/other.md",
                "type": "url",
                "source": "https://example.com/other",
                "date": "2026-04-10T00:00:00",
                "status": "processed",
                "source_class": "web",
            }
        ],
    )
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)
    by_slug = {n["slug"]: n for n in manifest["notes"]}
    assert by_slug["unmatched-note"]["source_ref"] is None
    assert "unmatched-note" in manifest["unmatched_sources"]


def test_source_ref_multiple_matches_latest_date_wins(populated_wiki: Path) -> None:
    permanent = populated_wiki / "wiki" / "permanent"
    _write_note(
        permanent,
        "dup-source-note",
        """\
---
id: perm-20260411-ddd01
type: permanent
knowledge_type: fact
status: approved
confidence: high
scope: universal
tags:
  - llm
source: "https://example.com/dup"
created: "2026-04-11T10:00:00"
---

# Dup Source Note

Ingested twice.
""",
    )
    _write_manifest(
        populated_wiki,
        [
            {
                "id": "ingest-old",
                "file": "raw/web/dup-old.md",
                "type": "url",
                "source": "https://example.com/dup",
                "date": "2026-04-01T00:00:00",
                "status": "processed",
                "source_class": "web",
            },
            {
                "id": "ingest-new",
                "file": "raw/web/dup-new.md",
                "type": "url",
                "source": "https://example.com/dup",
                "date": "2026-05-01T00:00:00",
                "status": "processed",
                "source_class": "web",
            },
        ],
    )
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)
    by_slug = {n["slug"]: n for n in manifest["notes"]}
    assert by_slug["dup-source-note"]["source_ref"] == "ingest-new"


def test_missing_manifest_yields_null_source_refs(populated_wiki: Path) -> None:
    # No _write_manifest call: the ingest manifest is absent.
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)
    assert manifest["sources"] == []
    assert all(n["source_ref"] is None for n in manifest["notes"])
    # Notes that HAVE a source string are still listed as unmatched.
    sourced = [n["slug"] for n in manifest["notes"] if n["source"].strip()]
    assert set(sourced) == set(manifest["unmatched_sources"])


def test_empty_wiki_yields_empty_manifest(wiki_root: Path) -> None:
    cfg = load_config(wiki_root)
    manifest = _build_manifest(cfg)
    assert manifest == {
        "notes": [],
        "dangling": [],
        "sources": [],
        "unmatched_sources": [],
    }


def test_export_notion_cli_stdout(populated_wiki: Path, monkeypatch) -> None:
    monkeypatch.chdir(populated_wiki)
    result = runner.invoke(app, ["export-notion"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    slugs = {n["slug"] for n in payload["notes"]}
    assert {"api-gateway-auth-pattern", "token-refresh-strategy", "orphan-note"} <= slugs


def test_export_notion_cli_writes_out_file(populated_wiki: Path, monkeypatch) -> None:
    monkeypatch.chdir(populated_wiki)
    result = runner.invoke(app, ["export-notion", "--out", "output/notion-manifest.json"])
    assert result.exit_code == 0, result.stdout
    written = (populated_wiki / "output" / "notion-manifest.json").read_text(encoding="utf-8")
    payload = json.loads(written)
    assert any(n["slug"] == "api-gateway-auth-pattern" for n in payload["notes"])
    assert "Wrote" in result.stdout


def test_export_notion_cli_no_config(wiki_root_bare: Path, monkeypatch) -> None:
    monkeypatch.chdir(wiki_root_bare)
    result = runner.invoke(app, ["export-notion"])
    assert result.exit_code == 1
    assert "Error:" in result.stdout or "Error:" in (result.stderr or "")
