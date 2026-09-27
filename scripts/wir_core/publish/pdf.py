"""One-page A4 PDF (fpdf2). Layout is compacted step by step until it fits on one page.

Only the notes sections come from the model; the table, reasons, limitations, method and sources come from
analysis.json and its summary."""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

import matplotlib
from fontTools.ttLib import TTFont
from fpdf import FPDF
from PIL import Image

from ..i18n import lang_name, t

FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
REGULAR, BOLD = FONT_DIR / "DejaVuSans.ttf", FONT_DIR / "DejaVuSans-Bold.ttf"
MARGIN = 12
# (max table rows, trust reasons per language, caveats, countries chart, base font size, chart height mm)
# caveats None = all of them
LEVELS = [(8, 3, None, True, 8.0, 62), (8, 2, None, True, 7.5, 58), (8, 2, 6, False, 7.5, 62),
          (8, 1, 5, False, 7.0, 56), (6, 0, 4, False, 6.5, 50)]
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


def rtl_chars(text: str) -> set[str]:
    """Right-to-left letters: fpdf2 without a shaping engine would print them reversed and unjoined."""
    return {ch for ch in text if unicodedata.bidirectional(ch) in ("R", "AL")}


def _safe(text: str) -> str:
    """Data text (titles in caveats, labels) with characters the PDF cannot draw replaced; report.md keeps them."""
    bad = font_covers(text) | rtl_chars(text)
    return "".join("?" if ch in bad else ch for ch in text) if bad else text


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
    pdf.cell(0, size * 0.6, _safe(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", size)


def _para(pdf: FPDF, text: str, size: float) -> None:
    pdf.set_font("DejaVu", "", size)
    pdf.multi_cell(0, size * 0.5, _safe(text), new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.ln(0.8)


def _image(pdf: FPDF, path: Path, x: float, y: float, box_w: float, box_h: float) -> float:
    """Draw the chart as large as fits the box, top-left aligned; returns the height used."""
    with Image.open(path) as img:
        px_w, px_h = img.size
    scale = min(box_w / px_w, box_h / px_h)
    pdf.image(str(path), x=x, y=y, w=px_w * scale, h=px_h * scale)
    return px_h * scale


def _draw(analysis: dict, summary: dict, notes: dict, charts: dict, ui: str, level: int) -> FPDF:
    rows_max, reasons_n, caveats_n, with_countries, size, chart_h = LEVELS[level]
    pdf = _pdf()
    proj, window = analysis["project"], analysis["window"]
    langs = list(proj["langs"])
    pdf.set_font("DejaVu", "B", size + 7)
    pdf.multi_cell(0, 7, _safe(proj.get("label") or proj.get("topic", "")), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", size)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(0, 4.5, align="L", text=_safe(t(ui, "pdf.subtitle", langs=", ".join(lang_name(code, ui) for code in langs),
                             start=window["start"], end=window["end"], source=proj.get("source") or "wikipedia",
                             date=data_date(analysis, ui))), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1.5)
    _heading(pdf, t(ui, "notes.h.conclusion"), size)
    _para(pdf, notes["conclusion"], size + 0.5)
    _heading(pdf, t(ui, "notes.h.recommendation"), size)
    _para(pdf, notes["recommendation"], size + 0.5)
    if notes.get("next") and level < 3:
        _heading(pdf, t(ui, "notes.h.next"), size)
        _para(pdf, notes["next"], size)

    _heading(pdf, t(ui, "pdf.h.table"), size)
    pdf.set_font("DejaVu", "", size - 0.5)
    with pdf.table(col_widths=WIDTHS, line_height=size * 0.48, text_align="LEFT", first_row_as_headings=True,
                   padding=0.6) as table:
        head = table.row()
        for col in COLS:
            head.cell(_safe(t(ui, col)))
        for lang in langs[:rows_max]:
            row = table.row()
            for value in table_row(lang, summary["facts"], ui):
                row.cell(_safe(str(value)))
    if len(langs) > rows_max:
        pdf.set_text_color(90, 90, 90)
        _para(pdf, t(ui, "pdf.more_langs", n=len(langs) - rows_max), size - 1)
        pdf.set_text_color(0, 0, 0)
    pdf.ln(1.5)

    # fixed boxes, top-aligned: a tall chart (many languages) shrinks instead of overlapping the text below
    y, used = pdf.get_y(), 0.0
    if charts.get("share"):
        used = _image(pdf, charts["share"], MARGIN, y, 112, chart_h)
    if charts.get("growth"):
        used = max(used, _image(pdf, charts["growth"], MARGIN + 115, y, 71, chart_h))
    if used:
        pdf.set_y(y + used + 1.5)
    if with_countries and charts.get("countries"):
        y = pdf.get_y()
        pdf.set_y(y + _image(pdf, charts["countries"], MARGIN, y, 150, 52) + 1.5)

    if reasons_n:
        grouped: dict[str, list[str]] = {}          # identical reasons share one line, as in the summary
        for lang in langs[:rows_max]:
            res = analysis["langs"].get(lang, {})
            if res.get("usable") and res["trust"]["reasons"]:
                reasons = "; ".join(t(ui, f"reason.{c}") for c in res["trust"]["reasons"][:reasons_n])
                grouped.setdefault(reasons, []).append(lang_name(lang, ui))
        if grouped:
            _heading(pdf, t(ui, "pdf.h.trust"), size)
            for reasons, names in grouped.items():
                _para(pdf, f"{', '.join(names)}: {reasons}", size - 0.5)
    _heading(pdf, t(ui, "pdf.h.limits"), size)
    caveats = summary["caveats"] if caveats_n is None else summary["caveats"][:caveats_n]
    for caveat in caveats:
        _para(pdf, f"• {caveat}", size - 0.5)
    if len(summary["caveats"]) > len(caveats):
        pdf.set_text_color(90, 90, 90)
        _para(pdf, t(ui, "pdf.more_caveats", n=len(summary["caveats"]) - len(caveats)), size - 1)
        pdf.set_text_color(0, 0, 0)
    _heading(pdf, t(ui, "pdf.h.sources"), size)
    articles, redirects = title_counts(analysis)
    sources = t(ui, "pdf.sources", articles=articles, redirects=redirects, date=data_date(analysis, ui))
    if proj.get("qid"):
        sources += f" Wikidata: {proj['qid']}."
    pdf.set_text_color(80, 80, 80)
    _para(pdf, " ".join((t(ui, "pdf.method"), t(ui, "pdf.params"), sources)), size - 1)
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
