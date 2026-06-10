"""Configuration loader for llm-wiki.

Reads .kb-config.yml from the wiki root, validates required fields,
and provides a typed Config dataclass to the rest of the system.

The project root is detected by walking up from cwd looking for .kb-config.yml.
All other modules use get_project_root() and load_config() from here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


CONFIG_FILENAME = ".kb-config.yml"
ENV_ROOT = "KARPATHY_WIKI_ROOT"

# Maximum number of parent directories to walk when searching for the config file.
_MAX_PARENT_WALK = 20


@dataclass
class WikiConfig:
    """Typed representation of .kb-config.yml.

    All path fields are resolved to absolute paths relative to project_root.
    """

    project_root: Path
    vault_root: Path
    raw_inbox: Path
    raw_sessions: Path
    raw_artifacts: Path
    raw_web: Path
    wiki_permanent: Path
    wiki_index: Path
    wiki_meta: Path
    output: Path
    fleeting: Path
    db_path: Path
    table_name: str
    compile_batch_size: int
    auto_link_threshold: float
    lint_orphan_threshold: int
    lint_tag_compliance: str
    lint_index_staleness_hours: int
    lint_index_min_coverage_pct: int
    query_default_limit: int
    # Keep the raw dict for backward-compat access
    _raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def get_path(self, key: str) -> Path:
        """Resolve a path key to an absolute path relative to project root.

        Supports dotted keys like 'paths.raw_inbox' or flat keys like 'raw_inbox'.
        """
        # Try as attribute first
        flat_key = key.replace("paths.", "").replace("lancedb.", "")
        if hasattr(self, flat_key):
            val = getattr(self, flat_key)
            if isinstance(val, Path):
                return val

        # Walk the raw config dict
        parts = key.split(".")
        node: Any = self._raw
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                msg = f"Config key not found: {key}"
                raise KeyError(msg)
        return self.project_root / str(node)


def get_project_root(start: Path | None = None) -> Path:
    """Find the wiki project root.

    Resolution order:
      1. Explicit ``start`` argument
      2. ``KARPATHY_WIKI_ROOT`` environment variable
      3. Walk up from cwd looking for .kb-config.yml

    Args:
        start: Directory to start searching from. If provided, skips the
               environment variable check.

    Returns:
        Path to the project root directory containing .kb-config.yml.

    Raises:
        FileNotFoundError: If no .kb-config.yml is found.
    """
    if start is None:
        env_root = os.environ.get(ENV_ROOT)
        if env_root:
            candidate = Path(env_root).resolve()
            if (candidate / CONFIG_FILENAME).exists():
                return candidate
            msg = f"{ENV_ROOT}={env_root} does not contain {CONFIG_FILENAME}."
            raise FileNotFoundError(msg)

    current = Path(start) if start else Path.cwd()
    current = current.resolve()

    for _ in range(_MAX_PARENT_WALK):
        if (current / CONFIG_FILENAME).exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent

    msg = (
        f"Cannot find {CONFIG_FILENAME}. "
        f"Run 'kb init' to create a new knowledge base, set {ENV_ROOT}, "
        "or cd into a wiki directory."
    )
    raise FileNotFoundError(msg)


def load_raw_config(root: Path) -> dict[str, Any]:
    """Load the raw YAML config as a dict.

    Args:
        root: Path to the project root directory.

    Returns:
        Parsed YAML dict.

    Raises:
        FileNotFoundError: If .kb-config.yml is not found.
        ValueError: If the config file is malformed (not a YAML mapping).
    """
    config_path = root / CONFIG_FILENAME
    if not config_path.exists():
        msg = f"Config file not found at {config_path}"
        raise FileNotFoundError(msg)
    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        msg = f"Malformed config file: expected a YAML mapping, got {type(data).__name__}"
        raise ValueError(msg)  # noqa: TRY004  # contract: tests assert ValueError
    return data


def load_config(root: Path | None = None) -> WikiConfig:
    """Load wiki configuration from .kb-config.yml.

    Args:
        root: Path to the wiki root directory. If None, searches upward
              from the current directory for a .kb-config.yml file.

    Returns:
        Parsed WikiConfig instance with all paths resolved to absolute.

    Raises:
        FileNotFoundError: If no .kb-config.yml is found.
        ValueError: If the config file is malformed.
    """
    if root is None:
        root = get_project_root()
    root = root.resolve()

    raw = load_raw_config(root)
    paths = raw.get("paths", {})
    lancedb_cfg = raw.get("lancedb", {})
    compile_cfg = raw.get("compile", {})
    lint_cfg = raw.get("lint", {})
    query_cfg = raw.get("query", {})

    def _resolve(rel: str) -> Path:
        return root / rel

    return WikiConfig(
        project_root=root,
        vault_root=_resolve(raw.get("vault_root", ".")),
        raw_inbox=_resolve(paths.get("raw_inbox", "raw/inbox")),
        raw_sessions=_resolve(paths.get("raw_sessions", "raw/sessions")),
        raw_artifacts=_resolve(paths.get("raw_artifacts", "raw/artifacts")),
        raw_web=_resolve(paths.get("raw_web", "raw/web")),
        wiki_permanent=_resolve(paths.get("wiki_permanent", "wiki/permanent")),
        wiki_index=_resolve(paths.get("wiki_index", "wiki/_index")),
        wiki_meta=_resolve(paths.get("wiki_meta", "wiki/_meta")),
        output=_resolve(paths.get("output", "output")),
        fleeting=_resolve(paths.get("fleeting", "fleeting")),
        db_path=_resolve(lancedb_cfg.get("db_path", ".lancedb")),
        table_name=lancedb_cfg.get("table_name", "notes"),
        compile_batch_size=compile_cfg.get("batch_size", 10),
        auto_link_threshold=compile_cfg.get("auto_link_threshold", 0.75),
        lint_orphan_threshold=lint_cfg.get("orphan_threshold", 0),
        lint_tag_compliance=lint_cfg.get("tag_compliance", "strict"),
        lint_index_staleness_hours=lint_cfg.get("index_staleness_hours", 24),
        lint_index_min_coverage_pct=lint_cfg.get("index_min_coverage_pct", 80),
        query_default_limit=query_cfg.get("default_limit", 10),
        _raw=raw,
    )
