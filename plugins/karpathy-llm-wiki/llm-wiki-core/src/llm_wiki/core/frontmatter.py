"""YAML frontmatter parsing and validation for wiki notes.

Handles reading, writing, and validating the YAML frontmatter block
at the top of markdown wiki notes.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import yaml


if TYPE_CHECKING:
    from pathlib import Path


KNOWLEDGE_TYPES = [
    "fact",
    "pattern",
    "decision",
    "correction",
    "idea",
    "design",
    "exploration",
    "tool",
]

# Fields that must be present for a note to lint clean.
# Knowledge type is enforced separately via the either-or rule below.
REQUIRED_FIELDS = [
    "tags",
    "source",
    "created",
]

# Fields that are part of the canonical schema but not hard-required.
# Absent recommended fields do not produce lint errors.
RECOMMENDED_FIELDS = [
    "id",
    "status",
    "confidence",
    "scope",
]

# Valid values for enum-like fields.
# `type` accepts either "permanent" (canonical schema) or any knowledge type
# (simplified schema where `type` doubles as `knowledge_type`).
VALID_VALUES = {
    "type": ["permanent", *KNOWLEDGE_TYPES],
    "knowledge_type": KNOWLEDGE_TYPES,
    "status": ["pending", "approved", "archived"],
    "confidence": ["high", "medium", "low"],
    "scope": ["universal", "project", "temporal"],
}

# Maximum number of tags allowed on a single note
MAX_TAGS = 6

# Frontmatter ordering convention for `dump`.
ORDERED_FIELDS = [
    "id",
    "type",
    "knowledge_type",
    "status",
    "confidence",
    "scope",
    "tags",
    "source",
    "created",
]

# Fields that should be quoted as YAML strings on serialization (e.g. dates)
_QUOTED_STRING_FIELDS = {"source", "created"}


def get_knowledge_type(metadata: dict[str, Any]) -> str | None:
    """Return the note's knowledge type from either schema.

    Canonical schema stores it in ``knowledge_type``. Simplified schema
    stores it in ``type`` (where ``type`` holds a knowledge-type value
    rather than the literal ``"permanent"``).
    """
    kt = metadata.get("knowledge_type")
    if isinstance(kt, str) and kt in KNOWLEDGE_TYPES:
        return kt
    t = metadata.get("type")
    if isinstance(t, str) and t in KNOWLEDGE_TYPES:
        return t
    return None


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def parse(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content.

    Args:
        content: Full markdown file content including frontmatter delimiters.

    Returns:
        Tuple of (frontmatter_dict, body_content). If no frontmatter is found,
        returns ({}, full_content).
    """
    match = _FRONTMATTER_RE.match(content)
    if match:
        try:
            metadata = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            metadata = {}
        body = match.group(2)
    else:
        metadata = {}
        body = content
    return metadata, body


def parse_file(filepath: Path) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown file.

    Args:
        filepath: Path to the markdown file.

    Returns:
        Tuple of (frontmatter_dict, body_content).
    """
    text = filepath.read_text(encoding="utf-8")
    return parse(text)


def _format_value(key: str, val: Any, in_ordered_set: bool = True) -> list[str]:  # noqa: ANN401  # frontmatter values are heterogeneous (str/list/int/etc.)
    """Format a single key/value into one or more YAML lines.

    Mirrors the original ``dump`` formatting logic but isolated so the main
    function stays under complexity thresholds.
    """
    if key == "tags" and isinstance(val, list):
        lines = ["tags:"]
        lines.extend(f"  - {tag}" for tag in val)
        return lines

    if isinstance(val, list):
        # Generic list serialization (only used for "extra" non-ordered keys)
        lines = [f"{key}:"]
        lines.extend(f"  - {item}" for item in val)
        return lines

    if isinstance(val, str) and (key in _QUOTED_STRING_FIELDS or not in_ordered_set):
        return [f'{key}: "{val}"']

    return [f"{key}: {val}"]


def dump(metadata: dict[str, Any], body: str) -> str:
    """Serialize frontmatter dict and body back into a markdown string.

    Produces deterministic field ordering matching the wiki convention:
    id, type, knowledge_type, status, confidence, scope, tags, source, created.

    Args:
        metadata: Frontmatter fields as a dictionary.
        body: Markdown body content (without frontmatter delimiters).

    Returns:
        Complete markdown string with YAML frontmatter block.
    """
    lines = ["---"]

    # Known fields in canonical order
    for key in ORDERED_FIELDS:
        if key in metadata:
            lines.extend(_format_value(key, metadata[key], in_ordered_set=True))

    # Append any extra keys not in the ordered set
    for key, val in metadata.items():
        if key not in ORDERED_FIELDS:
            lines.extend(_format_value(key, val, in_ordered_set=False))

    lines.append("---")
    lines.append("")

    content = "\n".join(lines)
    if body:
        content += body
        if not body.endswith("\n"):
            content += "\n"
    return content


def validate(metadata: dict[str, Any]) -> list[str]:
    """Validate frontmatter fields against required schema.

    Args:
        metadata: Parsed frontmatter dictionary.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors = [
        f"Missing required field: {field_name}"
        for field_name in REQUIRED_FIELDS
        if field_name not in metadata or metadata[field_name] is None
    ]

    if get_knowledge_type(metadata) is None:
        errors.append(
            "Missing knowledge type: set `knowledge_type` to one of "
            f"{KNOWLEDGE_TYPES}, or set `type` to one of those values "
            "(simplified schema)."
        )

    for field_name, allowed in VALID_VALUES.items():
        if field_name in metadata and metadata[field_name] is not None:
            val = str(metadata[field_name])
            if val not in allowed:
                errors.append(f"Invalid value for {field_name}: '{val}'. Expected one of: {allowed}")

    tags = metadata.get("tags", [])
    if isinstance(tags, list) and len(tags) > MAX_TAGS:
        errors.append(f"Too many tags ({len(tags)}). Maximum is {MAX_TAGS}.")

    return errors


# Keep backward-compatible aliases
parse_frontmatter = parse
write_frontmatter = dump
validate_frontmatter = validate
