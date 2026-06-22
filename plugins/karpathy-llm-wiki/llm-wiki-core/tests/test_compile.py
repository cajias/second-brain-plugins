"""Tests for ``kb compile`` — note compilation, dedup checking, and manifest management."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from llm_wiki.cli import app
from llm_wiki.commands.compile_cmd import _tag_candidate


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


# ---------------------------------------------------------------------------
# Dedup checking
# ---------------------------------------------------------------------------


class TestCheckDedup:
    """``kb compile --check-dedup`` classifies content similarity.

    Thresholds (from original kb_compile.py):
      >= 0.92  -> duplicate
      0.80-0.91 -> similar
      < 0.80   -> unique
    """

    def test_unique_when_no_index(self, wiki_root: Path, monkeypatch, mock_embedding_model):
        """With no LanceDB index, dedup should default to 'unique'."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            ["compile", "--check-dedup", "completely novel unrelated content xyz123"],
        )
        assert result.exit_code == 0
        assert "unique" in result.stdout.lower()

    def test_check_dedup_json(self, wiki_root: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            ["compile", "--check-dedup", "novel content", "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] in ("unique", "similar", "duplicate")
        assert "top_score" in data
        assert isinstance(data["matches"], list)

    def test_check_dedup_returns_valid_status(self, wiki_root: Path, monkeypatch, mock_embedding_model):
        """Status must be one of the three defined classes."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            ["compile", "--check-dedup", "API gateway patterns", "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] in ("unique", "similar", "duplicate", "error")


class TestDedupModule:
    """Direct tests for the dedup.check_duplicate function."""

    def test_returns_unique_with_no_index(self, wiki_root: Path, mock_embedding_model):
        from llm_wiki.core.dedup import check_duplicate

        result = check_duplicate("test query", wiki_root / ".lancedb", "notes")
        assert result["status"] == "unique"
        assert result["top_score"] == 0.0
        assert result["matches"] == []

    def test_batch_returns_one_result_per_query_in_order(self, wiki_root: Path, mock_embedding_model):
        """check_duplicates_batch returns one result per query, same order."""
        from llm_wiki.core.dedup import check_duplicates_batch

        queries = ["first query", "second query", "third query"]
        results = check_duplicates_batch(queries, wiki_root / ".lancedb", "notes")
        assert len(results) == len(queries)
        for res in results:
            assert res["status"] in ("unique", "similar", "duplicate")
            assert "top_score" in res
            assert isinstance(res["matches"], list)

    def test_batch_matches_single_results(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Batch results equal the per-query single-call results (with an index)."""
        from llm_wiki.core.dedup import check_duplicate, check_duplicates_batch

        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        db_path = populated_wiki / ".lancedb"

        queries = ["Token Refresh Strategy", "completely novel xyz123"]
        batch = check_duplicates_batch(queries, db_path, "notes")
        singles = [check_duplicate(q, db_path, "notes") for q in queries]
        assert [r["status"] for r in batch] == [r["status"] for r in singles]

    def test_batch_empty_queries(self, wiki_root: Path, mock_embedding_model):
        from llm_wiki.core.dedup import check_duplicates_batch

        assert check_duplicates_batch([], wiki_root / ".lancedb", "notes") == []


class TestCheckDedupBatchCLI:
    """``kb compile --check-dedup-batch`` reads a JSON list and emits keyed results."""

    def test_batch_from_file(self, wiki_root: Path, tmp_path: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(wiki_root)
        batch_file = tmp_path / "batch.json"
        batch_file.write_text(
            json.dumps(
                [
                    {"key": "k1", "query": "some idea about caching"},
                    {"key": "k2", "query": "another distinct idea"},
                ]
            )
        )
        result = runner.invoke(app, ["compile", "--check-dedup-batch", str(batch_file)])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert [item["key"] for item in data] == ["k1", "k2"]
        for item in data:
            assert item["status"] in ("unique", "similar", "duplicate")
            assert "top_score" in item
            assert isinstance(item["matches"], list)

    def test_batch_from_stdin(self, wiki_root: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(wiki_root)
        payload = json.dumps([{"key": "only", "query": "novel content"}])
        result = runner.invoke(app, ["compile", "--check-dedup-batch", "-"], input=payload)
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["key"] == "only"

    def test_batch_malformed_json_errors(self, wiki_root: Path, tmp_path: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(wiki_root)
        batch_file = tmp_path / "bad.json"
        batch_file.write_text("{not json")
        result = runner.invoke(app, ["compile", "--check-dedup-batch", str(batch_file)])
        assert result.exit_code != 0

    def test_batch_missing_fields_errors(self, wiki_root: Path, tmp_path: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(wiki_root)
        batch_file = tmp_path / "missing.json"
        batch_file.write_text(json.dumps([{"key": "k1"}]))
        result = runner.invoke(app, ["compile", "--check-dedup-batch", str(batch_file)])
        assert result.exit_code != 0


class TestWriteNoteEmptySlug:
    """Punctuation/emoji-only title must not produce a hidden `.md` filename."""

    def test_empty_slug_falls_back_to_note_id(self, wiki_root: Path, monkeypatch, mock_embedding_model):
        """_write_note with a punctuation-only title must produce a non-empty, non-'.md' filename."""
        import re

        monkeypatch.chdir(wiki_root)
        from llm_wiki.commands.compile_cmd import _write_note
        from llm_wiki.core.config import load_config

        cfg = load_config()
        result = _write_note(
            "!!!---???",  # pure punctuation — slugify returns ""
            "concept",
            ["llm"],
            "high",
            "manual",
            "This is the body.",
            cfg,
        )
        filename = result["filename"]
        assert filename != ".md", "Empty-slug must not produce a hidden file"
        assert not filename.startswith("."), "filename must not start with a dot"
        assert filename.endswith(".md")
        # The fallback filename should be the note_id (UUID-like pattern)
        assert re.match(r"[a-z0-9-]+\.md$", filename), f"Expected id-based filename, got: {filename!r}"


# ---------------------------------------------------------------------------
# Write note
# ---------------------------------------------------------------------------


class TestWriteNote:
    """``kb compile --write-note`` creates a permanent note."""

    def _write_note_args(self, **overrides) -> list[str]:
        defaults = {
            "title": "Test Pattern Note",
            "knowledge-type": "pattern",
            "tags": "architecture,api-design",
            "confidence": "high",
            "source": "session-test",
            "body": "This is the body of the note.",
        }
        defaults.update(overrides)
        args = ["compile", "--write-note"]
        for key, val in defaults.items():
            args.extend([f"--{key}", val])
        return args

    def test_creates_file_with_frontmatter(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, self._write_note_args())
        assert result.exit_code == 0

        permanent = wiki_root / "wiki" / "permanent"
        md_files = list(permanent.glob("*.md"))
        assert len(md_files) >= 1, "No note written to wiki/permanent/"

        content = md_files[0].read_text()
        assert "---" in content
        assert "Test Pattern Note" in content
        assert "pattern" in content
        assert "architecture" in content

    def test_generates_perm_id(self, wiki_root: Path, monkeypatch):
        """Each note should get a unique perm-YYYYMMDD-XXXXX id."""
        monkeypatch.chdir(wiki_root)
        runner.invoke(app, self._write_note_args())

        permanent = wiki_root / "wiki" / "permanent"
        md_files = list(permanent.glob("*.md"))
        content = md_files[0].read_text()
        assert "id: perm-" in content

    def test_validates_tags_against_taxonomy(self, wiki_root: Path, monkeypatch):
        """Invalid tags should produce a warning."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            self._write_note_args(tags="not-a-valid-tag,also-bad"),
        )
        assert result.exit_code == 0
        assert "warning" in result.stdout.lower()

    def test_dry_run_does_not_write(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            [*self._write_note_args(title="Dry Run Note"), "--dry-run"],
        )
        assert result.exit_code == 0

        permanent = wiki_root / "wiki" / "permanent"
        matching = list(permanent.glob("*dry*"))
        assert len(matching) == 0, "dry-run should not write a file"

    def test_dry_run_shows_preview(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            [*self._write_note_args(), "--dry-run"],
        )
        assert result.exit_code == 0
        assert "dry run" in result.stdout.lower()

    def test_write_note_uses_canonical_dump(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        runner.invoke(app, self._write_note_args(tags="architecture,api-design"))
        permanent = wiki_root / "wiki" / "permanent"
        content = next(permanent.glob("*.md")).read_text()
        assert content.startswith("---\n")
        assert "knowledge_type: pattern\n" in content
        assert "tags:\n  - architecture\n  - api-design\n" in content
        assert 'source: "session-test"\n' in content

    def test_missing_fields_error(self, wiki_root: Path, monkeypatch):
        """--write-note without all required fields should error."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["compile", "--write-note", "--title", "Only Title"])
        assert result.exit_code != 0

    def test_tool_tags_accepted_by_taxonomy(self, wiki_root: Path, monkeypatch):
        """Tool knowledge_type + tool-cli/phase-testing tags must not warn."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            self._write_note_args(**{"knowledge-type": "tool", "tags": "tool-cli,phase-testing", "title": "Some Tool"}),
        )
        assert result.exit_code == 0
        assert "not in approved" not in result.stdout.lower()
        assert "not in approved list" not in result.stdout.lower()


# ---------------------------------------------------------------------------
# Mark processed
# ---------------------------------------------------------------------------


class TestMarkProcessed:
    """``kb compile --mark-processed`` updates manifest entry status."""

    def test_marks_entry_processed(self, manifest_with_entries: Path, monkeypatch):
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(app, ["compile", "--mark-processed", "ingest-aaa11111"])
        assert result.exit_code == 0

        manifest = manifest_with_entries / "raw" / "inbox" / ".manifest.json"
        entries = json.loads(manifest.read_text())
        target = next(e for e in entries if e["id"] == "ingest-aaa11111")
        assert target["status"] == "processed"
        assert "processed_at" in target

    def test_mark_nonexistent_entry_errors(self, manifest_with_entries: Path, monkeypatch):
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(app, ["compile", "--mark-processed", "nonexistent-id"])
        assert result.exit_code != 0 or "not found" in result.stdout.lower()

    def test_marks_comma_separated_ids(self, manifest_with_entries: Path, monkeypatch):
        """Comma-separated ids mark all entries with a single manifest write."""
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(
            app,
            ["compile", "--mark-processed", "ingest-aaa11111,ingest-bbb22222"],
        )
        assert result.exit_code == 0

        manifest = manifest_with_entries / "raw" / "inbox" / ".manifest.json"
        entries = json.loads(manifest.read_text())
        statuses = {e["id"]: e["status"] for e in entries}
        assert statuses["ingest-aaa11111"] == "processed"
        assert statuses["ingest-bbb22222"] == "processed"
        # No leftover temp file from the atomic write.
        assert not (manifest_with_entries / "raw" / "inbox" / ".manifest.json.tmp").exists()

    def test_marks_repeated_flag_ids(self, manifest_with_entries: Path, monkeypatch):
        """Repeated --mark-processed flags mark all entries."""
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(
            app,
            [
                "compile",
                "--mark-processed",
                "ingest-aaa11111",
                "--mark-processed",
                "ingest-bbb22222",
            ],
        )
        assert result.exit_code == 0

        manifest = manifest_with_entries / "raw" / "inbox" / ".manifest.json"
        entries = json.loads(manifest.read_text())
        statuses = {e["id"]: e["status"] for e in entries}
        assert statuses["ingest-aaa11111"] == "processed"
        assert statuses["ingest-bbb22222"] == "processed"

    def test_partial_match_marks_found_reports_missing(self, manifest_with_entries: Path, monkeypatch):
        """One valid + one bogus id: valid marked, exit 0, bogus in not_found."""
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(
            app,
            ["compile", "--mark-processed", "ingest-aaa11111,bogus-id", "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["processed"] == ["ingest-aaa11111"]
        assert data["not_found"] == ["bogus-id"]

        manifest = manifest_with_entries / "raw" / "inbox" / ".manifest.json"
        entries = json.loads(manifest.read_text())
        target = next(e for e in entries if e["id"] == "ingest-aaa11111")
        assert target["status"] == "processed"

    def test_all_bogus_ids_error(self, manifest_with_entries: Path, monkeypatch):
        """No requested id found -> non-zero exit."""
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(app, ["compile", "--mark-processed", "x,y"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# List inbox
# ---------------------------------------------------------------------------


class TestListInbox:
    """``kb compile --list-inbox`` returns inbox entries."""

    def test_list_inbox_returns_entries(self, manifest_with_entries: Path, monkeypatch):
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(app, ["compile", "--list-inbox"])
        assert result.exit_code == 0
        assert "ingest-aaa11111" in result.stdout

    def test_list_inbox_json(self, manifest_with_entries: Path, monkeypatch):
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(app, ["compile", "--list-inbox", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 2  # both pending and processed

    def test_list_inbox_empty(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["compile", "--list-inbox"])
        assert result.exit_code == 0
        assert "empty" in result.stdout.lower() or "no" in result.stdout.lower()

    def test_no_mode_specified_errors(self, wiki_root: Path, monkeypatch):
        """Running ``compile`` with no action flag should error."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["compile"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Tag candidate
# ---------------------------------------------------------------------------


def _make_cfg(tmp_path: Path):
    """Build a minimal WikiConfig pointing into tmp_path."""
    from llm_wiki.core.config import WikiConfig

    return WikiConfig(
        project_root=tmp_path,
        vault_root=tmp_path / "vault",
        raw_inbox=tmp_path / "raw" / "inbox",
        raw_sessions=tmp_path / "raw" / "sessions",
        raw_artifacts=tmp_path / "raw" / "artifacts",
        raw_web=tmp_path / "raw" / "web",
        wiki_permanent=tmp_path / "wiki" / "permanent",
        wiki_index=tmp_path / "wiki" / "_index",
        wiki_meta=tmp_path / "wiki" / "_meta",
        output=tmp_path / "output",
        fleeting=tmp_path / "fleeting",
        db_path=tmp_path / ".lancedb",
        table_name="notes",
        compile_batch_size=10,
        auto_link_threshold=0.75,
        lint_orphan_threshold=0,
        lint_tag_compliance="strict",
        lint_index_staleness_hours=24,
        lint_index_min_coverage_pct=80,
        query_default_limit=10,
    )


class TestTagCandidate:
    def test_tags_existing_entry_with_candidate_metadata(self, tmp_path):
        manifest = tmp_path / "raw" / "inbox" / ".manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                [{"id": "ingest-abc", "source": "url", "type": "web", "file": "raw/web/x.md", "status": "pending"}]
            )
        )
        cfg = _make_cfg(tmp_path)

        result = _tag_candidate(
            entry_id="ingest-abc",
            verdict="yes",
            score=0.85,
            reason="concrete pattern with measurable result",
            suggested_type="pattern",
            suggested_tags=["agent-patterns", "llm"],
            cfg=cfg,
        )

        assert result["success"] is True
        loaded = json.loads(manifest.read_text())
        entry = loaded[0]
        assert entry["candidate"]["verdict"] == "yes"
        assert entry["candidate"]["score"] == 0.85
        assert entry["candidate"]["reason"] == "concrete pattern with measurable result"
        assert entry["candidate"]["suggested_type"] == "pattern"
        assert entry["candidate"]["suggested_tags"] == ["agent-patterns", "llm"]
        assert "tagged_at" in entry["candidate"]

    def test_rejects_unknown_entry_id(self, tmp_path):
        manifest = tmp_path / "raw" / "inbox" / ".manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps([{"id": "ingest-abc", "status": "pending"}]))
        cfg = _make_cfg(tmp_path)

        result = _tag_candidate(
            entry_id="ingest-missing",
            verdict="no",
            score=0.1,
            reason="not found",
            suggested_type=None,
            suggested_tags=[],
            cfg=cfg,
        )

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_rejects_invalid_verdict(self, tmp_path):
        manifest = tmp_path / "raw" / "inbox" / ".manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps([{"id": "ingest-abc", "status": "pending"}]))
        cfg = _make_cfg(tmp_path)

        result = _tag_candidate(
            entry_id="ingest-abc",
            verdict="probably",  # not yes/no/maybe
            score=0.5,
            reason="ambiguous",
            suggested_type=None,
            suggested_tags=[],
            cfg=cfg,
        )

        assert result["success"] is False
        assert "verdict" in result["error"].lower()

    def test_rejects_score_above_one(self, tmp_path):
        manifest = tmp_path / "raw" / "inbox" / ".manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps([{"id": "ingest-abc", "status": "pending"}]))
        cfg = _make_cfg(tmp_path)

        result = _tag_candidate(
            entry_id="ingest-abc",
            verdict="yes",
            score=1.5,
            reason="hallucinated score",
            suggested_type=None,
            suggested_tags=[],
            cfg=cfg,
        )

        assert result["success"] is False
        assert "score" in result["error"].lower()
        # Manifest must NOT have been mutated
        loaded = json.loads(manifest.read_text())
        assert "candidate" not in loaded[0]

    def test_rejects_score_below_zero(self, tmp_path):
        manifest = tmp_path / "raw" / "inbox" / ".manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps([{"id": "ingest-abc", "status": "pending"}]))
        cfg = _make_cfg(tmp_path)

        result = _tag_candidate(
            entry_id="ingest-abc",
            verdict="yes",
            score=-0.1,
            reason="negative score",
            suggested_type=None,
            suggested_tags=[],
            cfg=cfg,
        )

        assert result["success"] is False
        assert "score" in result["error"].lower()

    def test_warns_on_unknown_suggested_type(self, tmp_path):
        manifest = tmp_path / "raw" / "inbox" / ".manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps([{"id": "ingest-abc", "status": "pending"}]))
        # Seed taxonomy file with the known knowledge_types
        meta = tmp_path / "wiki" / "_meta"
        meta.mkdir(parents=True)
        (meta / "tag-taxonomy.md").write_text(
            "# Taxonomy\n\n"
            "## Knowledge Types\n\n"
            "| Type | Use |\n|---|---|\n"
            "| `fact` | x |\n| `pattern` | x |\n| `decision` | x |\n\n"
            "## Approved Tags\n\n"
            "| Tag | Use |\n|---|---|\n"
            "| `llm` | x |\n| `agent-patterns` | x |\n"
        )
        cfg = _make_cfg(tmp_path)

        result = _tag_candidate(
            entry_id="ingest-abc",
            verdict="yes",
            score=0.8,
            reason="bogus type",
            suggested_type="not-a-real-type",
            suggested_tags=[],
            cfg=cfg,
        )

        # The write succeeds (warnings are advisory) but the warning surfaces
        assert result["success"] is True
        assert "warnings" in result
        assert any("not-a-real-type" in w for w in result["warnings"])

    def test_cli_tag_candidate_flag(self, tmp_path, monkeypatch):
        # Set up minimal wiki + manifest
        wiki_root = tmp_path / "wiki"
        (wiki_root / "_meta").mkdir(parents=True)
        (wiki_root / "permanent").mkdir(parents=True)
        (tmp_path / "raw" / "inbox").mkdir(parents=True)
        (tmp_path / ".kb-config.yml").write_text("vault_root: .\n")
        (tmp_path / "raw" / "inbox" / ".manifest.json").write_text(
            json.dumps(
                [{"id": "ingest-abc", "source": "url", "type": "web", "file": "raw/web/x.md", "status": "pending"}]
            )
        )

        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app,
            [
                "compile",
                "--tag-candidate",
                "ingest-abc",
                "--verdict",
                "yes",
                "--score",
                "0.85",
                "--reason",
                "good pattern",
                "--suggested-type",
                "pattern",
                "--suggested-tags",
                "agent-patterns,llm",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["success"] is True

        loaded = json.loads((tmp_path / "raw" / "inbox" / ".manifest.json").read_text())
        assert loaded[0]["candidate"]["verdict"] == "yes"
        assert loaded[0]["candidate"]["suggested_tags"] == ["agent-patterns", "llm"]


# ---------------------------------------------------------------------------
# List inbox -- candidates-only filter
# ---------------------------------------------------------------------------


class TestListInboxCandidatesOnly:
    def test_filters_to_yes_candidates_by_default(self, tmp_path, monkeypatch):
        wiki_root = tmp_path / "wiki"
        (wiki_root / "_meta").mkdir(parents=True)
        (wiki_root / "permanent").mkdir(parents=True)
        (tmp_path / "raw" / "inbox").mkdir(parents=True)
        (tmp_path / ".kb-config.yml").write_text("vault_root: .\n")
        (tmp_path / "raw" / "inbox" / ".manifest.json").write_text(
            json.dumps(
                [
                    {
                        "id": "ingest-yes",
                        "status": "pending",
                        "candidate": {"verdict": "yes", "score": 0.9, "reason": "good"},
                    },
                    {
                        "id": "ingest-no",
                        "status": "pending",
                        "candidate": {"verdict": "no", "score": 0.05, "reason": "noise"},
                    },
                    {
                        "id": "ingest-maybe",
                        "status": "pending",
                        "candidate": {"verdict": "maybe", "score": 0.5, "reason": "borderline"},
                    },
                    {"id": "ingest-untagged", "status": "pending"},
                ]
            )
        )

        monkeypatch.chdir(tmp_path)
        from llm_wiki.cli import app

        runner = CliRunner()

        result = runner.invoke(app, ["compile", "--list-inbox", "--candidates-only", "--json"])

        assert result.exit_code == 0, result.output
        entries = json.loads(result.stdout)
        ids = [e["id"] for e in entries]
        assert ids == ["ingest-yes"]

    def test_include_maybe_with_flag(self, tmp_path, monkeypatch):
        wiki_root = tmp_path / "wiki"
        (wiki_root / "_meta").mkdir(parents=True)
        (wiki_root / "permanent").mkdir(parents=True)
        (tmp_path / "raw" / "inbox").mkdir(parents=True)
        (tmp_path / ".kb-config.yml").write_text("vault_root: .\n")
        (tmp_path / "raw" / "inbox" / ".manifest.json").write_text(
            json.dumps(
                [
                    {
                        "id": "ingest-yes",
                        "status": "pending",
                        "candidate": {"verdict": "yes", "score": 0.9, "reason": "good"},
                    },
                    {
                        "id": "ingest-maybe",
                        "status": "pending",
                        "candidate": {"verdict": "maybe", "score": 0.5, "reason": "borderline"},
                    },
                ]
            )
        )

        monkeypatch.chdir(tmp_path)
        from llm_wiki.cli import app

        runner = CliRunner()

        result = runner.invoke(
            app,
            [
                "compile",
                "--list-inbox",
                "--candidates-only",
                "--include-maybe",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        ids = [e["id"] for e in json.loads(result.stdout)]
        assert sorted(ids) == ["ingest-maybe", "ingest-yes"]


# ---------------------------------------------------------------------------
# Source-class dedup tuning
# ---------------------------------------------------------------------------


class TestCheckDedupSourceClass:
    """``kb compile --check-dedup --source-class book`` uses 0.94 threshold."""

    def test_book_class_uses_book_threshold(self, populated_wiki: Path, mock_embedding_model, monkeypatch):
        monkeypatch.chdir(populated_wiki)
        # Build the index so dedup has data
        runner.invoke(app, ["index"])
        result = runner.invoke(
            app,
            [
                "compile",
                "--check-dedup",
                "API Gateway Authentication Pattern with JWT validation",
                "--source-class",
                "book",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        # The known-existing populated_wiki note should produce a high score.
        # With source-class=book (0.94) it would NOT trip duplicate at 0.92,
        # but the test asserts the threshold actually got applied to status.
        assert "threshold" in data
        assert data["threshold"] == 0.94

    def test_unknown_source_class_errors(self, populated_wiki: Path, monkeypatch):
        monkeypatch.chdir(populated_wiki)
        result = runner.invoke(
            app,
            [
                "compile",
                "--check-dedup",
                "anything",
                "--source-class",
                "podcast",
            ],
        )
        assert result.exit_code != 0
        assert "podcast" in result.output.lower() or "unknown" in result.output.lower()

    def test_no_source_class_uses_chat_default(self, populated_wiki: Path, mock_embedding_model, monkeypatch):
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index"])
        result = runner.invoke(
            app,
            ["compile", "--check-dedup", "anything", "--json"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["threshold"] == 0.92
