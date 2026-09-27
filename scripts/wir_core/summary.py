"""analysis.json -> say / facts / caveats in the UI language. The only producer of user-facing numbers.

Lines are ordered by importance (headline per language, ranking, then details), because the command output
keeps only what fits into ~3 KB; `core` says how many leading say/caveat lines must always be shown."""
from __future__ import annotations

from . import fmt
from .i18n import lang_name, t, ui_lang
from .incidents import load as load_incidents

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def summarize(analysis: dict, ui: str) -> dict:
    incidents = {i.id: i for i in load_incidents()}
    note_key = "note_uk" if ui_lang(ui) == "uk" else "note_en"
    headlines: list[str] = []
    reasons_by_text: dict[str, list[str]] = {}
    context: list[str] = []
    seasons: list[str] = []
    countries_lines: list[str] = []
    geo_lines: list[str] = []
    lang_caveats: list[str] = []
    incident_langs: dict[str, list[str]] = {}
    facts: dict[str, dict] = {}
    caveats = [t(ui, "caveat.interest_not_demand"), t(ui, "caveat.lang_not_country")]
    if analysis["project"].get("period_months", 24) < 24 or analysis["project"].get("date_from"):
        caveats.append(t(ui, "caveat.short_period"))
    for lang, res in analysis["langs"].items():
        name = lang_name(lang, ui)
        if not res.get("usable"):
            headlines.append(t(ui, "say.missing", lang=name))
            facts[lang] = {"status": res["status"], "supply": t(ui, f"supply.{res.get('supply', 'missing')}")}
            continue
        g = res.get("growth")
        trust = t(ui, f"trust.{res['trust']['level']}")
        share = fmt.share(res.get("share_per_m"), ui)
        if g:
            headlines.append(t(ui, "say.lang", lang=name, share=share, g=fmt.pct(g["g"]), ci=fmt.ci(g["lo"], g["hi"]),
                               verdict=t(ui, f"verdict.{g['verdict']}"), trust=trust))
        else:
            headlines.append(t(ui, "say.lang_nogrowth", lang=name, share=share, trust=trust))
        reasons = "; ".join(t(ui, f"reason.{code}") for code in res["trust"]["reasons"])
        if reasons:
            reasons_by_text.setdefault(reasons, []).append(name)
        pg, rg = res.get("project_growth"), res.get("raw_growth")
        if g and pg is not None and rg is not None and abs(pg) >= 0.05:
            context.append(t(ui, "say.context", lang=name, proj=fmt.pct(pg), raw=fmt.pct(rg), g=fmt.pct(g["g"])))
        season = res.get("seasonality")
        if season and season["level"] != "weak":
            months = ", ".join(t(ui, f"month.{m}") for m in season["peaks"])
            seasons.append(t(ui, "say.season", lang=name, level=t(ui, f"season.{season['level']}"), months=months))
        countries = res.get("countries") or []
        if countries:
            countries_lines.append(t(ui, "say.countries", lang=name,
                                     list=", ".join(f"{c} {fmt.pct(s, signed=False)}" for c, s in countries[:3])))
        for ep in res.get("spikes", {}).get("episodes", []):
            geo = ep.get("geo")
            if geo and geo.get("countries"):
                code, share_c = geo["countries"][0]
                geo_lines.append(t(ui, "say.spike_geo", lang=name, day=fmt.day(ep["peak"]),
                                   share=fmt.pct(share_c, signed=False), country=code))
                if geo.get("other_projects"):
                    geo_lines.append(t(ui, "say.spike_geo_other", lang=name, country=code,
                                       others=", ".join(p for p, _ in geo["other_projects"][:3])))
            elif geo is not None and geo.get("below_threshold"):
                lang_caveats.append(t(ui, "caveat.geo_threshold", lang=name, day=fmt.day(ep["peak"])))
            elif geo is not None and geo.get("unpublished"):
                lang_caveats.append(t(ui, "caveat.geo_unpublished", lang=name, day=fmt.day(ep["peak"])))
        facts[lang] = {
            "share_per_m": share,
            "growth": fmt.pct(g["g"]) if g else "—",
            "growth_ci": fmt.ci(g["lo"], g["hi"]) if g else "—",
            "verdict": t(ui, f"verdict.{g['verdict']}") if g else "—",
            "trust": trust,
            "season": t(ui, f"season.{season['level']}") if season else "—",
            "countries": [f"{c} {fmt.pct(s, signed=False)}" for c, s in countries[:3]],
            "supply": t(ui, f"supply.{res['supply']}"),
        }
        if res.get("verify"):
            facts[lang]["verify"] = t(ui, f"verify.{res['verify']['outcome']}")
        # window incidents plus high-severity ones that lie only in the compared year (they cost trust)
        for inc_id in dict.fromkeys(res.get("incidents", []) + res.get("incidents_high", [])):
            if inc_id in incidents:
                incident_langs.setdefault(inc_id, []).append(name)
        if res.get("young"):
            lang_caveats.append(t(ui, "caveat.young", lang=name, created=res.get("created"),
                                  start=res.get("effective_start")))
        for mv in res.get("moves", []):
            lang_caveats.append(t(ui, "caveat.renamed", lang=name, day=mv["when"], source=mv["source"],
                                  target=mv["target"]))
        red = res.get("redirects") or {}
        if red.get("dominant"):
            lang_caveats.append(t(ui, "caveat.dominant_redirect", lang=name, title=red["dominant"]))
        if red.get("unchecked"):
            lang_caveats.append(t(ui, "caveat.unchecked_redirects", lang=name, n=len(red["unchecked"])))

    ranking_line: list[str] = []
    eligible = [r for r in analysis.get("ranking", []) if r["eligible"]]
    if len(analysis.get("ranking", [])) >= 2 and eligible:
        weights = ", ".join(f"{k}={fmt.number(v, ui)}" for k, v in analysis["weights"].items())
        ranking_line.append(t(ui, "say.ranking", list=", ".join(lang_name(r["lang"], ui) for r in eligible[:3]),
                              weights=weights))
    reason_lines = [t(ui, "say.reasons", lang=", ".join(names), reasons=text) for text, names in reasons_by_text.items()]
    say = headlines + ranking_line + reason_lines + context + seasons + countries_lines + geo_lines

    incident_caveats = []
    for inc_id in sorted(incident_langs, key=lambda i: (SEVERITY_ORDER.get(incidents[i].severity, 3), incidents[i].start)):
        inc = incidents[inc_id]
        dates = {"start": fmt.day(inc.start), "end": fmt.day(inc.end), "note": getattr(inc, note_key)}
        if "*" in inc.projects:  # Wikimedia-wide: naming one language would mislead
            incident_caveats.append(t(ui, "caveat.incident_wide", **dates))
        else:
            incident_caveats.append(t(ui, "caveat.incident", lang=", ".join(incident_langs[inc_id]), **dates))
    general = []
    if countries_lines:
        general.append(t(ui, "caveat.countries_rounded"))
    usable = [lang for lang, r in analysis["langs"].items() if r.get("usable")]
    if len(usable) >= 4:
        general.append(t(ui, "caveat.bh", n=len(usable)))
    if analysis.get("countries_skipped"):
        general.append(t(ui, "caveat.countries_skipped"))
    if analysis.get("geo_skipped"):
        general.append(t(ui, "caveat.geo_skipped"))
    caveats += incident_caveats + lang_caveats + general
    return {"say": say, "facts": facts, "caveats": caveats,
            "core": {"say": len(headlines) + len(ranking_line), "headlines": len(headlines), "caveats": 2}}
