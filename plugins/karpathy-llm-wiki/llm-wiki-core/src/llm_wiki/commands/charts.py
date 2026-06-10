"""Render visualizations for the wiki knowledge base.

Generates charts showing tag distribution, knowledge type breakdown,
confidence levels, growth over time, and a health summary dashboard
using matplotlib.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path  # noqa: TC003  # runtime use: Typer evaluates option type hints
from typing import TYPE_CHECKING, Any

import matplotlib as mpl
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import typer
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Rectangle
from matplotlib.ticker import MaxNLocator

from llm_wiki.core.config import WikiConfig, load_config
from llm_wiki.core.frontmatter import parse_file


if TYPE_CHECKING:
    from collections.abc import Callable

    from matplotlib.axes import Axes

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHART_STYLE = "bmh"

VALID_CHARTS = [
    "tag-distribution",
    "knowledge-type-distribution",
    "confidence-distribution",
    "growth-over-time",
    "health-summary",
]

CHART_ALIASES = {
    "tags": "tag-distribution",
    "knowledge": "knowledge-type-distribution",
    "confidence": "confidence-distribution",
    "growth": "growth-over-time",
    "health": "health-summary",
}

CONFIDENCE_ORDER = ["high", "medium", "low"]
CONFIDENCE_COLORS = {"high": "#2ecc71", "medium": "#f39c12", "low": "#e74c3c"}

KNOWLEDGE_TYPE_COLORS = {
    "fact": "#3498db",
    "pattern": "#9b59b6",
    "decision": "#e67e22",
    "correction": "#e74c3c",
    "idea": "#1abc9c",
    "design": "#2c3e50",
    "exploration": "#f1c40f",
}

WIKILINK_PATTERN = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")

# Tag-count → color thresholds (ratio of bar value to max value)
TAG_COLOR_HIGH_RATIO = 0.6
TAG_COLOR_MEDIUM_RATIO = 0.3

# Confidence score thresholds (numeric mean over notes)
CONF_HIGH_THRESHOLD = 0.7
CONF_MEDIUM_THRESHOLD = 0.4

# Health-summary percentage thresholds
ORPHAN_PCT_GREEN = 30
ORPHAN_PCT_YELLOW = 60
TAG_COMPLIANCE_PCT_GREEN = 80
TAG_COMPLIANCE_PCT_YELLOW = 50

# Growth chart: switch to monthly aggregation when the date span exceeds this
GROWTH_MONTHLY_THRESHOLD_DAYS = 60

# ax.pie() returns 2 elements without autopct, 3 with — used for safe unpacking
_PIE_RESULT_WITH_AUTOPCT = 3

# Numeric confidence map for averaging
_CONFIDENCE_NUMERIC = {"high": 1.0, "medium": 0.5, "low": 0.0}


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


def _collect_all_frontmatter(permanent_dir: Path) -> list[dict[str, Any]]:
    """Read frontmatter from all permanent notes."""
    notes: list[dict[str, Any]] = []
    if not permanent_dir.exists():
        return notes

    for md_file in sorted(permanent_dir.glob("*.md")):
        try:
            fm, _ = parse_file(md_file)
        except (OSError, ValueError):
            continue
        if fm:
            fm["_filename"] = md_file.stem
            notes.append(fm)

    return notes


def _collect_link_data(permanent_dir: Path) -> dict[str, int]:
    """Build basic link stats for health summary."""
    nodes: dict[str, dict[str, set[str]]] = {}
    if not permanent_dir.exists():
        return {"total": 0, "orphans": 0}

    md_files = sorted(permanent_dir.glob("*.md"))
    for md_file in md_files:
        nodes[md_file.stem] = {"linked_from": set()}

    for md_file in md_files:
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in WIKILINK_PATTERN.finditer(text):
            target = match.group(1).strip()
            if target in nodes:
                nodes[target]["linked_from"].add(md_file.stem)

    orphans = sum(1 for data in nodes.values() if len(data["linked_from"]) == 0)
    return {"total": len(nodes), "orphans": orphans}


# ---------------------------------------------------------------------------
# Chart generators
# ---------------------------------------------------------------------------


def _apply_style() -> None:
    """Apply the chart style, falling back if matplotlib lacks it."""
    try:
        plt.style.use(CHART_STYLE)
    except OSError:
        with contextlib.suppress(OSError):
            plt.style.use("seaborn-v0_8")


def _empty_chart(output_path: Path, title: str, message: str) -> Path:
    """Generate a placeholder chart when no data is available."""
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.text(
        0.5,
        0.5,
        message,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=14,
        color="#7f8c8d",
        style="italic",
    )
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.axis("off")
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def _bar_color_for_ratio(ratio: float) -> str:
    """Map a normalized 0..1 ratio to a tag-distribution bar color."""
    if ratio >= TAG_COLOR_HIGH_RATIO:
        return "#2ecc71"
    if ratio >= TAG_COLOR_MEDIUM_RATIO:
        return "#f1c40f"
    return "#e67e22"


def _chart_tag_distribution(notes: list[dict[str, Any]], output_dir: Path) -> Path:
    """Horizontal bar chart of note count per tag."""
    _apply_style()

    tag_counts: Counter[str] = Counter()
    for fm in notes:
        tags = fm.get("tags", [])
        if isinstance(tags, list):
            for t in tags:
                tag_counts[str(t)] += 1

    if not tag_counts:
        return _empty_chart(
            output_dir / "tag-distribution.png",
            "Tag Distribution",
            "No tags found in wiki notes.",
        )

    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1])
    labels = [t[0] for t in sorted_tags]
    values = [t[1] for t in sorted_tags]

    max_val = max(values) if values else 1
    colors = [_bar_color_for_ratio(v / max_val) for v in values]

    fig, ax = plt.subplots(figsize=(10, max(4, len(labels) * 0.4)))
    bars = ax.barh(labels, values, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Number of Notes")
    ax.set_title("Tag Distribution", fontsize=14, fontweight="bold", pad=15)

    for bar, val in zip(bars, values, strict=True):
        ax.text(
            bar.get_width() + 0.1,
            bar.get_y() + bar.get_height() / 2,
            str(val),
            va="center",
            fontsize=9,
        )

    ax.set_xlim(0, max(values) * 1.15)
    plt.tight_layout()
    out_path = output_dir / "tag-distribution.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _chart_knowledge_type_distribution(notes: list[dict[str, Any]], output_dir: Path) -> Path:
    """Donut chart of knowledge type proportions."""
    _apply_style()

    kt_counts: Counter[str] = Counter()
    for fm in notes:
        kt = fm.get("knowledge_type", "unknown")
        kt_counts[str(kt)] += 1

    if not kt_counts:
        return _empty_chart(
            output_dir / "knowledge-type-distribution.png",
            "Knowledge Type Distribution",
            "No knowledge types found.",
        )

    labels = list(kt_counts.keys())
    values = list(kt_counts.values())
    colors = [KNOWLEDGE_TYPE_COLORS.get(label, "#95a5a6") for label in labels]

    fig, ax = plt.subplots(figsize=(8, 8))
    pie_result = ax.pie(
        values,
        labels=labels,
        autopct="%1.0f%%",
        colors=colors,
        startangle=90,
        pctdistance=0.8,
        wedgeprops={"width": 0.4, "edgecolor": "white", "linewidth": 2},
    )
    # ax.pie returns (wedges, texts) without autopct, (wedges, texts, autotexts) with it.
    # mypy stubs type this as a 2-tuple; we always pass autopct so the runtime tuple has 3 items.
    autotexts = pie_result[2] if len(pie_result) == _PIE_RESULT_WITH_AUTOPCT else []  # type: ignore[misc]
    for autotext in autotexts:
        autotext.set_fontsize(10)
        autotext.set_fontweight("bold")

    ax.set_title("Knowledge Type Distribution", fontsize=14, fontweight="bold", pad=20)
    ax.text(0, 0, f"{sum(values)}\nnotes", ha="center", va="center", fontsize=16, fontweight="bold")

    plt.tight_layout()
    out_path = output_dir / "knowledge-type-distribution.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _chart_confidence_distribution(notes: list[dict[str, Any]], output_dir: Path) -> Path:
    """Bar chart of confidence levels."""
    _apply_style()

    conf_counts: Counter[str] = Counter()
    for fm in notes:
        conf = fm.get("confidence", "unknown")
        conf_counts[str(conf)] += 1

    if not conf_counts:
        return _empty_chart(
            output_dir / "confidence-distribution.png",
            "Confidence Distribution",
            "No confidence data found.",
        )

    ordered_labels = [c for c in CONFIDENCE_ORDER if c in conf_counts]
    extra = [c for c in conf_counts if c not in CONFIDENCE_ORDER]
    ordered_labels.extend(sorted(extra))

    values = [conf_counts[label] for label in ordered_labels]
    colors = [CONFIDENCE_COLORS.get(label, "#95a5a6") for label in ordered_labels]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(ordered_labels, values, color=colors, edgecolor="white", linewidth=1.5, width=0.5)
    ax.set_ylabel("Number of Notes")
    ax.set_title("Confidence Distribution", fontsize=14, fontweight="bold", pad=15)

    for bar, val in zip(bars, values, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.2,
            str(val),
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
        )

    ax.set_ylim(0, max(values) * 1.2 if values else 1)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    plt.tight_layout()
    out_path = output_dir / "confidence-distribution.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# --- growth-over-time helpers --------------------------------------------------

_GROWTH_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")

# Type alias for ``created`` frontmatter values we know how to handle.
_CreatedValue = date | datetime | str | None


def _parse_created_string(value: str) -> date | None:
    """Best-effort parse of an ISO-like or common-format date string."""
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        pass
    for fmt in _GROWTH_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    return None


def _parse_created_to_date(created: _CreatedValue) -> date | None:
    """Parse a ``created`` frontmatter value into a ``date``, or None if unparsable."""
    if created is None:
        return None
    if isinstance(created, datetime):
        return created.date()
    if isinstance(created, date):
        return created
    if isinstance(created, str):
        return _parse_created_string(created)
    return None


def _extract_creation_dates(notes: list[dict[str, Any]]) -> list[date]:
    """Extract sorted creation dates from notes' frontmatter."""
    dates: list[date] = []
    for fm in notes:
        d = _parse_created_to_date(fm.get("created"))
        if d is not None:
            dates.append(d)
    dates.sort()
    return dates


