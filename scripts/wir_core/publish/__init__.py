"""`wir publish`: notes.md -> strict number check -> report.pdf (one page) + report.md."""
from __future__ import annotations

import json
from pathlib import Path

from .. import project as pj
from ..envelope import make
from ..errors import EXIT_NODATA, EXIT_NUMCHECK, EXIT_USAGE, WirError
from ..i18n import lang_name, t, ui_lang
from ..summary import summarize
from .markdown import render_md
from .notes import parse_notes
from .numcheck import strings, allowed_values, check, nearest
from .pdf import font_covers, render_pdf

MAX_LISTED = 8


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


def _num(v: float) -> str:
    return f"{v:.0f}" if v.is_integer() else f"{v:g}"


def run_publish(args) -> dict:
    p = pj.load(args.project)
    path = p.dir / "analysis.json"
    if not path.exists():
        raise WirError("NOT_ANALYZED", "run the analysis before publishing", fix="wir analyze", exit_code=EXIT_NODATA)
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
    bad = check("\n".join(notes.values()), allowed)
    if bad:
        items = "; ".join(f"{b.text} → {_num(nearest(b, allowed))}" for b in bad[:MAX_LISTED])
        more = f" (+{len(bad) - MAX_LISTED})" if len(bad) > MAX_LISTED else ""
        raise WirError("NUMBERS_NOT_IN_DATA", t(ui, "publish.bad_numbers", items=items + more),
                       fix=f"In {pj.rel(notes_path)} replace each listed number with the value after the arrow "
                           "(nearest number in the data) if it means the same thing, otherwise copy the number from "
                           "the facts or remove it; then run wir publish again.", exit_code=EXIT_NUMCHECK)

    proj = analysis["project"]
    shown = " ".join([*notes.values(), *strings(summary), proj.get("label") or proj.get("topic") or "",
                      *(lang_name(code, ui) for code in proj["langs"])])
    missing_glyphs = font_covers(shown)
    if missing_glyphs:
        raise WirError("SCRIPT_UNSUPPORTED", f"the PDF font cannot draw: {''.join(sorted(missing_glyphs))[:20]}",
                       fix=f"Rewrite {pj.rel(notes_path)} in English (headings 'Conclusion' and 'Recommendation'), "
                           "then run: wir publish --ui en", exit_code=EXIT_USAGE)

    charts = _charts(analysis, p, ui)
    pdf_path, md_path = p.dir / "report.pdf", p.dir / "report.md"
    tmp = p.dir / "report.pdf.tmp"
    pages = render_pdf(analysis, summary, notes, charts, tmp, ui)
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
