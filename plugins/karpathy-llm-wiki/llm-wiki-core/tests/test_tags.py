"""Tests for the single core tag normalizer."""

from __future__ import annotations

from llm_wiki.core.tags import normalize_tags


class TestNormalizeTags:
    def test_list_passthrough_strips_and_drops_empties(self):
        assert normalize_tags(["  a ", "b", "", "  "]) == ["a", "b"]

    def test_csv_string_split(self):
        assert normalize_tags("a, b ,c") == ["a", "b", "c"]

    def test_none_returns_empty_list(self):
        assert normalize_tags(None) == []

    def test_scalar_becomes_single_element(self):
        assert normalize_tags("solo") == ["solo"]

    def test_empty_string_returns_empty_list(self):
        assert normalize_tags("") == []

    def test_non_string_scalar_coerced(self):
        assert normalize_tags(42) == ["42"]
