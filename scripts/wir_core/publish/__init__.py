"""`wir publish`: notes.md -> strict number check -> report.pdf (one page) + report.md."""
from __future__ import annotations

import json
from pathlib import Path

from .. import project as pj
from ..envelope import make
from ..errors import EXIT_NODATA, EXIT_NUMCHECK, EXIT_USAGE, WirError
from ..i18n import t, ui_lang
from ..summary import summarize
from .markdown import render_md
from .notes import KEYS, parse_notes
from .numcheck import allowed_values, check, nearest_values
from .pdf import font_covers, render_pdf, rtl_chars

MAX_LISTED = 6
SNIPPET = 24


def _charts(analysis: dict, p: pj.Project, ui: str) -> dict[str, Path]:
    from ..charts import render_all

    if ui == ui_lang(p.ui):
        folder = p.dir / "charts"
        existing = {n: folder / f"{n}.png" for n in ("share", "index", "growth", "countries", "season")
                    if (folder / f"{n}.png").exists()}
        if existing:
            return existing
        return render_all(analysis, folder, ui)
    return render_all(analysis, p.dir / f"charts-{ui}", ui)   # always redrawn: the analysis may be newer


def _num(v: float, ui: str, percent: bool) -> str:
    text = f"{v:.0f}" if v.is_integer() else f"{v:g}"
    return (text.replace(".", ",") if ui == "uk" else text) + ("%" if percent else "")


def _bad_numbers(notes: dict[str, str], allowed: list[float], ui: str) -> list[str]:
    """One line per wrong number: section, the words around it, and the closest values of the data."""
    items, seen = [], set()
    for key, text in notes.items():
        for tok in check(text, allowed):
            if (key, tok.text) in seen:
                continue
            seen.add((key, tok.text))
            a, b = max(0, tok.pos - SNIPPET), tok.pos + len(tok.text) + SNIPPET
            snippet = ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")
            options = " / ".join(_num(v, ui, tok.percent) for v in nearest_values(tok, allowed))
            written = tok.text + ("%" if tok.percent else "")
            items.append(f"{t(ui, KEYS[key])}: «{snippet}» {written} → {options or '—'}")
    return items


def run_publish(args) -> dict:
    p = pj.load(args.project)
    path = p.dir / "analysis.json"
    if not path.exists():
        raise WirError("NOT_ANALYZED", "run the analysis before publishing",
                       fix="wir analyze, then run wir publish again", exit_code=EXIT_NODATA)
    if (p.dir / ".stale").exists():
        raise WirError("STALE_ANALYSIS", "the project changed after the last analysis",
                       fix="wir analyze, then run wir publish again", exit_code=EXIT_NODATA)
    ui = ui_lang(getattr(args, "ui", None) or p.ui)
    notes_path = Path(args.notes) if getattr(args, "notes", None) else p.dir / "notes.md"
    if not notes_path.exists():
        raise WirError("NOTES_MISSING", f"{pj.rel(notes_path)} does not exist",
                       fix=f"Copy {pj.rel(p.dir / 'notes.template.md')} to {pj.rel(notes_path)}, fill in the sections, "
                           "then run wir publish again.", exit_code=EXIT_USAGE)
    analysis = json.loads(path.read_text("utf-8"))
    notes = parse_notes(notes_path.read_text("utf-8"))
    summary = analysis["summary"] if ui == ui_lang(analysis["project"]["ui"]) else summarize(analysis, ui)

    allowed = allowed_values(analysis, summary)
    bad = _bad_numbers(notes, allowed, ui)
    if bad:
        more = f" (+{len(bad) - MAX_LISTED})" if len(bad) > MAX_LISTED else ""
        raise WirError("NUMBERS_NOT_IN_DATA", t(ui, "publish.bad_numbers", items="; ".join(bad[:MAX_LISTED]) + more),
                       fix=f"In {pj.rel(notes_path)} replace each listed number with the value after the arrow "
                           "that means the same thing (copy it as it is written in the facts), or delete the number; "
                           "then run wir publish again.", exit_code=EXIT_NUMCHECK)

    written = " ".join(notes.values())
    missing_glyphs = font_covers(written) | rtl_chars(written)
    if missing_glyphs:
        raise WirError("SCRIPT_UNSUPPORTED", f"the PDF cannot draw this text of the notes: "
                                             f"{''.join(sorted(missing_glyphs))[:20]}",
                       fix=f"Rewrite {pj.rel(notes_path)} in English (headings 'Conclusion' and 'Recommendation'), "
                           "then run: wir publish --ui en", exit_code=EXIT_USAGE)

    charts = _charts(analysis, p, ui)
    pdf_path, md_path = p.dir / "report.pdf", p.dir / "report.md"
    tmp = p.dir / "report.pdf.tmp"
    try:
        pages = render_pdf(analysis, summary, notes, charts, tmp, ui)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if pages != 1:
        tmp.unlink(missing_ok=True)
        raise WirError("PDF_OVERFLOW", "the report does not fit on one page",
                       fix=f"Shorten the sections of {pj.rel(notes_path)} (drop the optional third section first), "
                           "then run wir publish again.", exit_code=EXIT_USAGE)
    tmp.replace(pdf_path)
    render_md(analysis, summary, notes, charts, md_path, ui)
    return make("ready", project=pj.rel(p.dir),
                say=[t(ui, "publish.done", pdf=pj.rel(pdf_path), md=pj.rel(md_path))],
                files={"pdf": pj.rel(pdf_path), "md": pj.rel(md_path)})
