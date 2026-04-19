"""Tests for ``kb migrate-frontmatter`` — simplified -> canonical schema."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from llm_wiki.cli import app
from llm_wiki.core.frontmatter import (
    KNOWLEDGE_TYPES,
    parse_file,
    validate,
)


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


SIMPLIFIED_NOTE = """\
---
title: Some simplified note
type: pattern
tags:
  - api-design
source: "raw/inbox/foo.md"
created: "2026-04-17"
---

# Some simplified note

Body content.
"""


CANONICAL_NOTE = """\
---
id: perm-20260417-abc12
type: permanent
knowledge_type: pattern
status: pending
confidence: medium
scope: universal
tags:
  - api-design
source: "raw/inbox/foo.md"
created: "2026-04-17T00:00:00"
---

# Canonical Note
"""


def _run(wiki_root: Path, *args, monkeypatch) -> object:
    monkeypatch.chdir(wiki_root)
    return runner.invoke(app, ["migrate-frontmatter", *args])


class TestMigrateFrontmatter:
    def test_dry_run_does_not_modify_files(self, wiki_root: Path, monkeypatch):
        permanent = wiki_root / "wiki" / "permanent"
        note_path = permanent / "simp.md"
        note_path.write_text(SIMPLIFIED_NOTE)
        original = note_path.read_text()

        result = _run(wiki_root, "--json", monkeypatch=monkeypatch)
        assert result.exit_code == 0
        report = json.loads(result.stdout)
        assert report["mode"] == "dry-run"
        assert report["migrated_count"] == 1
        # File content unchanged
        assert note_path.read_text() == original

    def test_apply_rewrites_simplified_to_canonical(self, wiki_root: Path, monkeypatch):
        permanent = wiki_root / "wiki" / "permanent"
        note_path = permanent / "simp.md"
        note_path.write_text(SIMPLIFIED_NOTE)

        result = _run(wiki_root, "--apply", "--json", monkeypatch=monkeypatch)
        assert result.exit_code == 0
        report = json.loads(result.stdout)
        assert report["mode"] == "apply"
        assert report["migrated_count"] == 1

        meta, _ = parse_file(note_path)
        assert meta["type"] == "permanent"
        assert meta["knowledge_type"] == "pattern"
        assert meta["status"] == "pending"
        assert meta["confidence"] == "medium"
        assert meta["scope"] == "universal"
        assert meta["id"].startswith("perm-2026")
        # Post-migration note should pass validation
        assert validate(meta) == []

    def test_already_canonical_skipped(self, wiki_root: Path, monkeypatch):
        permanent = wiki_root / "wiki" / "permanent"
        note_path = permanent / "canonical.md"
        note_path.write_text(CANONICAL_NOTE)
        original = note_path.read_text()

        result = _run(wiki_root, "--apply", "--json", monkeypatch=monkeypatch)
        assert result.exit_code == 0
        report = json.loads(result.stdout)
        assert report["migrated_count"] == 0
        assert report["skipped_canonical_count"] == 1
        # Untouched
        assert note_path.read_text() == original

    def test_idempotent(self, wiki_root: Path, monkeypatch):
        """Running migrate twice produces no changes the second time."""
        permanent = wiki_root / "wiki" / "permanent"
        note_path = permanent / "simp.md"
        note_path.write_text(SIMPLIFIED_NOTE)

        # First pass
        result1 = _run(wiki_root, "--apply", "--json", monkeypatch=monkeypatch)
        assert result1.exit_code == 0
        after_first = note_path.read_text()

        # Second pass should be a no-op
        result2 = _run(wiki_root, "--apply", "--json", monkeypatch=monkeypatch)
        assert result2.exit_code == 0
        report2 = json.loads(result2.stdout)
        assert report2["migrated_count"] == 0
        assert note_path.read_text() == after_first

    def test_id_uses_created_date_when_available(self, wiki_root: Path, monkeypatch):
        permanent = wiki_root / "wiki" / "permanent"
        note_path = permanent / "no-date-in-name.md"
        note_path.write_text("""\
---
title: Dated note
type: fact
tags:
  - api-design
source: "raw/inbox/x.md"
created: "2025-08-14"
---

# Body
""")
        result = _run(wiki_root, "--apply", "--json", monkeypatch=monkeypatch)
        assert result.exit_code == 0
        meta, _ = parse_file(note_path)
        assert meta["id"].startswith("perm-20250814-")

    def test_missing_source_gets_sentinel(self, wiki_root: Path, monkeypatch):
        """Notes without source get a 'migrated:unknown' marker so lint passes."""
        permanent = wiki_root / "wiki" / "permanent"
        note_path = permanent / "no-source.md"
        note_path.write_text("""\
---
title: No source
type: idea
tags:
  - api-design
created: "2026-01-01"
---

# Body
""")
        result = _run(wiki_root, "--apply", "--json", monkeypatch=monkeypatch)
        assert result.exit_code == 0
        meta, _ = parse_file(note_path)
        assert meta["source"] == "migrated:unknown"

    def test_all_knowledge_types_migrated_correctly(self, wiki_root: Path, monkeypatch):
        permanent = wiki_root / "wiki" / "permanent"
        for i, kt in enumerate(KNOWLEDGE_TYPES):
            (permanent / f"note-{i}.md").write_text(f"""\
---
title: Note {kt}
type: {kt}
tags:
  - api-design
source: "x.md"
created: "2026-04-17"
---

# Body
""")
        result = _run(wiki_root, "--apply", "--json", monkeypatch=monkeypatch)
        report = json.loads(result.stdout)
        assert report["migrated_count"] == len(KNOWLEDGE_TYPES)
        for i, kt in enumerate(KNOWLEDGE_TYPES):
            meta, _ = parse_file(permanent / f"note-{i}.md")
            assert meta["type"] == "permanent"
            assert meta["knowledge_type"] == kt

    def test_no_permanent_dir_exits_cleanly(self, wiki_root: Path, monkeypatch):
        import shutil

        shutil.rmtree(wiki_root / "wiki" / "permanent")
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["migrate-frontmatter"])
        assert result.exit_code == 0
        assert "Nothing to migrate" in result.stdout
