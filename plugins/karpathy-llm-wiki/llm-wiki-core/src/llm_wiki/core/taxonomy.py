"""Tag taxonomy management for the wiki.

Reads and parses the tag taxonomy markdown file, provides lookup
for valid tags and knowledge types, and supports validation.
"""

from __future__ import annotations

import re
from pathlib import Path


def load_taxonomy(taxonomy_path: Path) -> dict[str, set[str]]:
    """Load approved tags and knowledge types from tag-taxonomy.md.

    Args:
        taxonomy_path: Path to the tag-taxonomy.md file.

    Returns:
        Dict with 'tags' (set of approved tag strings) and
        'knowledge_types' (set of approved knowledge type strings).

    Raises:
        FileNotFoundError: If the taxonomy file doesn't exist.
    """
    if not taxonomy_path.exists():
        raise FileNotFoundError(f"Taxonomy file not found: {taxonomy_path}")

    content = taxonomy_path.read_text(encoding="utf-8")
    return _parse_taxonomy_content(content)


def load_taxonomy_safe(taxonomy_path: Path) -> dict[str, set[str]]:
    """Like load_taxonomy but returns empty sets if file is missing."""
    if not taxonomy_path.exists():
        return {"tags": set(), "knowledge_types": set()}
    content = taxonomy_path.read_text(encoding="utf-8")
    return _parse_taxonomy_content(content)


def _parse_taxonomy_content(content: str) -> dict[str, set[str]]:
    """Parse taxonomy content into tags and knowledge types."""
    tags: set[str] = set()
    knowledge_types: set[str] = set()

    # Split by top-level sections
    sections = re.split(r"^## ", content, flags=re.MULTILINE)
    for section in sections:
        if section.startswith("Knowledge Types"):
            for m in re.finditer(r"^\|\s*`(\w[\w-]*)`\s*\|", section, re.MULTILINE):
                knowledge_types.add(m.group(1))
        elif section.startswith("Approved Tags"):
            for m in re.finditer(r"^\|\s*`(\w[\w-]*)`\s*\|", section, re.MULTILINE):
                tags.add(m.group(1))

    # If we couldn't parse sections cleanly, use all tokens for both
    if not tags:
        tags = knowledge_types.copy()

    return {"tags": tags, "knowledge_types": knowledge_types}


def load_knowledge_types(taxonomy_path: Path) -> set[str]:
    """Load valid knowledge types from the taxonomy markdown file.

    Args:
        taxonomy_path: Path to the tag-taxonomy.md file.

    Returns:
        Set of valid knowledge type strings.
    """
    taxonomy = load_taxonomy_safe(taxonomy_path)
    return taxonomy["knowledge_types"]


def load_approved_tags(taxonomy_path: Path) -> list[str] | None:
    """Load approved tags from the taxonomy file.

    Args:
        taxonomy_path: Path to tag-taxonomy.md.

    Returns:
        List of approved tags, or None if file is missing.
    """
    if not taxonomy_path.exists():
        return None

    content = taxonomy_path.read_text(encoding="utf-8")
    tags = []
    tag_row_pattern = re.compile(r"^\|\s*`([^`]+)`\s*\|")
    in_approved_section = False
    for line in content.splitlines():
        if "## Approved Tags" in line:
            in_approved_section = True
            continue
        if in_approved_section and line.startswith("## "):
            break
        if in_approved_section:
            m = tag_row_pattern.match(line)
            if m:
                tags.append(m.group(1))
    return tags


def validate_tags(tags: list[str], taxonomy_path: Path) -> list[str]:
    """Validate a list of tags against the approved taxonomy.

    Args:
        tags: List of tag strings to validate.
        taxonomy_path: Path to the tag-taxonomy.md file.

    Returns:
        List of invalid tag names (empty if all valid).
    """
    taxonomy = load_taxonomy_safe(taxonomy_path)
    approved = taxonomy["tags"]
    if not approved:
        return []  # No taxonomy loaded, cannot validate
    return [t for t in tags if t not in approved]


def validate_knowledge_type(knowledge_type: str, taxonomy_path: Path) -> bool:
    """Check if a knowledge type is in the approved list.

    Returns True if valid, False otherwise.
    """
    taxonomy = load_taxonomy_safe(taxonomy_path)
    types = taxonomy["knowledge_types"]
    if not types:
        return True  # No taxonomy, assume valid
    return knowledge_type in types
