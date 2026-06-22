"""Tests for the single core slugify helper."""

from __future__ import annotations

from llm_wiki.core.text import slugify


class TestSlugify:
    def test_basic_kebab_case(self):
        assert slugify("Hello World Pattern") == "hello-world-pattern"

    def test_strips_punctuation(self):
        assert slugify("API: design & versioning!") == "api-design-versioning"

    def test_collapses_repeated_separators(self):
        assert slugify("a   --  b") == "a-b"

    def test_respects_max_len_on_word_boundary(self):
        out = slugify("alpha beta gamma delta", max_len=12)
        assert len(out) <= 12
        assert not out.endswith("-")

    def test_default_max_len_is_80(self):
        long = "word " * 40
        assert len(slugify(long)) <= 80
