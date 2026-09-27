"""Full Markdown report (everything the one-page PDF had to leave out)."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from .. import fmt
from ..i18n import lang_name, t
from .pdf import COLS, data_date, table_row, title_counts


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _link(text: str, url: str | None) -> str:
    label = text.replace("[", "\\[").replace("]", "\\]")
    return f"[{label}](<{url}>)" if url else label


def _title_url(article_url: str | None, title: str, role: str) -> str | None:
    if not article_url or "/wiki/" not in article_url:
        return None
    base = article_url.rsplit("/wiki/", 1)[0]
    url = f"{base}/wiki/{quote(title.replace(' ', '_'), safe='')}"
    return url + "?redirect=no" if role in ("redirect", "old_title") else url


def render_md(analysis: dict, summary: dict, notes: dict, charts: dict, out: Path, ui: str) -> None:
    proj, window = analysis["project"], analysis["window"]
    langs = list(proj["langs"])
    parts = [f"# {proj.get('label') or proj.get('topic')}",
             t(ui, "pdf.subtitle", langs=", ".join(lang_name(code, ui) for code in langs), start=window["start"],
               end=window["end"], source=proj.get("source") or "wikipedia", date=data_date(analysis, ui)),
             f"## {t(ui, 'notes.h.conclusion')}", notes["conclusion"],
             f"## {t(ui, 'notes.h.recommendation')}", notes["recommendation"]]
    if notes.get("next"):
        parts += [f"## {t(ui, 'notes.h.next')}", notes["next"]]
    parts += [f"## {t(ui, 'md.h.facts')}", "\n".join(f"- {line}" for line in summary["say"])]
    parts += [f"## {t(ui, 'pdf.h.table')}",
              _table([t(ui, c) for c in COLS], [table_row(code, summary["facts"], ui) for code in langs])]

    if analysis.get("ranking"):
        weights = ", ".join(f"{k}={fmt.number(v, ui)}" for k, v in analysis.get("weights", {}).items())
        parts += [f"## {t(ui, 'md.h.ranking')}", _table(
            [t(ui, "pdf.col.lang"), t(ui, "md.col.score"), t(ui, "md.col.eligible")],
            [[lang_name(r["lang"], ui), fmt.number(round(r["score"], 2), ui), t(ui, "md.yes" if r["eligible"] else "md.no")]
             for r in analysis["ranking"]]),
            t(ui, "md.weights", weights=weights)]
    verified = [(code, r["verify"]) for code, r in analysis["langs"].items() if r.get("verify")]
    if verified:
        parts += [f"## {t(ui, 'md.h.verify')}",
                  "\n".join(f"- {lang_name(code, ui)}: {t(ui, 'verify.' + v['outcome'])}" for code, v in verified)]

    trust_lines = []
    for code in langs:
        r = analysis["langs"].get(code, {})
        if r.get("usable"):
            reasons = "; ".join(t(ui, f"reason.{c}") for c in r["trust"]["reasons"]) or "—"
            trust_lines.append(f"- {lang_name(code, ui)} ({t(ui, 'trust.' + r['trust']['level'])}): {reasons}")
    if trust_lines:
        parts += [f"## {t(ui, 'pdf.h.trust')}", "\n".join(trust_lines)]

    if charts:
        parts.append(f"## {t(ui, 'md.h.charts')}")
        parts += [f"![{name}]({Path(os.path.relpath(path, out.parent)).as_posix()})" for name, path in charts.items()]

    parts.append(f"## {t(ui, 'md.h.articles')}")
    for code in langs:
        r = analysis["langs"].get(code, {})
        if not r.get("usable"):
            continue
        url = r.get("article_url")
        parts += [f"### {lang_name(code, ui)} — {_link(r['article'], url)}", _table(
            [t(ui, "md.col.title"), t(ui, "md.col.role"), t(ui, "md.col.views"), t(ui, "md.col.share")],
            [[_link(x["title"], _title_url(url, x["title"], x["role"])), t(ui, f"md.role.{x['role']}"),
              fmt.integer(x["views_window"], ui), fmt.pct(x["share"], signed=False)] for x in r.get("titles", [])])]

    prov = analysis.get("provenance", {})
    params = prov.get("params") or {"agent": "user", "access": "all-access"}
    articles, redirects = title_counts(analysis)
    sources = [f"- `{e}`" for e in prov.get("endpoints", [])]
    if proj.get("qid"):
        sources.append(f"- Wikidata: {_link(proj['qid'], 'https://www.wikidata.org/wiki/' + proj['qid'])}")
    parts += [f"## {t(ui, 'pdf.h.limits')}", "\n".join(f"- {c}" for c in summary["caveats"]),
              f"## {t(ui, 'md.h.method')}", t(ui, "pdf.method"),
              f"## {t(ui, 'pdf.h.sources')}", "\n".join(sources),
              t(ui, "md.params", agent=params.get("agent"), access=params.get("access")),
              t(ui, "pdf.sources", articles=articles, redirects=redirects, date=data_date(analysis, ui)),
              t(ui, "md.license")]
    out.write_text("\n\n".join(p for p in parts if p) + "\n", "utf-8")