def _cumulative_series(
    dates: list[date],
    *,
    by_month: bool,
) -> tuple[list[date], list[int]]:
    """Compute cumulative-count series, grouped by day or month."""
    bucket: dict[date, int] = defaultdict(int)
    for d in dates:
        key = d.replace(day=1) if by_month else d
        bucket[key] += 1

    sorted_keys = sorted(bucket.keys())
    cumulative: list[int] = []
    total = 0
    for k in sorted_keys:
        total += bucket[k]
        cumulative.append(total)
    return sorted_keys, cumulative


def _chart_growth_over_time(notes: list[dict[str, Any]], output_dir: Path) -> Path:
    """Line chart of cumulative note count over time."""
    _apply_style()

    dates = _extract_creation_dates(notes)
    if not dates:
        return _empty_chart(
            output_dir / "growth-over-time.png",
            "Growth Over Time",
            "No creation dates found in notes.",
        )

    span_days = (dates[-1] - dates[0]).days if len(dates) > 1 else 0
    group_by_month = span_days > GROWTH_MONTHLY_THRESHOLD_DAYS
    x_dates, y_vals = _cumulative_series(dates, by_month=group_by_month)
    # matplotlib accepts datetime-like x values; convert to numeric for type-correctness.
    x_vals = mdates.date2num(x_dates)  # type: ignore[no-untyped-call]
    x_label = "Month" if group_by_month else "Date"

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(
        x_vals,
        y_vals,
        marker="o",
        linewidth=2,
        markersize=6,
        color="#3498db",
        markerfacecolor="#2c3e50",
        markeredgecolor="#2c3e50",
    )
    ax.fill_between(x_vals, y_vals, alpha=0.15, color="#3498db")
    ax.set_xlabel(x_label)
    ax.set_ylabel("Cumulative Notes")
    ax.set_title("Knowledge Base Growth", fontsize=14, fontweight="bold", pad=15)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))

    fmt = "%Y-%m" if group_by_month else "%Y-%m-%d"
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))  # type: ignore[no-untyped-call]

    fig.autofmt_xdate(rotation=45)
    plt.tight_layout()
    out_path = output_dir / "growth-over-time.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# --- health-summary helpers ---------------------------------------------------


