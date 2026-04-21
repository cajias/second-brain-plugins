"""Tests for llm_wiki.core.config — configuration loading and path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from llm_wiki.core.config import get_project_root, load_config, load_raw_config, WikiConfig


# ---------------------------------------------------------------------------
# get_project_root
# ---------------------------------------------------------------------------


class TestGetProjectRoot:
    """get_project_root() walks up to find .kb-config.yml."""

    def test_finds_config_in_given_dir(self, wiki_root: Path):
        root = get_project_root(start=wiki_root)
        assert root == wiki_root.resolve()

    def test_finds_config_from_subdirectory(self, wiki_root: Path):
        """Starting from a child directory should still find the root."""
        sub = wiki_root / "wiki" / "permanent"
        root = get_project_root(start=sub)
        assert root == wiki_root.resolve()

    def test_error_when_no_config(self, wiki_root_bare: Path):
        with pytest.raises(FileNotFoundError, match="Cannot find"):
            get_project_root(start=wiki_root_bare)

    def test_env_var_overrides_cwd(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root.parent)
        monkeypatch.setenv("KARPATHY_WIKI_ROOT", str(wiki_root))
        root = get_project_root()
        assert root == wiki_root.resolve()

    def test_env_var_error_when_no_config(self, wiki_root_bare: Path, monkeypatch):
        monkeypatch.setenv("KARPATHY_WIKI_ROOT", str(wiki_root_bare))
        with pytest.raises(FileNotFoundError, match="KARPATHY_WIKI_ROOT"):
            get_project_root()

    def test_explicit_start_ignores_env_var(self, wiki_root: Path, wiki_root_bare: Path, monkeypatch):
        monkeypatch.setenv("KARPATHY_WIKI_ROOT", str(wiki_root_bare))
        root = get_project_root(start=wiki_root)
        assert root == wiki_root.resolve()


# ---------------------------------------------------------------------------
# load_raw_config
# ---------------------------------------------------------------------------


class TestLoadRawConfig:
    """load_raw_config() parses the YAML file into a dict."""

    def test_returns_dict(self, wiki_root: Path):
        data = load_raw_config(wiki_root)
        assert isinstance(data, dict)
        assert "paths" in data
        assert "lancedb" in data

    def test_error_when_no_file(self, wiki_root_bare: Path):
        with pytest.raises(FileNotFoundError):
            load_raw_config(wiki_root_bare)

    def test_error_on_malformed_yaml(self, tmp_path: Path):
        cfg = tmp_path / ".kb-config.yml"
        cfg.write_text("just a string, not a mapping\n")
        with pytest.raises(ValueError, match="Malformed"):
            load_raw_config(tmp_path)


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """load_config() returns a fully populated WikiConfig."""

    def test_returns_wiki_config(self, wiki_root: Path):
        cfg = load_config(root=wiki_root)
        assert isinstance(cfg, WikiConfig)

    def test_project_root_is_absolute(self, wiki_root: Path):
        cfg = load_config(root=wiki_root)
        assert cfg.project_root.is_absolute()
        assert cfg.project_root == wiki_root.resolve()

    def test_parses_paths_as_absolute(self, wiki_root: Path):
        cfg = load_config(root=wiki_root)
        assert cfg.raw_inbox.is_absolute()
        assert cfg.raw_inbox == wiki_root.resolve() / "raw" / "inbox"

    def test_parses_wiki_permanent(self, wiki_root: Path):
        cfg = load_config(root=wiki_root)
        assert cfg.wiki_permanent == wiki_root.resolve() / "wiki" / "permanent"

    def test_parses_lancedb_settings(self, wiki_root: Path):
        cfg = load_config(root=wiki_root)
        assert cfg.table_name == "notes"
        assert cfg.db_path == wiki_root.resolve() / ".lancedb"

    def test_parses_compile_settings(self, wiki_root: Path):
        cfg = load_config(root=wiki_root)
        assert cfg.compile_batch_size == 10
        assert cfg.auto_link_threshold == 0.75

    def test_parses_lint_settings(self, wiki_root: Path):
        cfg = load_config(root=wiki_root)
        assert cfg.lint_orphan_threshold == 0
        assert cfg.lint_tag_compliance == "strict"
        assert cfg.lint_index_staleness_hours == 24
        assert cfg.lint_index_min_coverage_pct == 80

    def test_parses_query_settings(self, wiki_root: Path):
        cfg = load_config(root=wiki_root)
        assert cfg.query_default_limit == 10

    def test_error_when_no_config(self, wiki_root_bare: Path):
        with pytest.raises(FileNotFoundError):
            load_config(root=wiki_root_bare)


# ---------------------------------------------------------------------------
# WikiConfig.get_path
# ---------------------------------------------------------------------------


class TestGetPath:
    """WikiConfig.get_path() resolves arbitrary config keys."""

    def test_resolves_flat_key(self, wiki_root: Path):
        cfg = load_config(root=wiki_root)
        perm = cfg.get_path("wiki_permanent")
        assert perm == cfg.wiki_permanent

    def test_resolves_dotted_key(self, wiki_root: Path):
        cfg = load_config(root=wiki_root)
        perm = cfg.get_path("paths.wiki_permanent")
        assert str(perm).endswith("wiki/permanent")

    def test_raises_on_unknown_key(self, wiki_root: Path):
        cfg = load_config(root=wiki_root)
        with pytest.raises(KeyError):
            cfg.get_path("nonexistent.key.path")
