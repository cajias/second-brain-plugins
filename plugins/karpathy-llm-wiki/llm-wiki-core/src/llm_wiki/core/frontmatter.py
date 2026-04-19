"""YAML frontmatter parsing and validation for wiki notes.

Handles reading, writing, and validating the YAML frontmatter block
at the top of markdown wiki notes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


KNOWLEDGE_TYPES = [
    "fact",
    "pattern",
    "decision",
    "correction",
    "idea",
    "design",
    "exploration",
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
    # Use explicit ordering for known fields
    ordered_keys = [
        "id", "type", "knowledge_type", "status", "confidence",
        "scope", "tags", "source", "created",
    ]
    lines = ["---"]
    for key in ordered_keys:
        if key in metadata:
            val = metadata[key]
            if key == "tags" and isinstance(val, list):
                lines.append("tags:")
                for tag in val:
                    lines.append(f"  - {tag}")
            elif key in ("source", "created") and isinstance(val, str):
                lines.append(f'{key}: "{val}"')
            else:
                lines.append(f"{key}: {val}")

    # Append any extra keys not in the ordered set
    for key, val in metadata.items():
        if key not in ordered_keys:
            if isinstance(val, list):
                lines.append(f"{key}:")
                for item in val:
                    lines.append(f"  - {item}")
            elif isinstance(val, str):
                lines.append(f'{key}: "{val}"')
            else:
                lines.append(f"{key}: {val}")

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
    errors = []

    for field_name in REQUIRED_FIELDS:
        if field_name not in metadata or metadata[field_name] is None:
            errors.append(f"Missing required field: {field_name}")

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
                errors.append(
                    f"Invalid value for {field_name}: '{val}'. "
                    f"Expected one of: {allowed}"
                )

    tags = metadata.get("tags", [])
    if isinstance(tags, list) and len(tags) > 6:
        errors.append(f"Too many tags ({len(tags)}). Maximum is 6.")

    return errors


# Keep backward-compatible aliases
parse_frontmatter = parse
write_frontmatter = dump
validate_frontmatter = validate