def _orphan_color(orphan_pct: float) -> str:
    if orphan_pct < ORPHAN_PCT_GREEN:
        return "#2ecc71"
    if orphan_pct < ORPHAN_PCT_YELLOW:
        return "#f39c12"
    return "#e74c3c"


def _tag_compliance_color(pct: float) -> str:
    if pct >= TAG_COMPLIANCE_PCT_GREEN:
        return "#2ecc71"
    if pct >= TAG_COMPLIANCE_PCT_YELLOW:
        return "#f39c12"
    return "#e74c3c"


def _confidence_color(score: float) -> str:
    if score >= CONF_HIGH_THRESHOLD:
        return "#2ecc71"
    if score >= CONF_MEDIUM_THRESHOLD:
        return "#f39c12"
    return "#e74c3c"


def _confidence_label(score: float) -> str:
    if score >= CONF_HIGH_THRESHOLD:
        return "High"
    if score >= CONF_MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


def _compute_health_metrics(
    notes: list[dict[str, Any]],
    permanent_dir: Path,
) -> list[dict[str, str]]:
    """Build the four metric cards rendered in the health-summary dashboard."""
    total_notes = len(notes)
    link_data = _collect_link_data(permanent_dir)
    orphan_count = link_data["orphans"]
    orphan_pct = (orphan_count / total_notes * 100) if total_notes > 0 else 0.0

    tagged = sum(1 for fm in notes if isinstance(fm.get("tags"), list) and len(fm["tags"]) > 0)
    tag_compliance_pct = (tagged / total_notes * 100) if total_notes > 0 else 0.0

    conf_values = [_CONFIDENCE_NUMERIC.get(str(fm.get("confidence", "")), 0.0) for fm in notes]
    avg_confidence = sum(conf_values) / len(conf_values) if conf_values else 0.0

    return [
        {
            "title": "Total Notes",
            "value": str(total_notes),
            "color": "#3498db",
            "subtitle": "in permanent/",
        },
        {
            "title": "Orphan Rate",
            "value": f"{orphan_pct:.0f}%",
            "color": _orphan_color(orphan_pct),
            "subtitle": f"{orphan_count} orphans",
        },
        {
            "title": "Tag Compliance",
            "value": f"{tag_compliance_pct:.0f}%",
            "color": _tag_compliance_color(tag_compliance_pct),
            "subtitle": f"{tagged}/{total_notes} tagged",
        },
        {
            "title": "Avg Confidence",
            "value": _confidence_label(avg_confidence),
            "color": _confidence_color(avg_confidence),
            "subtitle": f"score: {avg_confidence:.2f}",
        },
    ]


