"""Tests for ``kb ingest-tool`` — URL router into the tool ingest contract."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from llm_wiki.commands import ingest_tool as it
from llm_wiki.core.github import GitHubNotFoundError, GitHubRateLimitError, GitHubTool
from llm_wiki.core.html_extract import ExtractedDoc


if TYPE_CHECKING:
    from pathlib import Path


def _cfg(wiki_root: Path):  # type: ignore[no-untyped-def]
    import os

    os.chdir(wiki_root)
    from llm_wiki.core.config import load_config

    return load_config()


def _read_manifest(wiki_root: Path) -> list[dict]:  # type: ignore[no-untyped-def]
    return json.loads((wiki_root / "raw" / "inbox" / ".manifest.json").read_text())  # type: ignore[return-value]


def _sample_tool() -> GitHubTool:
    return GitHubTool(
        readme_markdown="# Whisper\n\nASR model by OpenAI.",
        description="Robust ASR",
        topics=["asr", "speech"],
        language="Python",
        homepage="https://openai.com",
        stargazers_count=1234,
    )


def _never_github(_owner: str, _repo: str, _token: object) -> GitHubTool:
    """Stub that must never be called in generic-URL routing tests."""
    msg = "github_fetch must not be called for non-github URL"
    raise AssertionError(msg)


class TestToolMetaBlock:
    def test_block_has_url_and_meta(self) -> None:
        block = it.build_tool_meta_block(
            "https://github.com/openai/whisper",
            lang_or_host="Python",
            stars=1234,
            topics_or_keywords=["asr", "speech"],
            description="Robust ASR",
        )
        assert "tool: https://github.com/openai/whisper" in block
        assert "Python" in block
        assert "1234" in block
        assert "asr" in block
        assert "Robust ASR" in block

    def test_block_without_stars(self) -> None:
        block = it.build_tool_meta_block(
            "https://deepeval.com",
            lang_or_host="deepeval.com",
            stars=None,
            topics_or_keywords=[],
            description=None,
        )
        assert "tool: https://deepeval.com" in block
        assert "⭐" not in block

    def test_block_without_topics(self) -> None:
        block = it.build_tool_meta_block(
            "https://example.com",
            lang_or_host="example.com",
            stars=42,
            topics_or_keywords=[],
            description="Some tool",
        )
        assert "42" in block
        assert "Some tool" in block

    def test_block_format_html_comment(self) -> None:
        block = it.build_tool_meta_block(
            "https://github.com/a/b",
            lang_or_host="Go",
            stars=100,
            topics_or_keywords=["cli"],
            description=None,
        )
        assert block.startswith("<!-- tool:")
        assert "-->" in block


class TestIngestToolRouting:
    def test_github_url_routes_to_github(self, wiki_root: Path) -> None:
        """A full github.com URL must call github_fetch, not html_fetch."""
        cfg = _cfg(wiki_root)
        tool = _sample_tool()
        html_called: list[str] = []

        result = it._ingest_tool(
            "https://github.com/openai/whisper",
            cfg,
            github_fetch=lambda _o, _r, _t: tool,
            html_fetch=lambda url: html_called.append(url) or ExtractedDoc("", None, None),  # type: ignore[return-value]
        )

        assert html_called == [], "html_fetch must NOT be called for github.com URL"
        dest = cfg.project_root / result["dest"]
        body = dest.read_text()
        assert "Whisper" in body
        assert "tool: https://github.com/openai/whisper" in body

        manifest = _read_manifest(wiki_root)
        assert manifest[-1]["source_class"] == "tool"
        assert manifest[-1]["source"] == "https://github.com/openai/whisper"

    def test_generic_url_routes_to_trafilatura(self, wiki_root: Path) -> None:
        """A non-github URL must call html_fetch, never github_fetch."""
        cfg = _cfg(wiki_root)
        gh_called: list[tuple[str, str]] = []

        def _spy_github(owner: str, repo: str, _token: object) -> GitHubTool:
            gh_called.append((owner, repo))
            msg = "should not call github API for non-github URL"
            raise AssertionError(msg)

        result = it._ingest_tool(
            "https://deepeval.com",
            cfg,
            github_fetch=_spy_github,
            html_fetch=lambda _url: ExtractedDoc("# Deepeval\n\nLLM eval.", "Deepeval", "The eval framework"),
        )

        assert gh_called == [], "github_fetch must NOT be called for non-github URL"
        body = (cfg.project_root / result["dest"]).read_text()
        assert "Deepeval" in body

        manifest = _read_manifest(wiki_root)
        assert manifest[-1]["source"] == "https://deepeval.com"
        assert manifest[-1]["source_class"] == "tool"

    def test_bare_owner_repo_routes_to_github(self, wiki_root: Path) -> None:
        """A bare ``owner/repo`` ref must be treated as GitHub (documented contract)."""
        cfg = _cfg(wiki_root)
        tool = _sample_tool()
        captured: list[tuple[str, str]] = []

        def _capture_fetch(owner: str, repo: str, _token: object) -> GitHubTool:
            captured.append((owner, repo))
            return tool

        result = it._ingest_tool(
            "openai/whisper",
            cfg,
            github_fetch=_capture_fetch,
            html_fetch=lambda _url: ExtractedDoc("should-not-be-used", None, None),
        )

        assert captured == [("openai", "whisper")], "bare owner/repo must route to github_fetch with correct owner/repo"
        body = (cfg.project_root / result["dest"]).read_text()
        assert "Whisper" in body

    def test_meta_block_prepended_to_readme(self, wiki_root: Path) -> None:
        """The tool-meta comment block must appear before the README body."""
        cfg = _cfg(wiki_root)
        tool = _sample_tool()

        result = it._ingest_tool(
            "https://github.com/openai/whisper",
            cfg,
            github_fetch=lambda _o, _r, _t: tool,
            html_fetch=lambda _url: ExtractedDoc("", None, None),
        )

        body = (cfg.project_root / result["dest"]).read_text()
        meta_idx = body.index("<!-- tool:")
        readme_idx = body.index("# Whisper")
        assert meta_idx < readme_idx, "meta block must come before README content"

    def test_source_and_source_class_persisted(self, wiki_root: Path) -> None:
        """source=<url> and source_class=tool must be in both sidecar and manifest."""
        cfg = _cfg(wiki_root)
        url = "https://github.com/openai/whisper"
        tool = _sample_tool()

        result = it._ingest_tool(
            url,
            cfg,
            github_fetch=lambda _o, _r, _t: tool,
            html_fetch=lambda _url: ExtractedDoc("", None, None),
        )

        dest = cfg.project_root / result["dest"]
        sidecar = dest.parent / (dest.name + ".meta.json")
        meta = json.loads(sidecar.read_text())
        assert meta["source"] == url
        assert meta["type"] == "tool"

        manifest = _read_manifest(wiki_root)
        last = manifest[-1]
        assert last["source"] == url
        assert last["source_class"] == "tool"

    def test_github_not_found_raises_error(self, wiki_root: Path) -> None:
        """GitHubNotFoundError must propagate from _ingest_tool."""
        cfg = _cfg(wiki_root)

        def _raise_404(owner: str, repo: str, _token: object) -> GitHubTool:
            msg = f"GitHub repo {owner}/{repo} not found (404)"
            raise GitHubNotFoundError(msg)

        with pytest.raises((GitHubNotFoundError, RuntimeError), match=r"not found|404"):
            it._ingest_tool(
                "https://github.com/does-not/exist",
                cfg,
                github_fetch=_raise_404,
                html_fetch=lambda _url: ExtractedDoc("", None, None),
            )

    def test_github_rate_limit_raises_error(self, wiki_root: Path) -> None:
        """GitHubRateLimitError must propagate cleanly from _ingest_tool."""
        cfg = _cfg(wiki_root)

        def _raise_rate_limit(_owner: str, _repo: str, _token: object) -> GitHubTool:
            msg = "GitHub API rate limit exceeded; resets at epoch 1700000000"
            raise GitHubRateLimitError(msg)

        with pytest.raises((GitHubRateLimitError, RuntimeError), match="rate limit"):
            it._ingest_tool(
                "https://github.com/openai/whisper",
                cfg,
                github_fetch=_raise_rate_limit,
                html_fetch=lambda _url: ExtractedDoc("", None, None),
            )

    def test_generic_empty_content_raises_runtime_error(self, wiki_root: Path) -> None:
        """Empty content from html_fetch must raise RuntimeError with clear message."""
        cfg = _cfg(wiki_root)

        with pytest.raises(RuntimeError, match="No content"):
            it._ingest_tool(
                "https://example.com/empty",
                cfg,
                github_fetch=_never_github,
                html_fetch=lambda _url: ExtractedDoc("", None, None),
            )

    def test_generic_url_meta_block_uses_netloc(self, wiki_root: Path) -> None:
        """lang_or_host in meta block for generic URL must be the domain (netloc)."""
        cfg = _cfg(wiki_root)

        result = it._ingest_tool(
            "https://buildkite.com/docs",
            cfg,
            github_fetch=_never_github,
            html_fetch=lambda _url: ExtractedDoc("# Buildkite\n\nCI/CD pipeline.", "Buildkite", "CI/CD"),
        )

        body = (cfg.project_root / result["dest"]).read_text()
        assert "buildkite.com" in body
