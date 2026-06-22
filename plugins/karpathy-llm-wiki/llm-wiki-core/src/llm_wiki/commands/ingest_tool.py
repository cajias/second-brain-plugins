"""Ingest a tool from any URL into the tool contract (source_class=tool).

GitHub repo URLs → README API + repo metadata; any other URL → trafilatura
main-content extraction + page metadata. Both prepend a tool-meta comment so
the compile classifier sees the signal inline, then reuse the existing
``kb ingest --mode text`` sidecar path.

Routing contract:
- ``https://github.com/<owner>/<repo>`` → GitHub API (README + metadata)
- ``owner/repo`` bare ref                → GitHub API (documented contract)
- Any other full URL                     → generic HTML extraction (trafilatura)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import typer

from llm_wiki.commands.ingest import _ingest_text
from llm_wiki.core.config import load_config
from llm_wiki.core.github import GitHubTool, fetch_github, github_token, parse_github_repo
from llm_wiki.core.html_extract import ExtractedDoc, extract_main_content


if TYPE_CHECKING:
    from collections.abc import Callable

    from llm_wiki.core.config import WikiConfig

    GithubFetch = Callable[[str, str, str | None], GitHubTool]
    HtmlFetch = Callable[[str], ExtractedDoc]


def build_tool_meta_block(
    url: str,
    *,
    lang_or_host: str,
    stars: int | None,
    topics_or_keywords: list[str],
    description: str | None,
) -> str:
    """Build the inline tool-meta comment + description prepended to the body.

    Format: ``<!-- tool: <url> | <lang/host> | ⭐<stars> | <topics> -->``
    followed by an optional blockquote description.
    """
    star_part = f" | ⭐{stars}" if stars is not None else ""
    topic_part = f" | {', '.join(topics_or_keywords)}" if topics_or_keywords else ""
    comment = f"<!-- tool: {url} | {lang_or_host}{star_part}{topic_part} -->"
    desc = f"\n\n> {description}" if description else ""
    return f"{comment}{desc}\n\n"


def _default_html_fetch(url: str) -> ExtractedDoc:
    req = Request(url, headers={"User-Agent": "kb-ingest-tool/1.0"})  # noqa: S310  # http(s) only
    with urlopen(req, timeout=30) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8", errors="replace")
    return extract_main_content(raw, url=url)


def _default_github_fetch(owner: str, repo: str, token: str | None) -> GitHubTool:
    return fetch_github(owner, repo, token)


def _ingest_tool(
    url: str,
    cfg: WikiConfig,
    *,
    github_fetch: GithubFetch = _default_github_fetch,
    html_fetch: HtmlFetch = _default_html_fetch,
) -> dict[str, Any]:
    """Route a URL to GitHub or generic extraction and ingest it as a tool.

    Routing rules (explicit, tested):
    - github.com URL  → GitHub API path
    - bare owner/repo → GitHub API path (documented contract)
    - any other URL   → generic HTML / trafilatura path
    """
    repo = parse_github_repo(url)
    if repo is not None:
        owner, name = repo
        tool = github_fetch(owner, name, github_token())
        block = build_tool_meta_block(
            url,
            lang_or_host=tool.language or "github",
            stars=tool.stargazers_count,
            topics_or_keywords=tool.topics,
            description=tool.description,
        )
        body = block + tool.readme_markdown
    else:
        doc = html_fetch(url)
        if not doc.text.strip():
            msg = f"No content could be extracted from {url}."
            raise RuntimeError(msg)
        block = build_tool_meta_block(
            url,
            lang_or_host=urlparse(url).netloc,
            stars=None,
            topics_or_keywords=[],
            description=doc.description or doc.title,
        )
        body = block + doc.text

    return _ingest_text(body, cfg, source_class="tool", source=url)


def ingest_tool(
    url: str = typer.Argument(..., help="Tool URL (https://github.com/owner/repo, owner/repo, or any HTTPS URL)."),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output result as JSON."),
) -> None:
    """Ingest a tool from any URL into the inbox (source_class=tool).

    GitHub repo URLs and bare owner/repo refs use the GitHub API to fetch the
    README and repository metadata.  Any other HTTPS URL is fetched as HTML
    and the main content is extracted via trafilatura.

    Both paths prepend a ``<!-- tool: … -->`` metadata comment so the compile
    classifier can recognise the note as a tool reference.
    """
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e

    try:
        result = _ingest_tool(url, cfg)
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e

    if json_output:
        typer.echo(json.dumps(result, indent=2, default=str))
    else:
        typer.echo(f"Ingested tool: {result['dest']} (source_class=tool)")
        typer.echo(f"  Manifest ID: {result['manifest_id']}")
        typer.echo("\nRun 'kb compile' to process the inbox.")
