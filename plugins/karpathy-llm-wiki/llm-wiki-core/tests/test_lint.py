"""Tests for ``kb lint`` — wiki health checks and frontmatter validation.

The lint command runs ALL checks by default and has two output modes:
  - human-readable (default)
  - JSON (--json)

It also supports --fix for auto-repair.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from llm_wiki.cli import app
from llm_wiki.core.frontmatter import parse


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lint(wiki_root: Path, *extra_args, monkeypatch=None) -> object:
    """Run ``kb lint`` with cwd set to wiki_root."""
    if monkeypatch:
        monkeypatch.chdir(wiki_root)
    return runner.invoke(app, ["lint", *extra_args])


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

    def test_simplified_schema_is_valid(self, wiki_root: Path, monkeypatch):
        """A note using `type: <knowledge-type>` (no `knowledge_type` field) lints clean."""
        permanent = wiki_root / "wiki" / "permanent"
        (permanent / "simplified-schema.md").write_text("""\
---
title: Simplified Schema Note
type: pattern
tags:
  - api-design
source: "raw/inbox/foo.md"
created: "2026-04-17"
---

# Simplified Schema

Uses the compact shape where `type` doubles as `knowledge_type`.
""")
        data = _lint_json(wiki_root, monkeypatch)
        entry = next(f for f in data["frontmatter"] if f["file"] == "simplified-schema.md")
        assert entry["fields_missing"] == []
        assert entry["invalid_values"] == {}
        assert "knowledge_type" in entry["fields_present"]

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
        assert data["contradictions"] == []


# ---------------------------------------------------------------------------
# Contradiction detection
# ---------------------------------------------------------------------------


class TestContradictionDetection:
    """``kb lint --contradictions`` surfaces close-but-distinct notes."""

    def test_contradictions_empty_by_default(self, populated_wiki: Path, monkeypatch):
        """Detection is opt-in; the key is present but empty without --contradictions."""
        data = _lint_json(populated_wiki, monkeypatch)
        assert data["contradictions"] == []

    def test_detects_contradiction(self, populated_wiki: Path, monkeypatch):
        """A similarity match in the contradiction band is reported as `detected`."""
        permanent = populated_wiki / "wiki" / "permanent"
        other = str(permanent / "token-refresh-strategy.md")

        def fake_batch(queries, db_path, table_name, threshold=0.85):
            # Only the first note (api-gateway-auth-pattern.md, sorted first) gets a
            # match in the [0.85, 0.92) band; the rest are unique.
            results = []
            for i, _query in enumerate(queries):
                if i == 0:
                    results.append(
                        {
                            "status": "similar",
                            "top_score": 0.88,
                            "matches": [
                                {
                                    "title": "Token Refresh Strategy",
                                    "score": 0.88,
                                    "file_path": other,
                                    "snippet": "...",
                                }
                            ],
                        }
                    )
                else:
                    results.append({"status": "unique", "top_score": 0.0, "matches": []})
            return results

        monkeypatch.setattr("llm_wiki.commands.lint.check_duplicates_batch", fake_batch)
        monkeypatch.chdir(populated_wiki)
        result = runner.invoke(app, ["lint", "--contradictions", "--json"])
        assert result.exit_code == 0, result.stdout
        contradictions = json.loads(result.stdout)["contradictions"]
        assert len(contradictions) == 1
        entry = contradictions[0]
        assert entry["file"] == "api-gateway-auth-pattern.md"
        assert entry["contradiction"]["status"] == "detected"
        assert entry["contradiction"]["with"] == "[[token-refresh-strategy]]"

    def test_near_duplicate_is_not_a_contradiction(self, populated_wiki: Path, monkeypatch):
        """A >= 0.92 match is a duplicate, not a contradiction, and is skipped."""
        permanent = populated_wiki / "wiki" / "permanent"
        other = str(permanent / "token-refresh-strategy.md")

        def fake_batch(queries, db_path, table_name, threshold=0.85):
            dup = {
                "status": "duplicate",
                "top_score": 0.97,
                "matches": [{"title": "x", "score": 0.97, "file_path": other, "snippet": "..."}],
            }
            return [
                dup if i == 0 else {"status": "unique", "top_score": 0.0, "matches": []} for i in range(len(queries))
            ]

        monkeypatch.setattr("llm_wiki.commands.lint.check_duplicates_batch", fake_batch)
        monkeypatch.chdir(populated_wiki)
        result = runner.invoke(app, ["lint", "--contradictions", "--json"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["contradictions"] == []

    def test_excludes_empty_body_notes(self, populated_wiki: Path, monkeypatch):
        """Whitespace-only-body notes are never embedded nor reported as candidates."""
        permanent = populated_wiki / "wiki" / "permanent"
        # A parseable note whose body is whitespace-only -- it must be skipped
        # *before* the batch so it neither wastes an embedding nor flags.
        (permanent / "blank-body-note.md").write_text("""\
