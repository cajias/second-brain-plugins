"""Tests for ``kb lint`` — wiki health checks and frontmatter validation.

The lint command runs ALL checks by default and has two output modes:
  - human-readable (default)
  - JSON (--json)

It also supports --fix for auto-repair.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_wiki.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lint(wiki_root: Path, *extra_args, monkeypatch=None) -> object:
    """Run ``kb lint`` with cwd set to wiki_root."""
    if monkeypatch:
        monkeypatch.chdir(wiki_root)
    return runner.invoke(app, ["lint"] + list(extra_args))


def _lint_json(wiki_root: Path, monkeypatch) -> dict:
    """Run ``kb lint --json`` and parse the result."""
    monkeypatch.chdir(wiki_root)
    result = runner.invoke(app, ["lint", "--json"])
    assert result.exit_code == 0, f"lint --json failed: {result.stdout}"
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Frontmatter validation
# ---------------------------------------------------------------------------


class TestFrontmatterValidation:
    """Lint should detect missing or invalid frontmatter fields."""

    def test_detects_missing_fields(self, wiki_root: Path, sample_note_missing_fields: str, monkeypatch):
        permanent = wiki_root / "wiki" / "permanent"
        (permanent / "incomplete-note.md").write_text(sample_note_missing_fields)

        data = _lint_json(wiki_root, monkeypatch)
        fm_entries = data["frontmatter"]
        incomplete = next(f for f in fm_entries if f["file"] == "incomplete-note.md")
        assert len(incomplete["fields_missing"]) > 0
        assert "knowledge_type" in incomplete["fields_missing"]

    def test_valid_note_has_no_missing(self, populated_wiki: Path, monkeypatch):
        data = _lint_json(populated_wiki, monkeypatch)
        for entry in data["frontmatter"]:
            if entry["file"] == "api-gateway-auth-pattern.md":
                assert entry["fields_missing"] == []
                assert entry["invalid_values"] == {}

    def test_detects_invalid_values(self, wiki_root: Path, monkeypatch):
        permanent = wiki_root / "wiki" / "permanent"
        (permanent / "bad-values.md").write_text("""\
---
id: perm-20260409-bad00
type: permanent
knowledge_type: not-a-real-type
status: invalid-status
confidence: maybe
scope: unknown-scope
tags:
  - testing
source: "test"
created: "2026-04-09T00:00:00"
---

# Bad Values Note
""")
        data = _lint_json(wiki_root, monkeypatch)
        bad = next(f for f in data["frontmatter"] if f["file"] == "bad-values.md")
        assert len(bad["invalid_values"]) > 0
        assert "knowledge_type" in bad["invalid_values"]


# ---------------------------------------------------------------------------
# Tag compliance
# ---------------------------------------------------------------------------


class TestTagCompliance:
    """Lint should detect rogue tags not in the taxonomy."""

    def test_detects_rogue_tags(self, wiki_root: Path, sample_note_rogue_tags: str, monkeypatch):
        permanent = wiki_root / "wiki" / "permanent"
        (permanent / "rogue-tags-note.md").write_text(sample_note_rogue_tags)

        data = _lint_json(wiki_root, monkeypatch)
        rogue = data["tag_compliance"]["rogue"]
        rogue_tags = [r["tag"] for r in rogue]
        assert "not-a-real-tag" in rogue_tags
        assert "also-invalid" in rogue_tags

    def test_compliant_tags_not_flagged(self, populated_wiki: Path, monkeypatch):
        data = _lint_json(populated_wiki, monkeypatch)
        compliant_files = [c["file"] for c in data["tag_compliance"]["compliant"]]
        # All notes in populated_wiki use approved tags
        assert "api-gateway-auth-pattern.md" in compliant_files
        assert "token-refresh-strategy.md" in compliant_files


# ---------------------------------------------------------------------------
# Orphan detection
# ---------------------------------------------------------------------------


class TestOrphanDetection:
    """Lint should detect notes with no inbound wikilinks."""

    def test_detects_orphan_notes(self, populated_wiki: Path, monkeypatch):
        data = _lint_json(populated_wiki, monkeypatch)
        assert "orphan-note" in data["orphans"]

    def test_linked_notes_not_in_orphans(self, populated_wiki: Path, monkeypatch):
        """api-gateway-auth-pattern and token-refresh-strategy link to each other."""
        data = _lint_json(populated_wiki, monkeypatch)
        # token-refresh-strategy is linked from api-gateway-auth-pattern
        assert "token-refresh-strategy" not in data["orphans"]


# ---------------------------------------------------------------------------
# Broken wikilinks
# ---------------------------------------------------------------------------


class TestBrokenWikilinks:
    """Lint should detect [[wikilinks]] pointing to non-existent files."""

    def test_detects_broken_link(self, wiki_root: Path, monkeypatch):
        permanent = wiki_root / "wiki" / "permanent"
        (permanent / "linker.md").write_text("""\
