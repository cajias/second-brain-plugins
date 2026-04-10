"""Render visualizations for the wiki knowledge base.

Generates charts showing tag distribution, knowledge type breakdown,
confidence levels, growth over time, and a health summary dashboard
using matplotlib.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from llm_wiki.core.config import load_config, WikiConfig
from llm_wiki.core.frontmatter import parse_file


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


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


def _collect_all_frontmatter(permanent_dir: Path) -> list[dict]:
    """Read frontmatter from all permanent notes."""
    notes = []
    if not permanent_dir.exists():
        return notes

    for md_file in sorted(permanent_dir.glob("*.md")):
        try:
            fm, _ = parse_file(md_file)
        except Exception:
            continue
        if fm:
            fm["_filename"] = md_file.stem
            notes.append(fm)

    return notes


def _collect_link_data(permanent_dir: Path) -> dict:
    """Build basic link stats for health summary."""
    nodes: dict[str, dict] = {}
    if not permanent_dir.exists():
        return {"total": 0, "orphans": 0}

    md_files = sorted(permanent_dir.glob("*.md"))
    for md_file in md_files:
        nodes[md_file.stem] = {"linked_from": set()}

    for md_file in md_files:
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
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
    import matplotlib.pyplot as plt
    try:
        plt.style.use(CHART_STYLE)
    except OSError:
        try:
            plt.style.use("seaborn-v0_8")
        except OSError:
            pass


def _empty_chart(output_path: Path, title: str, message: str) -> Path:
    """Generate a placeholder chart when no data is available."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.text(
        0.5, 0.5, message,
        transform=ax.transAxes, ha="center", va="center",
        fontsize=14, color="#7f8c8d", style="italic",
    )
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.axis("off")
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def _chart_tag_distribution(notes: list[dict], output_dir: Path) -> Path:
    """Horizontal bar chart of note count per tag."""
    import matplotlib.pyplot as plt
    _apply_style()

    tag_counts = Counter()
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
    colors = []
    for v in values:
        ratio = v / max_val
        if ratio >= 0.6:
            colors.append("#2ecc71")
        elif ratio >= 0.3:
            colors.append("#f1c40f")
        else:
            colors.append("#e67e22")

    fig, ax = plt.subplots(figsize=(10, max(4, len(labels) * 0.4)))
    bars = ax.barh(labels, values, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Number of Notes")
    ax.set_title("Tag Distribution", fontsize=14, fontweight="bold", pad=15)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_width() + 0.1,
            bar.get_y() + bar.get_height() / 2,
            str(val), va="center", fontsize=9,
        )

    ax.set_xlim(0, max(values) * 1.15)
    plt.tight_layout()
    out_path = output_dir / "tag-distribution.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _chart_knowledge_type_distribution(notes: list[dict], output_dir: Path) -> Path:
    """Donut chart of knowledge type proportions."""
    import matplotlib.pyplot as plt
    _apply_style()

    kt_counts = Counter()
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
    colors = [KNOWLEDGE_TYPE_COLORS.get(l, "#95a5a6") for l in labels]

    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, autopct="%1.0f%%",
        colors=colors, startangle=90, pctdistance=0.8,
        wedgeprops=dict(width=0.4, edgecolor="white", linewidth=2),
    )

    for autotext in autotexts:
        autotext.set_fontsize(10)
        autotext.set_fontweight("bold")

    ax.set_title("Knowledge Type Distribution", fontsize=14, fontweight="bold", pad=20)
    ax.text(0, 0, f"{sum(values)}\nnotes", ha="center", va="center",
            fontsize=16, fontweight="bold")

    plt.tight_layout()
    out_path = output_dir / "knowledge-type-distribution.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _chart_confidence_distribution(notes: list[dict], output_dir: Path) -> Path:
    """Bar chart of confidence levels."""
    import matplotlib.pyplot as plt
    _apply_style()

    conf_counts = Counter()
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

    values = [conf_counts[l] for l in ordered_labels]
    colors = [CONFIDENCE_COLORS.get(l, "#95a5a6") for l in ordered_labels]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(ordered_labels, values, color=colors, edgecolor="white",
                  linewidth=1.5, width=0.5)
    ax.set_ylabel("Number of Notes")
    ax.set_title("Confidence Distribution", fontsize=14, fontweight="bold", pad=15)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.2,
            str(val), ha="center", va="bottom", fontsize=11, fontweight="bold",
        )

    ax.set_ylim(0, max(values) * 1.2 if values else 1)
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    plt.tight_layout()
    out_path = output_dir / "confidence-distribution.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _chart_growth_over_time(notes: list[dict], output_dir: Path) -> Path:
    """Line chart of cumulative note count over time."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    _apply_style()

    dates = []
    for fm in notes:
        created = fm.get("created")
        if created is None:
            continue
        if isinstance(created, datetime):
            dates.append(created.date())
        elif isinstance(created, str):
            try:
                dates.append(datetime.fromisoformat(created).date())
            except (ValueError, TypeError):
                for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        dates.append(datetime.strptime(created, fmt).date())
                        break
                    except ValueError:
                        continue
        elif hasattr(created, "year"):
            dates.append(created)

    if not dates:
        return _empty_chart(
            output_dir / "growth-over-time.png",
            "Growth Over Time",
            "No creation dates found in notes.",
        )

    dates.sort()

    span_days = (dates[-1] - dates[0]).days if len(dates) > 1 else 0
    group_by_month = span_days > 60

    if group_by_month:
        monthly: dict = defaultdict(int)
        for d in dates:
            key = d.replace(day=1)
            monthly[key] += 1
        sorted_keys = sorted(monthly.keys())
        cumulative = []
        total = 0
        for m in sorted_keys:
            total += monthly[m]
            cumulative.append(total)
        x_vals = sorted_keys
        y_vals = cumulative
        x_label = "Month"
    else:
        daily: dict = defaultdict(int)
        for d in dates:
            daily[d] += 1
        sorted_keys = sorted(daily.keys())
        cumulative = []
        total = 0
        for day in sorted_keys:
            total += daily[day]
            cumulative.append(total)
        x_vals = sorted_keys
        y_vals = cumulative
        x_label = "Date"

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(
        x_vals, y_vals, marker="o", linewidth=2, markersize=6,
        color="#3498db", markerfacecolor="#2c3e50", markeredgecolor="#2c3e50",
    )
    ax.fill_between(x_vals, y_vals, alpha=0.15, color="#3498db")
    ax.set_xlabel(x_label)
    ax.set_ylabel("Cumulative Notes")
    ax.set_title("Knowledge Base Growth", fontsize=14, fontweight="bold", pad=15)
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))

    if group_by_month:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    else:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))

    fig.autofmt_xdate(rotation=45)
    plt.tight_layout()
    out_path = output_dir / "growth-over-time.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _chart_health_summary(
    notes: list[dict], permanent_dir: Path, output_dir: Path,
) -> Path:
    """Dashboard-style health summary chart."""
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    _apply_style()

    total_notes = len(notes)
    link_data = _collect_link_data(permanent_dir)
    orphan_count = link_data["orphans"]
    orphan_pct = (orphan_count / total_notes * 100) if total_notes > 0 else 0

    tagged = sum(
        1 for fm in notes
        if isinstance(fm.get("tags"), list) and len(fm["tags"]) > 0
    )
    tag_compliance_pct = (tagged / total_notes * 100) if total_notes > 0 else 0

    confidence_map = {"high": 1.0, "medium": 0.5, "low": 0.0}
    conf_values = [
        confidence_map.get(str(fm.get("confidence", "")), 0.0) for fm in notes
    ]
    avg_confidence = sum(conf_values) / len(conf_values) if conf_values else 0
    avg_confidence_label = (
        "High" if avg_confidence >= 0.7
        else "Medium" if avg_confidence >= 0.4
        else "Low"
    )

    fig = plt.figure(figsize=(12, 6), layout="constrained")
    fig.suptitle("Knowledge Base Health Summary", fontsize=16, fontweight="bold")

    gs = GridSpec(1, 4, figure=fig, wspace=0.3)

    metrics = [
        {
            "title": "Total Notes", "value": str(total_notes),
            "color": "#3498db", "subtitle": "in permanent/",
        },
        {
            "title": "Orphan Rate",
            "value": f"{orphan_pct:.0f}%",
            "color": "#2ecc71" if orphan_pct < 30 else "#f39c12" if orphan_pct < 60 else "#e74c3c",
            "subtitle": f"{orphan_count} orphans",
        },
        {
            "title": "Tag Compliance",
            "value": f"{tag_compliance_pct:.0f}%",
            "color": "#2ecc71" if tag_compliance_pct >= 80 else "#f39c12" if tag_compliance_pct >= 50 else "#e74c3c",
            "subtitle": f"{tagged}/{total_notes} tagged",
        },
        {
            "title": "Avg Confidence",
            "value": avg_confidence_label,
            "color": "#2ecc71" if avg_confidence >= 0.7 else "#f39c12" if avg_confidence >= 0.4 else "#e74c3c",
            "subtitle": f"score: {avg_confidence:.2f}",
        },
    ]

    for i, metric in enumerate(metrics):
        ax = fig.add_subplot(gs[0, i])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

        rect = plt.Rectangle(
            (0.05, 0.05), 0.9, 0.9,
            facecolor=metric["color"], alpha=0.12,
            edgecolor=metric["color"], linewidth=2,
            transform=ax.transAxes, clip_on=False,
        )
        ax.add_patch(rect)

        ax.text(0.5, 0.82, metric["title"], transform=ax.transAxes,
                ha="center", va="center", fontsize=11, fontweight="bold",
                color="#2c3e50")
        ax.text(0.5, 0.48, metric["value"], transform=ax.transAxes,
                ha="center", va="center", fontsize=28, fontweight="bold",
                color=metric["color"])
        ax.text(0.5, 0.2, metric["subtitle"], transform=ax.transAxes,
                ha="center", va="center", fontsize=9, color="#7f8c8d")

    out_path = output_dir / "health-summary.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# Public helper for auto-refresh
# ---------------------------------------------------------------------------


def _generate_all_charts(cfg: WikiConfig) -> list[Path]:
    """Generate all charts. Called by compile/lint for auto-refresh."""
    import matplotlib
    matplotlib.use("Agg")

    output_dir = cfg.output / "charts"
    output_dir.mkdir(parents=True, exist_ok=True)

    notes = _collect_all_frontmatter(cfg.wiki_permanent)
    generated = []

    chart_funcs = [
        ("tag-distribution", lambda: _chart_tag_distribution(notes, output_dir)),
        ("knowledge-type-distribution", lambda: _chart_knowledge_type_distribution(notes, output_dir)),
        ("confidence-distribution", lambda: _chart_confidence_distribution(notes, output_dir)),
        ("growth-over-time", lambda: _chart_growth_over_time(notes, output_dir)),
        ("health-summary", lambda: _chart_health_summary(notes, cfg.wiki_permanent, output_dir)),
    ]

    for name, func in chart_funcs:
        try:
            path = func()
            generated.append(path)
        except Exception:
            pass

    return generated


# ---------------------------------------------------------------------------
# Typer command
# ---------------------------------------------------------------------------


def charts(
    chart: Optional[str] = typer.Option(
        None, "--chart", "-c",
        help=(
            "Generate a specific chart. Options: "
            "tag-distribution, knowledge-type-distribution, "
            "confidence-distribution, growth-over-time, health-summary "
            "(aliases: tags, knowledge, confidence, growth, health)"
        ),
    ),
    all_charts: bool = typer.Option(
        False, "--all", "-a", help="Generate all charts.",
    ),
    output_dir: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Directory to save chart images. Defaults to output/charts/.",
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="Output result as JSON.",
    ),
) -> None:
    """Render wiki visualization charts."""
    import matplotlib
    matplotlib.use("Agg")

    if not chart and not all_charts:
        typer.echo("Error: Specify --chart CHART_NAME or --all", err=True)
        raise typer.Exit(code=1)

    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    # Determine output directory
    if output_dir:
        out = output_dir.resolve()
    else:
        out = cfg.output / "charts"
    out.mkdir(parents=True, exist_ok=True)

    notes = _collect_all_frontmatter(cfg.wiki_permanent)

    if not notes:
        typer.echo(
            f"No notes found in {cfg.wiki_permanent}. Charts will show empty state.",
            err=True,
        )

    # Resolve aliases
    if all_charts:
        charts_to_generate = VALID_CHARTS
    else:
        resolved = CHART_ALIASES.get(chart, chart)
        if resolved not in VALID_CHARTS:
            typer.echo(f"Error: Unknown chart '{chart}'", err=True)
            raise typer.Exit(code=1)
        charts_to_generate = [resolved]

    generated = []
    for chart_name in charts_to_generate:
        typer.echo(f"Generating {chart_name}...", nl=False)
        try:
            if chart_name == "tag-distribution":
                path = _chart_tag_distribution(notes, out)
            elif chart_name == "knowledge-type-distribution":
                path = _chart_knowledge_type_distribution(notes, out)
            elif chart_name == "confidence-distribution":
                path = _chart_confidence_distribution(notes, out)
            elif chart_name == "growth-over-time":
                path = _chart_growth_over_time(notes, out)
            elif chart_name == "health-summary":
                path = _chart_health_summary(notes, cfg.wiki_permanent, out)
            else:
                typer.echo(f" SKIPPED (unknown)")
                continue
            generated.append(str(path))
            typer.echo(f" done -> {path}")
        except Exception as e:
            typer.echo(f" FAILED: {e}", err=True)

    if json_output:
        typer.echo(json.dumps({"generated": generated, "output_dir": str(out)}, indent=2))
    else:
        typer.echo(f"\nGenerated {len(generated)} chart(s) in {out}")
