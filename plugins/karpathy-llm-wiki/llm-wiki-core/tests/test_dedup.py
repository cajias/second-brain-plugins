"""Tests for the dedup threshold resolution logic."""
from __future__ import annotations

import pytest

from llm_wiki.core.dedup import SOURCE_CLASS_THRESHOLDS, resolve_threshold


class TestSourceClassThresholds:
    def test_constant_has_required_keys(self):
        assert set(SOURCE_CLASS_THRESHOLDS.keys()) == {"chat", "doc", "book", "paper"}

    def test_thresholds_in_valid_range(self):
        for cls, t in SOURCE_CLASS_THRESHOLDS.items():
            assert 0.85 <= t <= 0.99, f"{cls}: {t} out of range"

    def test_book_looser_than_chat(self):
        assert SOURCE_CLASS_THRESHOLDS["book"] > SOURCE_CLASS_THRESHOLDS["chat"]

    def test_paper_looser_than_chat(self):
        assert SOURCE_CLASS_THRESHOLDS["paper"] > SOURCE_CLASS_THRESHOLDS["chat"]


class TestResolveThreshold:
    def test_known_class_returns_mapped_threshold(self):
        assert resolve_threshold("book") == SOURCE_CLASS_THRESHOLDS["book"]
        assert resolve_threshold("chat") == SOURCE_CLASS_THRESHOLDS["chat"]

    def test_none_returns_chat_default(self):
        assert resolve_threshold(None) == SOURCE_CLASS_THRESHOLDS["chat"]

    def test_empty_string_returns_chat_default(self):
        assert resolve_threshold("") == SOURCE_CLASS_THRESHOLDS["chat"]

    def test_unknown_class_raises(self):
        with pytest.raises(ValueError, match="unknown source_class"):
            resolve_threshold("podcast")

    def test_case_insensitive(self):
        assert resolve_threshold("BOOK") == SOURCE_CLASS_THRESHOLDS["book"]
        assert resolve_threshold("Book") == SOURCE_CLASS_THRESHOLDS["book"]