---
id: perm-20260409-lnk01
type: permanent
knowledge_type: fact
status: approved
confidence: high
scope: universal
tags:
  - testing
source: "test"
created: "2026-04-09T00:00:00"
---

# Linker Note

This links to [[does-not-exist]] which is broken.
""")
        data = _lint_json(wiki_root, monkeypatch)
        broken_targets = [b["target"] for b in data["broken_links"]]
        assert "does-not-exist" in broken_targets

    def test_valid_links_not_broken(self, populated_wiki: Path, monkeypatch):
        """Links between existing notes should not be flagged as broken."""
        data = _lint_json(populated_wiki, monkeypatch)
        broken_targets = [b["target"] for b in data["broken_links"]]
        assert "token-refresh-strategy" not in broken_targets
        assert "api-gateway-auth-pattern" not in broken_targets


# ---------------------------------------------------------------------------
# Link graph
# ---------------------------------------------------------------------------


class TestLinkGraph:
    """Lint JSON should include link graph information."""

    def test_graph_node_count(self, populated_wiki: Path, monkeypatch):
        data = _lint_json(populated_wiki, monkeypatch)
        assert data["link_graph"]["node_count"] == 3

    def test_graph_edge_count(self, populated_wiki: Path, monkeypatch):
        data = _lint_json(populated_wiki, monkeypatch)
        # api-gateway links to token-refresh, token-refresh links to api-gateway = 2 edges
        assert data["link_graph"]["edge_count"] == 2


# ---------------------------------------------------------------------------
# JSON output structure
# ---------------------------------------------------------------------------


class TestLintJsonOutput:
    """``kb lint --json`` produces the expected machine-readable structure."""

    def test_json_has_all_keys(self, populated_wiki: Path, monkeypatch):
        data = _lint_json(populated_wiki, monkeypatch)
        assert "timestamp" in data
        assert "note_count" in data
        assert "frontmatter" in data
        assert "link_graph" in data
        assert "orphans" in data
        assert "broken_links" in data
        assert "tag_compliance" in data

    def test_note_count_matches(self, populated_wiki: Path, monkeypatch):
        data = _lint_json(populated_wiki, monkeypatch)
        assert data["note_count"] == 3


# ---------------------------------------------------------------------------
# Human-readable output
# ---------------------------------------------------------------------------


class TestLintHumanOutput:
    """The default text output should summarize issues."""

    def test_summary_line(self, populated_wiki: Path, monkeypatch):
        monkeypatch.chdir(populated_wiki)
        result = runner.invoke(app, ["lint"])
        assert result.exit_code == 0
        assert "lint report" in result.stdout.lower() or "total notes" in result.stdout.lower()

    def test_reports_orphans(self, populated_wiki: Path, monkeypatch):
        monkeypatch.chdir(populated_wiki)
        result = runner.invoke(app, ["lint"])
        assert result.exit_code == 0
        assert "orphan" in result.stdout.lower()

    def test_reports_issues_with_count(self, wiki_root: Path, sample_note_rogue_tags: str, monkeypatch):
        permanent = wiki_root / "wiki" / "permanent"
        (permanent / "rogue.md").write_text(sample_note_rogue_tags)
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["lint"])
        assert result.exit_code == 0
        assert "issue" in result.stdout.lower() or "rogue" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Empty wiki
# ---------------------------------------------------------------------------


class TestLintEmptyWiki:
    """Lint on a wiki with no notes should succeed gracefully."""

    def test_empty_wiki_json(self, wiki_root: Path, monkeypatch):
        data = _lint_json(wiki_root, monkeypatch)
        assert data["note_count"] == 0
        assert data["orphans"] == []
        assert data["broken_links"] == []