def _draw_metric_card(ax: Axes, metric: dict[str, str]) -> None:
    """Render a single metric card on the given axis."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    rect = Rectangle(
        (0.05, 0.05),
        0.9,
        0.9,
        facecolor=metric["color"],
        alpha=0.12,
        edgecolor=metric["color"],
        linewidth=2,
        transform=ax.transAxes,
        clip_on=False,
    )
    ax.add_patch(rect)

    ax.text(
        0.5,
        0.82,
        metric["title"],
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=11,
        fontweight="bold",
        color="#2c3e50",
    )
    ax.text(
        0.5,
        0.48,
        metric["value"],
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=28,
        fontweight="bold",
        color=metric["color"],
    )
    ax.text(
        0.5,
        0.2,
        metric["subtitle"],
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=9,
        color="#7f8c8d",
    )


def _chart_health_summary(
    notes: list[dict[str, Any]],
    permanent_dir: Path,
    output_dir: Path,
) -> Path:
    """Dashboard-style health summary chart."""
    _apply_style()

    metrics = _compute_health_metrics(notes, permanent_dir)

    fig = plt.figure(figsize=(12, 6), layout="constrained")
    fig.suptitle("Knowledge Base Health Summary", fontsize=16, fontweight="bold")

    gs = GridSpec(1, 4, figure=fig, wspace=0.3)
    for i, metric in enumerate(metrics):
        ax = fig.add_subplot(gs[0, i])
        _draw_metric_card(ax, metric)

    out_path = output_dir / "health-summary.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# Public helper for auto-refresh
# ---------------------------------------------------------------------------


def _generate_all_charts(cfg: WikiConfig) -> list[Path]:
    """Generate all charts. Called by compile/lint for auto-refresh."""
    mpl.use("Agg")

    output_dir = cfg.output / "charts"
    output_dir.mkdir(parents=True, exist_ok=True)

    notes = _collect_all_frontmatter(cfg.wiki_permanent)
    generated: list[Path] = []

    chart_funcs: list[tuple[str, Callable[[], Path]]] = [
        ("tag-distribution", lambda: _chart_tag_distribution(notes, output_dir)),
        ("knowledge-type-distribution", lambda: _chart_knowledge_type_distribution(notes, output_dir)),
        ("confidence-distribution", lambda: _chart_confidence_distribution(notes, output_dir)),
        ("growth-over-time", lambda: _chart_growth_over_time(notes, output_dir)),
        ("health-summary", lambda: _chart_health_summary(notes, cfg.wiki_permanent, output_dir)),
    ]

    # Auto-refresh path: any chart failure must not block compile/lint.
    # Suppress all exceptions, including blind Exception catch.
    for _name, func in chart_funcs:
        with contextlib.suppress(Exception):
            generated.append(func())

    return generated


# ---------------------------------------------------------------------------
# Typer command
# ---------------------------------------------------------------------------


# Module-level Typer Option singletons (avoid B008 — calls in defaults).
_CHART_OPTION = typer.Option(
    None,
    "--chart",
    "-c",
    help=(
        "Generate a specific chart. Options: "
        "tag-distribution, knowledge-type-distribution, "
        "confidence-distribution, growth-over-time, health-summary "
        "(aliases: tags, knowledge, confidence, growth, health)"
    ),
)
_ALL_OPTION = typer.Option(False, "--all", "-a", help="Generate all charts.")
_OUTPUT_OPTION = typer.Option(
    None,
    "--output",
    "-o",
    help="Directory to save chart images. Defaults to output/charts/.",
)
_JSON_OPTION = typer.Option(False, "--json", "-j", help="Output result as JSON.")


def _resolve_charts_to_generate(chart: str | None, all_charts: bool) -> list[str]:
    """Map CLI flags to a concrete list of chart names. Exits on unknown chart."""
    if all_charts:
        return list(VALID_CHARTS)
    # Type narrowing: if not all_charts, the upstream caller has ensured chart is set.
    assert chart is not None  # noqa: S101  # pre-validated by caller
    resolved = CHART_ALIASES.get(chart, chart)
    if resolved not in VALID_CHARTS:
        typer.echo(f"Error: Unknown chart '{chart}'", err=True)
        raise typer.Exit(code=1)
    return [resolved]


_DISPATCH: dict[str, Callable[[list[dict[str, Any]], Path, Path], Path]] = {
    "tag-distribution": lambda notes, out, _perm: _chart_tag_distribution(notes, out),
    "knowledge-type-distribution": lambda notes, out, _perm: _chart_knowledge_type_distribution(notes, out),
    "confidence-distribution": lambda notes, out, _perm: _chart_confidence_distribution(notes, out),
    "growth-over-time": lambda notes, out, _perm: _chart_growth_over_time(notes, out),
    "health-summary": lambda notes, out, perm: _chart_health_summary(notes, perm, out),
}


def _dispatch_chart(
    chart_name: str,
    notes: list[dict[str, Any]],
    out: Path,
    permanent_dir: Path,
) -> Path | None:
    """Run the named chart generator. Returns None for unknown names."""
    func = _DISPATCH.get(chart_name)
    return None if func is None else func(notes, out, permanent_dir)


def charts(
    chart: str | None = _CHART_OPTION,
    all_charts: bool = _ALL_OPTION,
    output_dir: Path | None = _OUTPUT_OPTION,
    json_output: bool = _JSON_OPTION,
) -> None:
    """Render wiki visualization charts."""
    mpl.use("Agg")

    if not chart and not all_charts:
        typer.echo("Error: Specify --chart CHART_NAME or --all", err=True)
        raise typer.Exit(code=1)

    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e

    out = output_dir.resolve() if output_dir else cfg.output / "charts"
    out.mkdir(parents=True, exist_ok=True)

    notes = _collect_all_frontmatter(cfg.wiki_permanent)
    if not notes:
        typer.echo(
            f"No notes found in {cfg.wiki_permanent}. Charts will show empty state.",
            err=True,
        )

    charts_to_generate = _resolve_charts_to_generate(chart, all_charts)
    generated: list[str] = []
    for chart_name in charts_to_generate:
        typer.echo(f"Generating {chart_name}...", nl=False)
        try:
            path = _dispatch_chart(chart_name, notes, out, cfg.wiki_permanent)
        except Exception as e:  # noqa: BLE001  # CLI: report any failure and continue
            typer.echo(f" FAILED: {e}", err=True)
            continue
        if path is None:
            typer.echo(" SKIPPED (unknown)")
            continue
        generated.append(str(path))
        typer.echo(f" done -> {path}")

    if json_output:
        typer.echo(json.dumps({"generated": generated, "output_dir": str(out)}, indent=2))
    else:
        typer.echo(f"\nGenerated {len(generated)} chart(s) in {out}")
