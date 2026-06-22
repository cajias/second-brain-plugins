"""Tag normalization — the single core home for turning a frontmatter ``tags`` value into a clean ``list[str]``.

Replaces the ad-hoc CSV split/join previously duplicated across
``commands/index`` and ``commands/compile_cmd``.
"""

from __future__ import annotations


def normalize_tags(value: object) -> list[str]:
    """Coerce a frontmatter tags value into a clean list of tag strings.

    Accepts a list, numpy ndarray (or any object with ``.tolist()``), a
    comma-separated string, a scalar, or None. Strips whitespace and drops
    empty entries.

    Args:
        value: The raw ``tags`` frontmatter value.

    Returns:
        A list of non-empty, stripped tag strings.
    """
    if value is None:
        return []
    # numpy ndarray and other array-like types expose .tolist(); convert first
    # so the list branch handles the elements uniformly.
    if not isinstance(value, (str, list)) and hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, list):
        return [s for s in (str(t).strip() for t in value) if s]
    if isinstance(value, str):
        return [s for s in (part.strip() for part in value.split(",")) if s]
    text = str(value).strip()
    return [text] if text else []
