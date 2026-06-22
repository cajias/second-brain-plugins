"""GitHub repo detection + README/metadata fetch (stdlib urllib)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen


_GITHUB_URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/?#]+)", re.IGNORECASE)
_BARE_REF_RE = re.compile(r"^([\w.-]+)/([\w.-]+)$")
_GH_TOKEN_TIMEOUT_SEC = 5
_HTTP_404 = 404
_HTTP_403 = 403

Fetch = Callable[[str, dict[str, str]], bytes]


class GitHubNotFoundError(Exception):
    """Raised when the repo or README returns 404."""


class GitHubRateLimitError(Exception):
    """Raised when the GitHub API returns a 403 rate-limit response."""


@dataclass(frozen=True)
class GitHubTool:
    """README + metadata for a GitHub repo."""

    readme_markdown: str
    description: str | None
    topics: list[str]
    language: str | None
    homepage: str | None
    stargazers_count: int


def parse_github_repo(url_or_ref: str) -> tuple[str, str] | None:
    """Return ``(owner, repo)`` for a GitHub URL or bare ``owner/repo`` ref, else None."""
    ref = url_or_ref.strip()
    m = _GITHUB_URL_RE.match(ref) or _BARE_REF_RE.match(ref)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    return owner, repo[:-4] if repo.endswith(".git") else repo


def readme_api_url(owner: str, repo: str) -> str:
    """Return the README API URL for a repo."""
    return f"https://api.github.com/repos/{owner}/{repo}/readme"


def repo_api_url(owner: str, repo: str) -> str:
    """Return the repo-metadata API URL."""
    return f"https://api.github.com/repos/{owner}/{repo}"


def github_token() -> str | None:
    """Read a GitHub token from $GITHUB_TOKEN, falling back to ``gh auth token``.

    Read at call time and never persisted.
    """
    import os  # noqa: PLC0415  # local import keeps the module import side-effect-free

    env = os.environ.get("GITHUB_TOKEN")
    if env:
        return env
    if shutil.which("gh") is None:
        return None
    try:
        out = subprocess.run(
            ["gh", "auth", "token"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=_GH_TOKEN_TIMEOUT_SEC,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    token = out.stdout.strip()
    return token or None


def _default_fetch(url: str, headers: dict[str, str]) -> bytes:
    req = Request(url, headers=headers)  # noqa: S310
    with urlopen(req, timeout=30) as resp:  # noqa: S310
        return bytes(resp.read())


def _handle_http_error(exc: HTTPError, owner: str, repo: str) -> None:
    """Translate HTTPError into domain-specific exceptions."""
    if exc.code == _HTTP_404:
        msg = f"GitHub repo {owner}/{repo} not found (404)"
        raise GitHubNotFoundError(msg) from exc
    if exc.code == _HTTP_403:
        remaining = exc.headers.get("X-RateLimit-Remaining", "")
        if remaining == "0":
            reset = exc.headers.get("X-RateLimit-Reset", "unknown")
            msg = f"GitHub API rate limit exceeded for {owner}/{repo}; resets at epoch {reset}"
            raise GitHubRateLimitError(msg) from exc
    raise exc


def fetch_github(
    owner: str,
    repo: str,
    token: str | None,
    *,
    fetch: Fetch = _default_fetch,
) -> GitHubTool:
    """Fetch README (raw) + repo metadata. ``fetch`` is injectable for tests."""
    base: dict[str, str] = {"User-Agent": "kb-ingest-tool/1.0"}
    if token:
        base["Authorization"] = f"Bearer {token}"

    try:
        readme_bytes = fetch(readme_api_url(owner, repo), {**base, "Accept": "application/vnd.github.raw"})
    except HTTPError as exc:
        _handle_http_error(exc, owner, repo)
        raise  # unreachable but satisfies type checker

    try:
        meta_bytes = fetch(repo_api_url(owner, repo), {**base, "Accept": "application/vnd.github+json"})
    except HTTPError as exc:
        _handle_http_error(exc, owner, repo)
        raise  # unreachable but satisfies type checker

    readme = readme_bytes.decode("utf-8", errors="replace")
    meta = json.loads(meta_bytes.decode())
    return GitHubTool(
        readme_markdown=readme,
        description=meta.get("description"),
        topics=list(meta.get("topics", [])),
        language=meta.get("language"),
        homepage=meta.get("homepage"),
        stargazers_count=int(meta.get("stargazers_count", 0)),
    )
