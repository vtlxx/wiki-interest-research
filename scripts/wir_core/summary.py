"""analysis.json -> say / facts / caveats in the UI language. The only producer of user-facing numbers."""
from __future__ import annotations

from . import fmt
from .i18n import lang_name, t, ui_lang
from .incidents import load as load_incidents


def _incident_notes(ui: str) -> dict[str, str]:
    key = "note_uk" if ui_lang(ui) == "uk" else "note_en"
    return {i.id: getattr(i, key) for i in load_incidents()}


def summarize(analysis: dict, ui: str) -> dict:
    say: list[str] = []
    facts: dict[str, dict] = {}
    caveats = [t(ui, "caveat.interest_not_demand"), t(ui, "caveat.lang_not_country")]
    if analysis["project"].get("period_months", 24) < 24 or analysis["project"].get("date_from"):
        caveats.append(t(ui, "caveat.short_period"))
    notes = _incident_notes(ui)
    seen_incidents: set[str] = set()
    geo_lines: list[str] = []
    any_countries = False
    for lang, res in analysis["langs"].items():
        name = lang_name(lang, ui)
        if not res.get("usable"):
            say.append(t(ui, "say.missing", lang=name))
            facts[lang] = {"status": res["status"], "supply": t(ui, f"supply.{res.get('supply', 'missing')}")}
            continue
        g = res.get("growth")
        trust = t(ui, f"trust.{res['trust']['level']}")
        share = fmt.share(res.get("share_per_m"), ui)
        if g:
            say.append(t(ui, "say.lang", lang=name, share=share, g=fmt.pct(g["g"]), ci=fmt.ci(g["lo"], g["hi"]),
                         verdict=t(ui, f"verdict.{g['verdict']}"), trust=trust))
        else:
            say.append(t(ui, "say.lang_nogrowth", lang=name, share=share, trust=trust))
        reasons = [t(ui, f"reason.{code}") for code in res["trust"]["reasons"]]
        if reasons:
            say.append(t(ui, "say.reasons", lang=name, reasons="; ".join(reasons)))
        pg, rg = res.get("project_growth"), res.get("raw_growth")
        if g and pg is not None and rg is not None and abs(pg) >= 0.05:
            say.append(t(ui, "say.context", lang=name, proj=fmt.pct(pg), raw=fmt.pct(rg), g=fmt.pct(g["g"])))
        season = res.get("seasonality")
        if season and season["level"] != "weak":
            months = ", ".join(t(ui, f"month.{m}") for m in season["peaks"])
            say.append(t(ui, "say.season", lang=name, level=t(ui, f"season.{season['level']}"), months=months))
        countries = res.get("countries") or []
        if countries:
            any_countries = True
            geo_lines.append(t(ui, "say.countries", lang=name,
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
                caveats.append(t(ui, "caveat.geo_threshold", lang=name, day=fmt.day(ep["peak"])))
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
        for inc_id in res.get("incidents", []):
            if inc_id not in seen_incidents and inc_id in notes:
                seen_incidents.add(inc_id)
                caveats.append(t(ui, "caveat.incident", lang=name, note=notes[inc_id]))
        if res.get("young"):
            caveats.append(t(ui, "caveat.young", lang=name, created=res.get("created"), start=res.get("effective_start")))
        for mv in res.get("moves", []):
            caveats.append(t(ui, "caveat.renamed", lang=name, day=mv["when"], source=mv["source"], target=mv["target"]))
        red = res.get("redirects") or {}
        if red.get("dominant"):
            caveats.append(t(ui, "caveat.dominant_redirect", lang=name, title=red["dominant"]))
        if red.get("unchecked"):
            caveats.append(t(ui, "caveat.unchecked_redirects", lang=name, n=len(red["unchecked"])))
    # The ranking goes before the geography lines: the envelope drops say lines from the end when it is too long.
    eligible = [r for r in analysis.get("ranking", []) if r["eligible"]]
    if len(analysis.get("ranking", [])) >= 2 and eligible:
        weights = ", ".join(f"{k}={v:g}" for k, v in analysis["weights"].items())
        say.append(t(ui, "say.ranking", list=", ".join(lang_name(r["lang"], ui) for r in eligible[:3]), weights=weights))
    say.extend(geo_lines)
    if any_countries:
        caveats.append(t(ui, "caveat.countries_rounded"))
    usable = [lang for lang, r in analysis["langs"].items() if r.get("usable")]
    if len(usable) >= 4:
        caveats.append(t(ui, "caveat.bh", n=len(usable)))
    if analysis.get("countries_skipped"):
        caveats.append(t(ui, "caveat.countries_skipped"))
    if analysis.get("geo_skipped"):
        caveats.append(t(ui, "caveat.geo_skipped"))
    return {"say": say, "facts": facts, "caveats": caveats}
