"""One-page A4 PDF (fpdf2). Layout is compacted step by step until it fits on one page.

Only the notes sections come from the model; the table, reasons, limitations, method and sources come from
analysis.json and its summary."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import matplotlib
from fontTools.ttLib import TTFont
from fpdf import FPDF

from ..i18n import lang_name, t

FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
REGULAR, BOLD = FONT_DIR / "DejaVuSans.ttf", FONT_DIR / "DejaVuSans-Bold.ttf"
MARGIN = 12
# (max table rows, trust reasons per language, caveats, countries chart, base font size, chart height mm)
LEVELS = [(8, 3, 8, True, 8.0, 62), (8, 2, 6, False, 7.5, 62), (8, 1, 5, False, 7.0, 56), (6, 0, 4, False, 6.5, 50)]
COLS = ("pdf.col.lang", "pdf.col.share", "pdf.col.growth", "pdf.col.verdict", "pdf.col.trust",
        "pdf.col.season", "pdf.col.countries", "pdf.col.supply")
WIDTHS = (22, 16, 30, 22, 16, 18, 34, 28)          # sums to 186 mm = A4 width minus margins


@lru_cache(maxsize=1)
def _cmap() -> frozenset[int]:
    with TTFont(str(REGULAR)) as font:
        return frozenset(font.getBestCmap())


def font_covers(text: str) -> set[str]:
    """Characters of `text` that DejaVu Sans cannot render."""
    cmap = _cmap()
    return {ch for ch in text if not ch.isspace() and ord(ch) not in cmap}


def data_date(analysis: dict, ui: str) -> str:
    """'fetched <day>' for a live run, 'data through <day>' for an offline one."""
    prov = analysis.get("provenance", {})
    if prov.get("fetched_at"):
        return t(ui, "pdf.fetched", date=prov["fetched_at"][:10])
    return t(ui, "pdf.through", date=prov.get("data_through") or analysis["window"].get("last_day") or "—")


def title_counts(analysis: dict) -> tuple[int, int]:
    titles = [x for r in analysis["langs"].values() for x in r.get("titles", [])]
    return (sum(1 for x in titles if x["role"] in ("main", "extra")),
            sum(1 for x in titles if x["role"] in ("redirect", "old_title")))


def table_row(lang: str, facts: dict, ui: str) -> list[str]:
    f = facts.get(lang, {})
    growth = f.get("growth", "—")
    return [lang_name(lang, ui), f.get("share_per_m", "—"),
            f"{growth} ({f.get('growth_ci', '—')})" if growth != "—" else "—",
            f.get("verdict", "—"), f.get("trust", "—"), f.get("season", "—"),
            ", ".join(f.get("countries", [])) or "—", f.get("supply", "—")]


def _pdf() -> FPDF:
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_margins(MARGIN, 10, MARGIN)
    pdf.set_auto_page_break(True, margin=10)
    pdf.add_font("DejaVu", "", str(REGULAR))
    pdf.add_font("DejaVu", "B", str(BOLD))
    pdf.add_page()
    return pdf


def _heading(pdf: FPDF, text: str, size: float) -> None:
    pdf.set_font("DejaVu", "B", size + 1.5)
    pdf.cell(0, size * 0.6, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", size)


def _para(pdf: FPDF, text: str, size: float) -> None:
    pdf.set_font("DejaVu", "", size)
    pdf.multi_cell(0, size * 0.5, text, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(0.8)


def _draw(analysis: dict, summary: dict, notes: dict, charts: dict, ui: str, level: int) -> FPDF:
    rows_max, reasons_n, caveats_n, with_countries, size, chart_h = LEVELS[level]
    pdf = _pdf()
    proj, window = analysis["project"], analysis["window"]
    langs = list(proj["langs"])
    pdf.set_font("DejaVu", "B", size + 7)
    pdf.multi_cell(0, 7, proj.get("label") or proj.get("topic", ""), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", size)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(0, 4.5, t(ui, "pdf.subtitle", langs=", ".join(lang_name(code, ui) for code in langs),
                             start=window["start"], end=window["end"], source=proj.get("source") or "wikipedia",
                             date=data_date(analysis, ui)), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1.5)
    _heading(pdf, t(ui, "notes.h.conclusion"), size)
    _para(pdf, notes["conclusion"], size + 0.5)
    _heading(pdf, t(ui, "notes.h.recommendation"), size)
    _para(pdf, notes["recommendation"], size + 0.5)
    if notes.get("next") and level < 2:
        _heading(pdf, t(ui, "notes.h.next"), size)
        _para(pdf, notes["next"], size)

    _heading(pdf, t(ui, "pdf.h.table"), size)
    pdf.set_font("DejaVu", "", size - 0.5)
    with pdf.table(col_widths=WIDTHS, line_height=size * 0.48, text_align="LEFT", first_row_as_headings=True,
                   padding=0.6) as table:
        head = table.row()
        for col in COLS:
            head.cell(t(ui, col))
        for lang in langs[:rows_max]:
            row = table.row()
            for value in table_row(lang, summary["facts"], ui):
                row.cell(str(value))
    if len(langs) > rows_max:
        pdf.set_text_color(90, 90, 90)
        _para(pdf, t(ui, "pdf.more_langs", n=len(langs) - rows_max), size - 1)
        pdf.set_text_color(0, 0, 0)
    pdf.ln(1.5)

    # fixed boxes; keep_aspect_ratio stops a tall chart (many languages) from overlapping the text below
    y = pdf.get_y()
    if charts.get("share") or charts.get("growth"):
        if charts.get("share"):
            pdf.image(str(charts["share"]), x=MARGIN, y=y, w=112, h=chart_h, keep_aspect_ratio=True)
        if charts.get("growth"):
            pdf.image(str(charts["growth"]), x=MARGIN + 115, y=y, w=71, h=chart_h, keep_aspect_ratio=True)
        pdf.set_y(y + chart_h + 1)
    if with_countries and charts.get("countries"):
        y = pdf.get_y()
        pdf.image(str(charts["countries"]), x=MARGIN, y=y, w=150, h=52, keep_aspect_ratio=True)
        pdf.set_y(y + 53)

    if reasons_n:
        lines = []
        for lang in langs[:rows_max]:
            res = analysis["langs"].get(lang, {})
            if res.get("usable") and res["trust"]["reasons"]:
                reasons = "; ".join(t(ui, f"reason.{c}") for c in res["trust"]["reasons"][:reasons_n])
                lines.append(f"{lang_name(lang, ui)}: {reasons}")
        if lines:
            _heading(pdf, t(ui, "pdf.h.trust"), size)
            for line in lines:
                _para(pdf, line, size - 0.5)
    _heading(pdf, t(ui, "pdf.h.limits"), size)
    for caveat in summary["caveats"][:caveats_n]:
        _para(pdf, f"• {caveat}", size - 0.5)
    _heading(pdf, t(ui, "pdf.h.sources"), size)
    articles, redirects = title_counts(analysis)
    sources = t(ui, "pdf.sources", articles=articles, redirects=redirects, date=data_date(analysis, ui))
    if proj.get("qid"):
        sources += f" Wikidata: {proj['qid']}."
    pdf.set_text_color(80, 80, 80)
    _para(pdf, t(ui, "pdf.method") + " " + sources, size - 1)
    pdf.set_text_color(0, 0, 0)
    return pdf


def _close(pdf: FPDF) -> None:
    """fpdf2 loads fonts lazily and keeps the files open; close them once the document is written or dropped."""
    for font in pdf.fonts.values():
        if getattr(font, "ttfont", None) is not None:
            font.ttfont.close()


def render_pdf(analysis: dict, summary: dict, notes: dict, charts: dict, out: Path, ui: str) -> int:
    """Write the first layout that fits on one page; returns the page count (1 unless even level 3 overflows)."""
    for level in range(len(LEVELS)):
        pdf = _draw(analysis, summary, notes, charts, ui, level)
        if pdf.page_no() == 1 or level == len(LEVELS) - 1:
            break
        _close(pdf)
    try:
        pdf.output(str(out))
        return pdf.page_no()
    finally:
        _close(pdf)