---
id: perm-20260406-blank1
type: permanent
knowledge_type: idea
status: pending
confidence: low
scope: project
tags:
  - llm
source: "manual"
created: "2026-04-06T08:00:00"
---

""")

        captured: dict[str, list[str]] = {}

        def fake_batch(queries, db_path, table_name, threshold=0.85):
            captured["queries"] = list(queries)
            return [{"status": "unique", "top_score": 0.0, "matches": []} for _ in queries]

        monkeypatch.setattr("llm_wiki.commands.lint.check_duplicates_batch", fake_batch)
        monkeypatch.chdir(populated_wiki)
        result = runner.invoke(app, ["lint", "--contradictions", "--json"])
        assert result.exit_code == 0, result.stdout

        # The whitespace body never reaches the embedding batch.
        assert all(q.strip() for q in captured["queries"])
        # Only the three non-empty fixture notes were embedded.
        assert len(captured["queries"]) == 3

        contradictions = json.loads(result.stdout)["contradictions"]
        assert all(c["file"] != "blank-body-note.md" for c in contradictions)


# ---------------------------------------------------------------------------
# Smart fix-all
# ---------------------------------------------------------------------------


class TestSmartFixAll:
    """``kb lint --fix`` previews repairs; ``--apply`` writes the safe ones."""

    def test_fix_fills_missing_frontmatter(self, wiki_root: Path, sample_note_missing_fields: str, monkeypatch):
        permanent = wiki_root / "wiki" / "permanent"
        note = permanent / "incomplete-note.md"
        note.write_text(sample_note_missing_fields)

        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["lint", "--fix", "--apply"])
        assert result.exit_code == 0, result.stdout

        meta, _ = parse(note.read_text())
        assert meta["status"] == "pending"
        assert meta["confidence"] == "medium"
        assert meta["scope"] == "universal"
        assert meta["source"]
        assert meta["created"]

    def test_fix_replaces_rogue_tag(self, wiki_root: Path, monkeypatch):
        permanent = wiki_root / "wiki" / "permanent"
        note = permanent / "typo-tags.md"
        note.write_text("""\
---
id: perm-20260409-typo1
type: permanent
knowledge_type: fact
status: approved
confidence: medium
scope: universal
tags:
  - secuirty
  - performnce
source: "manual"
created: "2026-04-09T12:00:00"
---

# Typo Tags
""")
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["lint", "--fix", "--apply"])
        assert result.exit_code == 0, result.stdout

        meta, _ = parse(note.read_text())
        assert "security" in meta["tags"]
        assert "performance" in meta["tags"]
        assert "secuirty" not in meta["tags"]

    def test_dry_run_writes_nothing(self, wiki_root: Path, sample_note_missing_fields: str, monkeypatch):
        """Default --fix (no --apply) prints a plan but leaves files byte-identical."""
        permanent = wiki_root / "wiki" / "permanent"
        note = permanent / "incomplete-note.md"
        note.write_text(sample_note_missing_fields)
        before = note.read_text()

        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["lint", "--fix"])
        assert result.exit_code == 0, result.stdout
        assert note.read_text() == before
        assert "dry run" in result.stdout.lower()

    def test_fix_survives_vector_backend_failure(self, populated_wiki: Path, monkeypatch):
        """``--fix`` must not crash if the vector backend dies while suggesting links.

        Orphan suggestions are optional, so a failing ``search_index`` degrades to
        "no suggestion" (None) rather than propagating and aborting the fix run.
        """

        def boom(*_args, **_kwargs):
            msg = "vector backend unavailable"
            raise RuntimeError(msg)

        monkeypatch.setattr("llm_wiki.commands.lint.search_index", boom)
        monkeypatch.chdir(populated_wiki)
        result = runner.invoke(app, ["lint", "--fix", "--json"])
        assert result.exit_code == 0, result.stdout

        plan = json.loads(result.stdout)
        # orphan-note.md is flagged but with no suggested link (backend failed).
        flagged = {o["file"]: o for o in plan["orphans_flagged"]}
        assert "orphan-note.md" in flagged
        assert flagged["orphan-note.md"]["suggested_link_from"] is None
