"""Tests for frontmatter parsing, dumping, and validation.

Covers the schema relaxation that allows two valid shapes:
  - canonical: ``type: permanent`` + ``knowledge_type: <type>``
  - simplified: ``type: <knowledge-type>`` (``type`` doubles as knowledge type)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from llm_wiki.core.frontmatter import (
    KNOWLEDGE_TYPES,
    RECOMMENDED_FIELDS,
    REQUIRED_FIELDS,
    dump,
    get_knowledge_type,
    parse,
    parse_file,
    validate,
)


if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


CANONICAL_META = {
    "id": "perm-20260417-abc12",
    "type": "permanent",
    "knowledge_type": "pattern",
    "status": "pending",
    "confidence": "medium",
    "scope": "universal",
    "tags": ["api-design"],
    "source": "raw/inbox/foo.md",
    "created": "2026-04-17T00:00:00",
}


SIMPLIFIED_META = {
    "title": "Some title",
    "type": "pattern",
    "tags": ["api-design"],
    "source": "raw/inbox/foo.md",
    "created": "2026-04-17",
}


# ---------------------------------------------------------------------------
# parse / dump round-trip
# ---------------------------------------------------------------------------


class TestParseAndDump:
    def test_parse_extracts_frontmatter_and_body(self):
        content = "---\nid: perm-20260417-abc12\ntype: permanent\n---\n\n# Body\n"
        meta, body = parse(content)
        assert meta["id"] == "perm-20260417-abc12"
        assert meta["type"] == "permanent"
        assert "# Body" in body

    def test_parse_no_frontmatter_returns_empty_meta(self):
        meta, body = parse("No frontmatter here.\n")
        assert meta == {}
        assert body == "No frontmatter here.\n"

    def test_parse_malformed_yaml_returns_empty_meta(self):
        content = "---\nkey: [unclosed\n---\n\nBody\n"
        meta, _ = parse(content)
        assert meta == {}

    def test_parse_file_reads_from_disk(self, tmp_path: Path):
        f = tmp_path / "note.md"
        f.write_text("---\ntype: permanent\n---\n\nBody\n", encoding="utf-8")
        meta, body = parse_file(f)
        assert meta["type"] == "permanent"
        assert "Body" in body

    def test_dump_emits_ordered_fields(self):
        out = dump(CANONICAL_META, "\n# Body\n")
        # id should come before type
        assert out.index("id:") < out.index("type:")
        # knowledge_type should come before status
        assert out.index("knowledge_type:") < out.index("status:")
        # tags listed as block sequence
        assert "  - api-design" in out

    def test_dump_preserves_body_trailing_newline(self):
        out = dump(CANONICAL_META, "Body without newline")
        assert out.endswith("\n")

    def test_dump_handles_extra_keys(self):
        meta = {**CANONICAL_META, "custom_field": "x", "extra_list": ["a", "b"]}
        out = dump(meta, "")
        assert "custom_field:" in out
        assert "  - a" in out


# ---------------------------------------------------------------------------
# get_knowledge_type — either-or resolution
# ---------------------------------------------------------------------------


class TestGetKnowledgeType:
    def test_canonical_schema_returns_knowledge_type_field(self):
        assert get_knowledge_type(CANONICAL_META) == "pattern"

    def test_simplified_schema_returns_type_field(self):
        assert get_knowledge_type(SIMPLIFIED_META) == "pattern"

    def test_type_permanent_without_knowledge_type_returns_none(self):
        meta = {"type": "permanent", "tags": []}
        assert get_knowledge_type(meta) is None

    def test_invalid_knowledge_type_not_accepted(self):
        meta = {"type": "permanent", "knowledge_type": "bogus"}
        assert get_knowledge_type(meta) is None

    def test_non_string_values_return_none(self):
        assert get_knowledge_type({"type": 42}) is None
        assert get_knowledge_type({"knowledge_type": None}) is None

    def test_canonical_takes_priority_over_type_alias(self):
        meta = {"type": "pattern", "knowledge_type": "fact"}
        # knowledge_type should win when both are present and valid
        assert get_knowledge_type(meta) == "fact"

    def test_all_knowledge_types_resolvable_via_simplified(self):
        for kt in KNOWLEDGE_TYPES:
            assert get_knowledge_type({"type": kt}) == kt


# ---------------------------------------------------------------------------
# validate — either-or rule + recommended fields
# ---------------------------------------------------------------------------


class TestValidate:
    def test_canonical_schema_is_valid(self):
        assert validate(CANONICAL_META) == []

    def test_simplified_schema_is_valid(self):
        assert validate(SIMPLIFIED_META) == []

    def test_missing_required_fields_produce_errors(self):
        errors = validate({"type": "pattern"})
        for field in REQUIRED_FIELDS:
            assert any(field in err for err in errors), f"Expected error for missing {field}, got {errors}"

    def test_missing_knowledge_type_produces_error(self):
        # Note: has tags/source/created but no valid knowledge-type anywhere
        meta = {
            "type": "permanent",
            "tags": ["api-design"],
            "source": "foo.md",
            "created": "2026-04-17",
        }
        errors = validate(meta)
        assert any("knowledge type" in err.lower() for err in errors)

    def test_recommended_fields_absent_does_not_error(self):
        # Simplified schema omits id/status/confidence/scope — no errors expected
        errors = validate(SIMPLIFIED_META)
        assert errors == []
        # Sanity: RECOMMENDED_FIELDS are indeed absent
        for field in RECOMMENDED_FIELDS:
            assert field not in SIMPLIFIED_META

    def test_invalid_enum_value_flagged(self):
        meta = {**CANONICAL_META, "status": "not-a-status"}
        errors = validate(meta)
        assert any("status" in err for err in errors)

    def test_invalid_knowledge_type_value_flagged(self):
        meta = {**CANONICAL_META, "knowledge_type": "bogus"}
        errors = validate(meta)
        assert any("knowledge_type" in err for err in errors)

    def test_type_accepts_both_permanent_and_knowledge_types(self):
        # Both schemas should pass the VALID_VALUES["type"] check
        canonical = validate(CANONICAL_META)
        simplified = validate(SIMPLIFIED_META)
        assert canonical == []
        assert simplified == []

    def test_tags_over_limit_flagged(self):
        meta = {**CANONICAL_META, "tags": [f"tag-{i}" for i in range(8)]}
        errors = validate(meta)
        assert any("Too many tags" in err for err in errors)

    def test_empty_metadata_yields_multiple_errors(self):
        errors = validate({})
        # Missing all required fields + knowledge type
        assert len(errors) >= len(REQUIRED_FIELDS) + 1


# ---------------------------------------------------------------------------
# reviewed — overwrite-protection enum
# ---------------------------------------------------------------------------


class TestReviewedField:
    def test_reviewed_true_string_is_valid(self):
        meta = {**CANONICAL_META, "reviewed": "true"}
        assert validate(meta) == []

    def test_reviewed_false_string_is_valid(self):
        meta = {**CANONICAL_META, "reviewed": "false"}
        assert validate(meta) == []

    def test_reviewed_yaml_boolean_is_valid(self):
        # `reviewed: true` in YAML parses to Python bool True, which validate()
        # stringifies to "True". Real human-reviewed notes carry this form.
        content = (
            "---\n" + "\n".join(f"{k}: {v}" for k, v in SIMPLIFIED_META.items()) + "\nreviewed: true\n---\n\nBody\n"
        )
        meta, _ = parse(content)
        assert meta["reviewed"] is True  # parsed as a bool, not a string
        assert validate(meta) == []

    def test_reviewed_python_bools_are_valid(self):
        assert validate({**CANONICAL_META, "reviewed": True}) == []
        assert validate({**CANONICAL_META, "reviewed": False}) == []

    def test_reviewed_bogus_value_flagged(self):
        meta = {**CANONICAL_META, "reviewed": "maybe"}
        errors = validate(meta)
        assert any("reviewed" in err for err in errors)

    def test_reviewed_in_ordered_fields_after_status(self):
        from llm_wiki.core.frontmatter import ORDERED_FIELDS

        assert ORDERED_FIELDS.index("reviewed") == ORDERED_FIELDS.index("status") + 1


# ---------------------------------------------------------------------------
# contradiction — optional recommended-tier mapping
# ---------------------------------------------------------------------------


class TestContradictionField:
    def test_valid_contradiction_accepted(self):
        meta = {**CANONICAL_META, "contradiction": {"status": "detected", "with": "[[other-note]]"}}
        assert validate(meta) == []

    def test_absent_contradiction_is_ok(self):
        assert validate(CANONICAL_META) == []

    def test_invalid_contradiction_status_flagged(self):
        meta = {**CANONICAL_META, "contradiction": {"status": "bogus", "with": "[[x]]"}}
        errors = validate(meta)
        assert any("contradiction.status" in err for err in errors)

    def test_contradiction_missing_with_flagged(self):
        meta = {**CANONICAL_META, "contradiction": {"status": "resolved"}}
        errors = validate(meta)
        assert any("contradiction.with" in err for err in errors)

    def test_contradiction_not_a_mapping_flagged(self):
        meta = {**CANONICAL_META, "contradiction": "just-a-string"}
        errors = validate(meta)
        assert any("contradiction" in err for err in errors)

    def test_all_contradiction_statuses_accepted(self):
        for status in ("detected", "review-passed", "resolved", "unresolved"):
            meta = {**CANONICAL_META, "contradiction": {"status": status, "with": "[[x]]"}}
            assert validate(meta) == [], f"status {status} should be valid"

    def test_contradiction_mapping_dumps_as_block_yaml_and_round_trips(self):
        meta = {**CANONICAL_META, "contradiction": {"status": "detected", "with": "[[other-note]]"}}
        out = dump(meta, "\n# Body\n")
        # Serialized as a YAML block mapping -- never a Python dict repr.
        assert "contradiction:\n  status: detected\n" in out
        assert "{'status'" not in out  # no str(dict) leakage
        # And it survives a parse round-trip unchanged.
        reparsed, _ = parse(out)
        assert reparsed["contradiction"] == {"status": "detected", "with": "[[other-note]]"}
