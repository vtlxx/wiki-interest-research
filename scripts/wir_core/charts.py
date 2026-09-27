"""PNG charts from analysis.json (no statistics here — only drawing)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from .i18n import lang_name, t  # noqa: E402
from .incidents import load as load_incidents  # noqa: E402

# Colour-blind safe (Okabe–Ito; yellow and black swapped for hues that read on white; slot 8 is the least bad
# indigo — it passes the colour-blind checks but sits close to slot 1 for normal vision, so it always has a label).
PALETTE = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#882255", "#4B3BA8"]
# Verdicts are a status, not an identity: a blue/red diverging pair plus greys; the verdict is also written as text.
VERDICT_COLORS = {"growing": "#2166AC", "declining": "#B2182B", "stable": "#7F7F7F", "unclear": "#BDBDBD"}
# Countries differ per language, so they get an ordinal grey ramp (by rank) and a text label, never a language hue.
COUNTRY_RAMP = ["#3D3D3D", "#5E5E5E", "#9A9A9A", "#B8B8B8", "#D2D2D2"]
OTHER_COLOR = "#EDEDED"
INK, MUTED, GRID, SHADE = "#222222", "#555555", "#DDDDDD", "#9E9E9E"
SHADED = ("medium", "high")          # low severity = small or since corrected: not worth shading
DPI = 200
# Figures are drawn close to the size the one-page PDF prints them at (share 112×62 mm, growth 71×62 mm),
# so 8-pt text stays at ≥6 pt on paper for up to ~5 languages (more languages make growth/countries taller).
STYLE = {"font.family": "DejaVu Sans", "font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
         "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.edgecolor": MUTED, "axes.labelcolor": INK,
         "axes.labelsize": 8, "xtick.labelsize": 8, "ytick.labelsize": 8, "xtick.color": MUTED,
         "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
         "axes.axisbelow": True, "legend.frameon": False, "legend.fontsize": 8}
MID_MONTH = pd.Timedelta(days=14)    # a monthly value is drawn in the middle of its month


def _usable(analysis: dict) -> list[str]:
    return [lang for lang in analysis["project"]["langs"] if analysis["langs"].get(lang, {}).get("usable")]


def _colors(analysis: dict) -> dict[str, str]:
    """One colour per language, fixed by project order, on every chart."""
    return {lang: PALETTE[i % len(PALETTE)] for i, lang in enumerate(analysis["project"]["langs"])}


def _month_x(month: str) -> pd.Timestamp:
    return pd.Timestamp(month[:7] + "-01") + MID_MONTH


def _monthly(res: dict) -> pd.Series:
    rows = [(_month_x(r["month"]), r["share"]) for r in res.get("monthly", [])]
    return pd.Series({ts: np.nan if v is None else v for ts, v in rows}, dtype=float)


def _source_line(analysis: dict, ui: str) -> str:
    prov = analysis.get("provenance") or {}
    if prov.get("fetched_at"):
        return t(ui, "chart.source", date=prov["fetched_at"][:10])
    if prov.get("data_through"):                     # offline run: no fetch happened, say how fresh the data is
        return t(ui, "chart.source_through", date=prov["data_through"][:10])
    return t(ui, "chart.source_plain")


def _footer(fig, analysis: dict, ui: str, wrap: int | None = None) -> None:
    # Place it under everything already drawn (tick labels of short or rotated axes reach below y=0).
    renderer = fig.canvas.get_renderer()
    boxes = [ax.get_tightbbox(renderer) for ax in fig.axes if ax.axison]
    x0, y0 = fig.transFigure.inverted().transform((min(b.x0 for b in boxes), min(b.y0 for b in boxes)))
    text = _source_line(analysis, ui)
    if wrap:
        text = textwrap.fill(text, wrap)
    fig.text(x0, y0 - 0.02, text, fontsize=6.5, color=MUTED, ha="left", va="top")


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight", pad_inches=0.08, facecolor="white")
    plt.close(fig)
    return path


def _log_scale(series: list[pd.Series]) -> bool:
    """Log y-axis when typical levels differ more than 10×."""
    medians = [m for m in (s[s > 0].median() for s in series) if not np.isnan(m)]
    return len(medians) >= 2 and max(medians) / min(medians) > 10


def _incident_spans(analysis: dict, langs: list[str]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    start, end = pd.Timestamp(analysis["window"]["start"]), pd.Timestamp(analysis["window"]["end"])
    ids = {i for lang in langs for i in analysis["langs"][lang].get("incidents", [])}
    spans = []
    for incident in load_incidents():
        if incident.id in ids and incident.severity in SHADED:
            lo = max(pd.Timestamp(incident.start), start)
            hi = min(pd.Timestamp(incident.end), end) + pd.Timedelta(days=1)
            if lo < hi:
                spans.append((lo, hi))
    return spans


def _moves(analysis: dict, langs: list[str]) -> list[pd.Timestamp]:
    start, end = pd.Timestamp(analysis["window"]["start"]), pd.Timestamp(analysis["window"]["end"])
    days = {pd.Timestamp(mv["when"][:10]) for lang in langs for mv in analysis["langs"][lang].get("moves", [])}
    return sorted(d for d in days if start <= d <= end)


def _window_months(analysis: dict) -> int:
    start, end = pd.Timestamp(analysis["window"]["start"]), pd.Timestamp(analysis["window"]["end"])
    return (end.year - start.year) * 12 + end.month - start.month + 1


def _date_axis(ax, months: int, narrow: bool = False) -> None:
    """Tick step from the window length, so labels never run together (a small panel counts double)."""
    span = months * (2 if narrow else 1)
    if span <= 8:
        loc, fmt = mdates.MonthLocator(), "%Y-%m"
    elif span <= 15:
        loc, fmt = mdates.MonthLocator(bymonth=(1, 4, 7, 10)), "%Y-%m"
    elif span <= 36:
        loc, fmt = mdates.MonthLocator(bymonth=(1, 7)), "%Y-%m"
    else:
        loc, fmt = mdates.YearLocator(1 if span <= 84 else 2 if span <= 168 else 5), "%Y"
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))


def _decorate_timeline(ax, analysis: dict, langs: list[str], ui: str, narrow: bool = False) -> dict[str, bool]:
    """Shade data incidents, mark renames, set date ticks; returns which extra legend entries are needed."""
    spans, moves = _incident_spans(analysis, langs), _moves(analysis, langs)
    for lo, hi in spans:
        ax.axvspan(lo, hi, color=SHADE, alpha=0.22, lw=0, zorder=0)
    for day in moves:
        ax.axvline(day, color=MUTED, ls="--", lw=0.9, zorder=1)
        ax.text(day, 0.99, t(ui, "chart.rename"), transform=ax.get_xaxis_transform(), fontsize=6.5,
                va="top", ha="left", color=MUTED, zorder=5,
                bbox={"boxstyle": "square,pad=0.15", "fc": "white", "ec": "none", "alpha": 0.85})
    _date_axis(ax, _window_months(analysis), narrow)
    ax.grid(axis="x", visible=False)
    return {"incident": bool(spans), "rename": bool(moves)}


def _extra_handles(ui: str, flags: dict[str, bool]) -> list:
    handles = []
    if flags.get("spike"):
        handles.append(Line2D([], [], ls="none", marker="v", color=MUTED, markersize=5, label=t(ui, "chart.spike")))
    if flags.get("incident"):
        handles.append(Patch(color=SHADE, alpha=0.35, lw=0, label=t(ui, "chart.incident")))
    if flags.get("rename"):
        handles.append(Line2D([], [], color=MUTED, ls="--", lw=0.9, label=t(ui, "chart.rename")))
    return handles


def _title_and_legend(ax, title: str, handles: list) -> None:
    """Title, then the legend in one or two rows between the title and the plot (keeps the bottom for the footer)."""
    if not handles:
        ax.set_title(title, loc="left")
        return
    ncol = min(len(handles), 4)
    rows = int(np.ceil(len(handles) / ncol))
    ax.set_title(title, loc="left", pad=6 + 12 * rows)
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=ncol, borderaxespad=0.2,
              handlelength=1.5, columnspacing=1.0)


def _percent_axis(axis) -> None:
    axis.set_major_locator(mticker.MaxNLocator(nbins=6, steps=[1, 2, 2.5, 5, 10], integer=True))
    axis.set_major_formatter(mticker.PercentFormatter(decimals=0))


def _spike_marks(ax, series: pd.Series, res: dict, color: str) -> bool:
    """A small triangle just above the month of each top spike episode (the point itself stays visible)."""
    drawn = False
    for ep in res.get("spikes", {}).get("episodes", [])[:3]:
        x = _month_x(ep["peak"])
        if x in series.index and not np.isnan(series[x]):
            ax.annotate("▼", xy=(x, series[x]), xytext=(0, 3), textcoords="offset points", ha="center",
                        va="bottom", fontsize=7, color=color, zorder=4)
            drawn = True
    return drawn


def _plain_log_axis(ax) -> None:
    ax.yaxis.set_major_locator(mticker.LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.yaxis.set_minor_formatter(mticker.NullFormatter())


def _small_multiples(analysis: dict, langs: list[str], series: dict, colors: dict, ui: str):
    cols = 3
    rows = int(np.ceil(len(langs) / cols))
    head = 0.52                                              # inches for the title and the legend row
    height = 1.25 * rows + head
    fig, axes = plt.subplots(rows, cols, figsize=(5.4, height), sharex=True, squeeze=False)
    flags: dict[str, bool] = {}
    for ax, lang in zip(axes.flat, langs):
        s = series[lang]
        ax.plot(s.index, s.values, color=colors[lang], lw=1.6)
        flags["spike"] = _spike_marks(ax, s, analysis["langs"][lang], colors[lang]) or flags.get("spike", False)
        ax.set_title(lang_name(lang, ui), fontsize=8, loc="left", pad=3)
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=3))
        for k, v in _decorate_timeline(ax, analysis, [lang], ui, narrow=True).items():
            flags[k] = flags.get(k, False) or v
        ax.tick_params(labelsize=7)
    for i, ax in enumerate(axes.flat):
        if i >= len(langs):
            ax.axis("off")
        elif i + cols >= len(langs):                         # nothing below it: it needs its own dates
            ax.xaxis.set_tick_params(labelbottom=True)
    fig.supylabel(t(ui, "chart.share.y"), fontsize=7.5, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 1 - head / height), h_pad=0.6, w_pad=0.8)
    fig.text(0.01, 1 - 0.02 / height, t(ui, "chart.share.title"), fontsize=9.5, fontweight="bold", va="top")
    extras = _extra_handles(ui, flags)
    if extras:
        fig.legend(handles=extras, loc="upper left", bbox_to_anchor=(0.0, 1 - 0.22 / height), ncol=len(extras),
                   handlelength=1.5, columnspacing=1.0)
    return fig


def share_chart(analysis: dict, out: Path, ui: str) -> Path:
    langs, colors = _usable(analysis), _colors(analysis)
    series = {lang: _monthly(analysis["langs"][lang]) for lang in langs}
    with plt.rc_context(STYLE):
        if len(langs) >= 5:
            fig = _small_multiples(analysis, langs, series, colors, ui)
        else:
            log = _log_scale(list(series.values()))
            fig, ax = plt.subplots(figsize=(5.0, 2.9))
            flags: dict[str, bool] = {}
            for lang in langs:
                s = series[lang].where(series[lang] > 0) if log else series[lang]   # log(0) cannot be drawn
                if s.notna().any():
                    ax.plot(s.index, s.values, color=colors[lang], lw=1.8, label=lang_name(lang, ui))
                flags["spike"] = _spike_marks(ax, s, analysis["langs"][lang], colors[lang]) or flags.get("spike", False)
            if log:
                ax.set_yscale("log")
                _plain_log_axis(ax)
            else:
                ax.set_ylim(bottom=0)
            ax.set_ylabel(t(ui, "chart.share.y"))
            flags.update(_decorate_timeline(ax, analysis, langs, ui))
            _title_and_legend(ax, t(ui, "chart.share.title"), ax.get_legend_handles_labels()[0] + _extra_handles(ui, flags))
        _footer(fig, analysis, ui)
        return _save(fig, out / "share.png")


def index_chart(analysis: dict, out: Path, ui: str) -> Path:
    langs, colors = _usable(analysis), _colors(analysis)
    series = {lang: _monthly(analysis["langs"][lang]) for lang in langs}
    with_data = [int(s.notna().sum()) for s in series.values() if s.notna().any()]
    base_n = 12 if with_data and min(with_data) >= 24 else 3     # one base length for all, so the title is true
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(5.0, 2.9))
        for lang in langs:
            s = series[lang]
            base = s.dropna().head(base_n).mean()             # a young article starts at its first month with data
            if base and not np.isnan(base):
                ax.plot(s.index, s / base * 100, color=colors[lang], lw=1.8, label=lang_name(lang, ui))
        ax.axhline(100, color=MUTED, lw=0.8)
        flags = _decorate_timeline(ax, analysis, langs, ui)
        title = t(ui, "chart.index.title" if base_n == 12 else "chart.index.title3")
        _title_and_legend(ax, title, ax.get_legend_handles_labels()[0] + _extra_handles(ui, flags))
        _footer(fig, analysis, ui)
        return _save(fig, out / "index.png")


def growth_chart(analysis: dict, out: Path, ui: str) -> Path | None:
    """Narrow (it shares a PDF row with share.png): each bar carries its label line above it."""
    langs = [lang for lang in _usable(analysis) if analysis["langs"][lang].get("growth")]
    if not langs:
        return None
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(3.5, 0.36 * len(langs) + 0.95))
        ys = list(range(len(langs)))[::-1]                    # first language on top
        for y, lang in zip(ys, langs):
            res = analysis["langs"][lang]
            g = res["growth"]
            color = VERDICT_COLORS.get(g["verdict"], VERDICT_COLORS["unclear"])
            ax.barh(y, g["g"] * 100, color=color, height=0.36, zorder=2)
            ax.errorbar(g["g"] * 100, y, xerr=[[max(0.0, (g["g"] - g["lo"]) * 100)], [max(0.0, (g["hi"] - g["g"]) * 100)]],
                        fmt="none", ecolor=INK, capsize=2.5, lw=1, zorder=3)
            label = f"{lang_name(lang, ui)} — {t(ui, 'verdict.' + g['verdict'])} · " + \
                t(ui, "chart.trust", level=t(ui, f"trust.{res['trust']['level']}"))
            ax.text(0.0, y + 0.24, label, transform=ax.get_yaxis_transform(), va="bottom", ha="left", fontsize=7.5,
                    color=INK, zorder=4, bbox={"boxstyle": "square,pad=0.1", "fc": "white", "ec": "none"})
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
        ax.set_ylim(-0.4, len(langs) - 0.2)
        lo = min(0.0, *(analysis["langs"][lang]["growth"]["lo"] for lang in langs)) * 100
        hi = max(0.0, *(analysis["langs"][lang]["growth"]["hi"] for lang in langs)) * 100
        pad = max(3.0, (hi - lo) * 0.06)
        ax.set_xlim(lo - pad, hi + pad)
        ax.axvline(0, color=INK, lw=0.8, zorder=2)
        ax.grid(axis="y", visible=False)
        _percent_axis(ax.xaxis)
        ax.set_title(textwrap.fill(t(ui, "chart.growth.title"), 34), loc="left")
        _footer(fig, analysis, ui, wrap=60)
        return _save(fig, out / "growth.png")


def countries_chart(analysis: dict, out: Path, ui: str) -> Path | None:
    langs = [lang for lang in _usable(analysis) if analysis["langs"][lang].get("countries")]
    if not langs:
        return None
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(5.4, 0.28 * len(langs) + 0.85))
        ys = list(range(len(langs)))[::-1]
        for y, lang in zip(ys, langs):
            left, small = 0.0, []
            for i, (code, share) in enumerate(analysis["langs"][lang]["countries"][:5]):
                width = share * 100
                ax.barh(y, width, left=left, color=COUNTRY_RAMP[i], height=0.62, edgecolor="white", lw=1.0)
                ink = "white" if i < 2 else INK
                if width >= 10:
                    ax.text(left + width / 2, y, f"{code} {width:.0f}%", ha="center", va="center", fontsize=7,
                            color=ink)
                elif width >= 3:
                    ax.text(left + width / 2, y, code, ha="center", va="center", fontsize=6.5, color=ink)
                if width < 10:
                    small.append(f"{code} {width:.0f}%" if width >= 0.5 else f"{code} <1%")
                left += width
            if small:                                           # the exact figure of every country not labelled so
                ax.text(1.02, y, ", ".join(small), transform=ax.get_yaxis_transform(), va="center", fontsize=7,
                        color=INK)
            rest = max(0.0, 100 - left)
            ax.barh(y, rest, left=left, color=OTHER_COLOR, height=0.62, edgecolor="white", lw=1.0)
            if rest >= 12:
                ax.text(left + rest / 2, y, t(ui, "chart.countries.other"), ha="center", va="center", fontsize=7,
                        color=MUTED)
        ax.set_yticks(ys, [lang_name(lang, ui) for lang in langs])
        ax.set_ylim(-0.5, len(langs) - 0.5)
        ax.set_xlim(0, 100)
        ax.grid(False)
        ax.tick_params(axis="y", length=0, labelcolor=INK)
        ax.xaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
        ax.set_title(t(ui, "chart.countries.title"), loc="left")
        _footer(fig, analysis, ui)
        return _save(fig, out / "countries.png")


def season_chart(analysis: dict, out: Path, ui: str) -> Path | None:
    langs = [lang for lang in _usable(analysis)
             if (analysis["langs"][lang].get("seasonality") or {}).get("level") in ("moderate", "strong")]
    if not langs:
        return None
    colors = _colors(analysis)
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(5.0, 2.8))
        months = list(range(1, 13))
        for lang in langs:
            # stats stores the profile in log units (deviation of log share from its yearly mean)
            profile = np.array(analysis["langs"][lang]["seasonality"]["profile"], dtype=float)
            ax.plot(months, (np.exp(profile) - 1) * 100, color=colors[lang], lw=1.8, marker="o", ms=4,
                    markeredgecolor="white", markeredgewidth=0.8, label=lang_name(lang, ui))
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.set_xticks(months, [t(ui, f"chart.month.{m}") for m in months])
        ax.grid(axis="x", visible=False)
        _percent_axis(ax.yaxis)
        _title_and_legend(ax, t(ui, "chart.season.title"), ax.get_legend_handles_labels()[0])
        _footer(fig, analysis, ui)
        return _save(fig, out / "season.png")


def render_all(analysis: dict, out_dir: Path, ui: str) -> dict[str, Path]:
    if not _usable(analysis):
        return {}
    out_dir = Path(out_dir)
    files: dict[str, Path] = {"share": share_chart(analysis, out_dir, ui), "index": index_chart(analysis, out_dir, ui)}
    for name, fn in (("growth", growth_chart), ("countries", countries_chart), ("season", season_chart)):
        path = fn(analysis, out_dir, ui)
        if path:
            files[name] = path
        else:
            (out_dir / f"{name}.png").unlink(missing_ok=True)   # never leave a chart from an earlier run
    return files
