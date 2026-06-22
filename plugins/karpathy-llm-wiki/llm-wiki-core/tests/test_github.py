"""Tests for GitHub repo detection + README/metadata API construction."""

from __future__ import annotations

import json

import pytest

from llm_wiki.core import github


class TestParseGithubRepo:
    def test_full_url(self):
        assert github.parse_github_repo("https://github.com/openai/whisper") == ("openai", "whisper")

    def test_url_with_trailing_path(self):
        assert github.parse_github_repo("https://github.com/openai/whisper/tree/main") == ("openai", "whisper")

    def test_bare_ref(self):
        assert github.parse_github_repo("openai/whisper") == ("openai", "whisper")

    def test_non_github_url_returns_none(self):
        assert github.parse_github_repo("https://deepeval.com") is None

    def test_strips_dot_git(self):
        assert github.parse_github_repo("https://github.com/a/b.git") == ("a", "b")


class TestApiUrls:
    def test_readme_url(self):
        assert github.readme_api_url("a", "b") == "https://api.github.com/repos/a/b/readme"

    def test_repo_url(self):
        assert github.repo_api_url("a", "b") == "https://api.github.com/repos/a/b"


class TestFetchGithub:
    def test_assembles_tool_from_injected_fetch(self):
        def _fake_fetch(url, headers):
            if url.endswith("/readme"):
                assert headers["Accept"] == "application/vnd.github.raw"
                return b"# Whisper\n\nASR model."
            return json.dumps(
                {
                    "description": "Robust ASR",
                    "topics": ["asr", "speech"],
                    "language": "Python",
                    "homepage": "https://openai.com",
                    "stargazers_count": 1234,
                }
            ).encode()

        tool = github.fetch_github("openai", "whisper", token=None, fetch=_fake_fetch)
        assert tool.readme_markdown.startswith("# Whisper")
        assert tool.description == "Robust ASR"
        assert tool.topics == ["asr", "speech"]
        assert tool.language == "Python"
        assert tool.stargazers_count == 1234

    def test_token_header_sent_when_provided(self):
        """Authorization header is set when token is provided."""
        captured: list[dict[str, str]] = []

        def _fake_fetch(url, headers):
            captured.append(dict(headers))
            if url.endswith("/readme"):
                return b"# Readme"
            return json.dumps(
                {
                    "description": None,
                    "topics": [],
                    "language": None,
                    "homepage": None,
                    "stargazers_count": 0,
                }
            ).encode()

        github.fetch_github("a", "b", token="mytoken", fetch=_fake_fetch)
        assert all("Authorization" in h for h in captured)
        assert all(h["Authorization"] == "Bearer mytoken" for h in captured)

    def test_token_header_absent_when_none(self):
        """Authorization header is NOT set when token is None."""
        captured: list[dict[str, str]] = []

        def _fake_fetch(url, headers):
            captured.append(dict(headers))
            if url.endswith("/readme"):
                return b"# Readme"
            return json.dumps(
                {
                    "description": None,
                    "topics": [],
                    "language": None,
                    "homepage": None,
                    "stargazers_count": 0,
                }
            ).encode()

        github.fetch_github("a", "b", token=None, fetch=_fake_fetch)
        assert all("Authorization" not in h for h in captured)

    def test_404_raises_github_not_found(self):
        """404 from API raises GitHubNotFoundError with clear message."""
        from urllib.error import HTTPError

        def _fake_fetch(url, headers):
            raise HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

        with pytest.raises(github.GitHubNotFoundError, match="no/repo"):
            github.fetch_github("no", "repo", token=None, fetch=_fake_fetch)

    def test_rate_limit_raises_github_rate_limit_error(self):
        """403 with rate-limit headers raises GitHubRateLimitError with reset info."""
        from http.client import HTTPMessage
        from urllib.error import HTTPError

        headers = HTTPMessage()
        headers["X-RateLimit-Remaining"] = "0"
        headers["X-RateLimit-Reset"] = "1700000000"

        def _fake_fetch(url, headers_arg):
            raise HTTPError(url, 403, "Forbidden", headers, None)  # type: ignore[arg-type]

        with pytest.raises(github.GitHubRateLimitError, match="rate limit"):
            github.fetch_github("a", "b", token=None, fetch=_fake_fetch)
