"""`wir analyze` and `wir verify`: fetch -> series -> stats -> trust -> countries -> analysis.json + envelope."""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from itertools import zip_longest

import pandas as pd

from . import incidents as inc
from . import project as pj
from . import series as sr
from . import stats as st
from .config import today_utc
from .envelope import fit, make
from .errors import EXIT_NETWORK, EXIT_NODATA, EXIT_USAGE, WirError
from .geo import spike_breakdown, top_countries
from .i18n import lang_name, t
from .net import BudgetExceeded, Deadline, open_client
from .providers import get_provider
from .providers.base import PROXY, SECTION, Move
from .providers.wikimedia import DP_START
from .rank import GAP_VALUE, parse_weights, rank_langs, supply_status
from .summary import summarize
from .trust import TrustInputs, assess

SCHEMA = 1
TIME_BUDGET_S = 90.0
MAX_GEO_EPISODES = 3      # spec 5.6: at most 6 daily DP files per run; one file per episode day
COMPACT_FACTS_FROM = 3    # languages; smaller facts keep the headline of every language inside ~3 KB
DAILY_CSV_YEARS = 5       # enough for verify's 36-month trend and the 104-week comparison
ENDPOINTS = [
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/all-access/user/{title}/daily/{start}/{end}",
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/aggregate/{project}/all-access/user/daily/{start}/{end}",
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/top-by-country/{project}/all-access/{year}/{month}",
    "https://analytics.wikimedia.org/published/datasets/country_project_page/{day}.tsv",
    "https://www.wikidata.org/w/api.php",
]


def _progress(text: str) -> None:
    print(f"[wir] {text}", file=sys.stderr)


# ---- fetching --------------------------------------------------------------------------------
@dataclass
class RawLang:
    lang: str
    project_raw: dict
    series: dict[str, dict] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    redirects: dict[str, dict] = field(default_factory=dict)
    moves: list[Move] = field(default_factory=list)
    created: date | None = None
    qid: str | None = None
    main_title: str = ""
    through: date | None = None   # last day covered by every fetched series of this language


def fetch_lang(provider, p: pj.Project, lang: str) -> RawLang:
    entry = p.entries[lang]
    main = entry.main()
    raw = RawLang(lang, provider.project_daily(lang), main_title=main.title,
                  created=date.fromisoformat(main.created) if main.created else None, qid=main.qid or p.qid)
    for art in entry.articles:
        raw.roles[art.title] = art.role
        if "redirects" not in provider.capabilities:
            continue
        reds = provider.redirects(lang, art.title)
        main60 = provider.views_60d(lang, [art.title]).get(art.title)
        # old titles keep residual traffic after a rename, so check the most-viewed redirects first (lookups are capped)
        by_views = sorted((r for r in reds if r.fragment is None), key=lambda r: -(r.views_60d or 0))
        moves = provider.moves(lang, [r.title for r in by_views]) if "moves" in provider.capabilities else []
        names = {art.title} | {r.title for r in reds}
        relevant = [m for m in moves if m.target in names]
        raw.moves.extend(relevant)
        sel = sr.select_redirects(reds, main60, {m.source for m in relevant})
        raw.redirects[art.title] = {"included": sel.included, "coverage": sel.coverage, "dominant": sel.dominant,
                                    "unchecked": sel.unchecked}
        old_titles = {m.source for m in relevant}
        for title in sel.included:
            raw.roles.setdefault(title, "old_title" if title in old_titles else "redirect")
    for title in raw.roles:
        raw.series[title] = provider.article_daily(lang, title)
    # Offline copies of article and project series can end on different days (HANDOFF #13): cut at the earliest.
    ends = [provider.series_through(lang)] + [provider.series_through(lang, title) for title in raw.roles]
    known = [d for d in ends if d is not None]
    raw.through = min(known) if known else None
    return raw


def common_window(p: pj.Project, raws: list[RawLang]) -> dict:
    """One window for all languages, so their numbers are comparable."""
    today = today_utc()
    last_day = min(min(sr.last_complete_day(r.project_raw, today), r.through or today) for r in raws)
    m0, _ = sr.month_bounds(last_day)
    start, end = sr.window_bounds(m0, p.period_months, p.date_from, p.date_to)
    if start > end:
        raise WirError("BAD_WINDOW", f"the requested period has no complete month of data (last complete day "
                                     f"{last_day.isoformat()})",
                       fix="wir scope --period 24m", exit_code=EXIT_USAGE)
    return {"start": start.isoformat(), "end": end.isoformat(), "last_day": last_day.isoformat()}


# ---- per-language analysis ------------------------------------------------------------------
def _growth_dict(g: st.Growth | None) -> dict | None:
    return asdict(g) if g else None


def _first_day(created: date | None, topic: pd.Series) -> date | None:
    """Article creation date, or the first day with views when the creation date is unknown."""
    if created:
        return created
    nonzero = topic[topic > 0]
    return nonzero.index[0].date() if len(nonzero) else None


def analyze_lang(p: pj.Project, raw: RawLang, window: dict) -> tuple[dict, dict[str, pd.Series]]:
    entry = p.entries[raw.lang]
    start, end = date.fromisoformat(window["start"]), date.fromisoformat(window["end"])
    eff_start, young = sr.young_start(raw.created, start)
    project_daily = sr.fill_daily(raw.project_raw, sr.DATA_START, end)
    per_title = {title: sr.fill_daily(s, sr.DATA_START, end) for title, s in raw.series.items()}
    topic = sr.combine(list(per_title.values()))
    first = _first_day(raw.created, topic)
    cmp_start = end - timedelta(days=7 * 104 - 1)
    # spikes over the whole span growth compares (and the window), never over days before the article existed
    spike_from = max(min(eff_start, cmp_start), sr.DATA_START, first or sr.DATA_START)
    episodes, despiked = st.detect_spikes(topic, project_daily, spike_from, end)
    growth = st.growth_yoy(topic, project_daily, end, first_day=first)
    growth_ds = st.growth_yoy(despiked, project_daily, end, first_day=first)
    hist_start = sr.first_full_month(max(first, sr.DATA_START)) if first else eff_start
    m_topic = sr.monthly(topic, hist_start, end)
    m_proj = sr.monthly(project_daily, hist_start, end)
    share_full = sr.share(m_topic, m_proj)
    season = st.seasonality(share_full)
    in_window = share_full.index >= pd.Timestamp(eff_start)
    share_win, m_topic_win, m_proj_win = share_full[in_window], m_topic[in_window], m_proj[in_window]
    trend = st.trend(share_win, seasonal=bool(season and season.strength >= 0.3))
    spike_sh = st.spike_share(episodes, topic, eff_start, end)
    flips = bool(growth and growth_ds and growth.verdict in ("growing", "declining")
                 and growth_ds.verdict in ("growing", "declining") and growth.verdict != growth_ds.verdict)
    conflict = bool(growth and trend and trend.p < 0.1 and (
        (growth.verdict == "growing" and trend.pct_per_year < 0) or (growth.verdict == "declining" and trend.pct_per_year > 0)))
    main_sel = raw.redirects.get(raw.main_title, {})
    renamed = sr.renamed_within(raw.moves, eff_start, end)
    high = [i.id for i in inc.overlapping(raw.lang, cmp_start, end, {"high"})]
    trust_inputs = TrustInputs(
        median_monthly_views=float(m_topic_win.median()) if len(m_topic_win) else 0.0,
        history_months=sr.history_months(topic, raw.created, end), spike_share=spike_sh,
        flips_without_spikes=flips, high_incidents=high, redirect_coverage=main_sel.get("coverage"),
        dominant_redirect=bool(main_sel.get("dominant")), young_article=young, renamed_in_window=bool(renamed),
        project_yoy=st.simple_yoy(project_daily, end), trend_conflict=conflict,
        is_proxy=entry.status == PROXY)
    trust = assess(trust_inputs)
    in_eff = topic.index >= pd.Timestamp(eff_start)
    window_total = float(topic[in_eff].sum()) or 1.0
    titles = [{"title": title, "role": raw.roles[title], "views_window": int(s[in_eff].sum()),
               "share": float(s[in_eff].sum()) / window_total}
              for title, s in per_title.items()]
    result = {
        "status": entry.status, "usable": True, "article": raw.main_title, "qid": raw.qid,
        "created": raw.created.isoformat() if raw.created else None,
        "effective_start": eff_start.isoformat(), "young": young,
        "history_months": trust_inputs.history_months, "titles": titles,
        "redirects": main_sel or {"included": [], "coverage": None, "dominant": None, "unchecked": []},
        "moves": [{"when": m.when.isoformat(), "source": m.source, "target": m.target} for m in renamed],
        "median_monthly_views": trust_inputs.median_monthly_views,
        "share_per_m": float(share_win.tail(12).mean()) if share_win.notna().any() else None,
        "raw_monthly_mean": float(m_topic_win.tail(12).mean()) if len(m_topic_win) else 0.0,
        "growth": _growth_dict(growth), "growth_despiked": _growth_dict(growth_ds),
        "raw_growth": st.simple_yoy(topic, end, first_day=first), "project_growth": trust_inputs.project_yoy,
        "trend": {**asdict(trend), "q": None} if trend else None,
        "seasonality": asdict(season) if season else None,
        "spikes": {"share": spike_sh, "episodes": [
            {"start": e.start.isoformat(), "end": e.end.isoformat(), "peak": e.peak.isoformat(),
             "extra_views": e.extra_views, "peak_views": e.peak_views, "edits": None, "geo": None}
            for e in episodes[:5]]},
        "incidents": [i.id for i in inc.overlapping(raw.lang, eff_start, end)], "incidents_high": high,
        "countries": [], "supply": "normal", "trust_inputs": asdict(trust_inputs),
        "trust": {"level": trust.level, "reasons": [r.code for r in trust.reasons]}, "verify": None,
        "monthly": [{"month": ts.strftime("%Y-%m"), "views": int(m_topic_win[ts]), "project_views": int(m_proj_win[ts]),
                     "share": None if math.isnan(share_win[ts]) else float(share_win[ts])} for ts in share_win.index],
    }
    return result, {"topic": topic, "project": project_daily, "despiked": despiked}


# ---- cross-language steps --------------------------------------------------------------------
def add_countries(provider, results: dict, window_end: date) -> bool:
    """Top reader countries of each edition over the last 12 full months. Returns True when skipped
    for some language (offline and not cached)."""
    if "geo" not in provider.capabilities:
        return False
    last_month = window_end.replace(day=1)
    skipped = False
    for lang, res in results.items():
        if not res.get("usable"):
            continue
        try:
            months = [provider.countries(lang, d.year, d.month)
                      for d in (sr.add_months(last_month, -k) for k in range(12))]
        except WirError as err:
            if err.code != "NOT_CACHED":
                raise
            skipped = True
            continue
        res["countries"] = [[code, share] for code, share in top_countries(months, n=5)]
    return skipped


def add_spike_geo(provider, results: dict) -> bool:
    """Country breakdown of the largest spikes. Returns True when the step was skipped (offline / not available)."""
    if "spike_geo" not in provider.capabilities:
        return True
    candidates = sorted(((res["spikes"]["episodes"][i]["extra_views"], lang, i)
                         for lang, res in results.items() if res.get("usable") and res.get("qid")
                         for i in range(len(res["spikes"]["episodes"]))), reverse=True)
    picked = [(lang, i) for _, lang, i in candidates
              if date.fromisoformat(results[lang]["spikes"]["episodes"][i]["peak"]) >= DP_START][:MAX_GEO_EPISODES]
    try:
        for lang, i in picked:
            res, ep = results[lang], results[lang]["spikes"]["episodes"][i]
            peak = date.fromisoformat(ep["peak"])
            rows = provider.spike_geo(peak, [res["qid"]])[res["qid"]]
            own = provider.aqs_project(lang)
            breakdown = spike_breakdown(rows, own)
            if breakdown:
                top = breakdown[0][0]
                others = sorted(((r.project, r.views) for r in rows if r.code == top and r.project != own),
                                key=lambda x: -x[1])[:4]
                ep["geo"] = {"countries": [[c, s] for c, s in breakdown[:5]], "other_projects": [list(o) for o in others]}
            else:
                ep["geo"] = {"countries": [], "other_projects": [], "below_threshold": True}
            ep["edits"] = provider.edits_on(lang, res["article"], peak)
    except WirError as err:
        if err.code != "NOT_CACHED":
            raise
        return True
    return False


def add_supply_rank_bh(p: pj.Project, results: dict) -> list[dict]:
    """Supply status per language, Benjamini-Hochberg q-values (>=4 languages), ranking (>=2 languages).
    Idempotent: verify calls it again on the stored results."""
    lengths = {lang: (p.entries[lang].main().length if p.entries.get(lang) and p.entries[lang].main() else None)
               for lang in results}
    for lang, res in results.items():
        entry = p.entries.get(lang)
        peers = [v for k, v in lengths.items() if k != lang and v]
        status = res["status"] if res.get("usable") else "missing"   # missing / disambiguation => no own article
        if status == PROXY:  # a stand-in article: the topic itself has no own article here
            status = SECTION
        res["supply"] = supply_status(status, lengths[lang], entry.badges if entry else [], peers)
    usable = [lang for lang, res in results.items() if res.get("usable")]
    if len(usable) >= 4:
        qs = st.bh_adjust([results[lang]["trend"]["p"] if results[lang]["trend"] else None for lang in usable])
        for lang, q in zip(usable, qs):
            if results[lang]["trend"]:
                results[lang]["trend"]["q"] = q
    if len(usable) < 2:
        return []
    rows = [{"lang": lang, "level": results[lang]["share_per_m"],
             "momentum": (results[lang]["growth_despiked"] or {}).get("g"),
             "size": results[lang]["raw_monthly_mean"], "gap": GAP_VALUE[results[lang]["supply"]],
             "trust": results[lang]["trust"]["level"]} for lang in usable]
    return [asdict(r) for r in rank_langs(rows, p.weights)]


# ---- outputs ----------------------------------------------------------------------------------
def _write_csvs(p: pj.Project, frames: dict[str, dict[str, pd.Series]], results: dict) -> None:
    with open(p.dir / "series_daily.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["lang", "date", "views", "project_views", "despiked"])
        for lang, fr in frames.items():
            end = fr["topic"].index[-1]
            since = max(fr["topic"].index[0], end - pd.DateOffset(years=DAILY_CSV_YEARS))
            for ts in fr["topic"].index[fr["topic"].index >= since]:
                w.writerow([lang, ts.date().isoformat(), int(fr["topic"][ts]), int(fr["project"][ts]),
                            round(float(fr["despiked"][ts]), 3)])
    with open(p.dir / "series_monthly.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["lang", "month", "views", "project_views", "share"])
        for lang, res in results.items():
            for row in res.get("monthly", []):
                w.writerow([lang, row["month"], row["views"], row["project_views"], row["share"]])


def _write_notes_template(p: pj.Project, summary: dict) -> None:
    ui = p.ui
    facts = "\n".join(f"- {line}" for line in summary["say"])
    text = (f"<!-- {t(ui, 'notes.instructions')} -->\n\n"
            f"## {t(ui, 'notes.h.conclusion')}\n\n\n"
            f"## {t(ui, 'notes.h.recommendation')}\n\n\n"
            f"## {t(ui, 'notes.h.next')}\n\n\n"
            f"<!-- facts:\n{facts}\n-->\n")
    (p.dir / "notes.template.md").write_text(text, "utf-8")


def _render_charts(analysis: dict, p: pj.Project) -> dict[str, str]:
    if importlib.util.find_spec("wir_core.charts") is None:
        return {}
    from .charts import render_all  # B09
    return {name: pj.rel(path) for name, path in render_all(analysis, p.dir / "charts", p.ui).items()}


def _finish(p: pj.Project, analysis: dict, extra_say: list[str] | None = None) -> dict:
    ui = p.ui
    analysis["summary"] = summarize(analysis, ui)
    (p.dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=1, default=str), "utf-8")
    _write_notes_template(p, analysis["summary"])
    charts = _render_charts(analysis, p)
    s = analysis["summary"]
    nxt = []
    if any(r.get("usable") and r["trust"]["level"] != "high" and not r.get("verify")
           for r in analysis["langs"].values()):
        nxt.append({"why": t(ui, "next.verify"), "cmd": "wir verify"})
    nxt.append({"why": t(ui, "next.publish", template="notes.template.md"), "cmd": "wir publish"})
    files = {"data": pj.rel(p.dir / "analysis.json"), "notes_template": pj.rel(p.dir / "notes.template.md"), **charts}
    facts = s["facts"]
    if len(facts) >= COMPACT_FACTS_FROM:  # countries and season are in the say lines and analysis.json
        facts = {lang: {k: v for k, v in f.items() if k not in ("countries", "season")} for lang, f in facts.items()}
    core_say, core_caveats = s["core"]["say"], s["core"]["caveats"]
    env = make("ready", project=pj.rel(p.dir), say=(extra_say or []) + s["say"][:core_say], facts=facts,
               caveats=s["caveats"][:core_caveats], next_=nxt, files=files)
    rest_say = [("say", line) for line in s["say"][core_say:]]
    rest_caveats = [("caveats", line) for line in s["caveats"][core_caveats:]]
    optional = [item for pair in zip_longest(rest_say, rest_caveats) for item in pair if item]
    return fit(env, optional, t(ui, "caveat.more"))


def _budget_used_up(p: pj.Project, err: BudgetExceeded, done: int, total: int) -> dict:
    """Out of time: continue on the next run from the cache, unless Wikimedia itself kept refusing (HANDOFF #5)."""
    if err.last_status == 429:
        raise WirError("RATE_LIMITED", "Wikimedia rate limit (HTTP 429) did not clear within the time budget",
                       fix="Wait one minute, then run wir analyze again (downloaded data is cached).",
                       exit_code=EXIT_NETWORK)
    if err.last_status is not None:
        raise WirError("UPSTREAM_ERROR", f"Wikimedia kept answering HTTP {err.last_status} within the time budget",
                       fix="Run wir analyze again in a few minutes (downloaded data is cached).",
                       exit_code=EXIT_NETWORK)
    return make("ready", project=pj.rel(p.dir), say=[t(p.ui, "analyze.partial", done=done, total=total)],
                next_=[{"why": t(p.ui, "next.continue"), "cmd": "wir analyze"}])


def run_analyze(args) -> dict:
    p = pj.load(args.project)
    if args.weights:
        p.weights = parse_weights(args.weights)
        pj.save(p)
    usable = [lang for lang in p.langs if p.entries.get(lang) and p.entries[lang].usable()]
    if not usable:
        raise WirError("NOTHING_TO_ANALYZE", "no language of this project has a usable article",
                       fix='Fix the scope first, e.g. wir scope --set <lang>="<title>" or wir scope --add-lang <code>',
                       exit_code=EXIT_NODATA)
    http = open_client(offline=args.offline, deadline=Deadline(TIME_BUDGET_S))
    try:
        provider = get_provider(p.source, http)
        raws: dict[str, RawLang] = {}
        try:
            for lang in usable:
                _progress(f"{lang}: downloading")
                raws[lang] = fetch_lang(provider, p, lang)
            window = common_window(p, list(raws.values()))
            results: dict[str, dict] = {}
            frames: dict[str, dict[str, pd.Series]] = {}
            for lang, raw in raws.items():
                results[lang], frames[lang] = analyze_lang(p, raw, window)
                results[lang]["article_url"] = provider.article_url(lang, raw.main_title)
            _progress("countries")
            countries_skipped = add_countries(provider, results, date.fromisoformat(window["end"]))
            geo_skipped = add_spike_geo(provider, results)
        except BudgetExceeded as err:
            return _budget_used_up(p, err, len(raws), len(usable))
        requests = http.requests_made
    finally:
        http.close()
    for lang in p.langs:
        if lang not in results:
            entry = p.entries.get(lang)
            results[lang] = {"status": entry.status if entry else "missing", "usable": False}
    ranking = add_supply_rank_bh(p, results)
    analysis = {
        "schema": SCHEMA, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": {k: getattr(p, k) for k in ("id", "topic", "qid", "label", "source", "langs", "ui",
                                               "period_months", "date_from", "date_to")},
        "window": window, "weights": p.weights, "langs": {lang: results[lang] for lang in p.langs},
        "ranking": ranking, "geo_skipped": geo_skipped, "countries_skipped": countries_skipped,
        "provenance": {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": p.source,
                       "offline": bool(args.offline), "requests": requests,
                       "params": {"agent": "user", "access": "all-access"}, "endpoints": ENDPOINTS},
    }
    _write_csvs(p, frames, results)
    env = _finish(p, analysis)
    (p.dir / ".stale").unlink(missing_ok=True)
    return env


# ---- verify -----------------------------------------------------------------------------------
def direction_of_growth(g: st.Growth | None) -> int:
    if g is None:
        return 0
    return {"growing": 1, "declining": -1}.get(g.verdict, 0)


def direction_of_trend(tr: st.Trend | None) -> int:
    if tr is None or tr.p >= 0.1:
        return 0
    return 1 if tr.pct_per_year > 0 else -1


def verify_outcome(main_dir: int, dirs: list[int]) -> str:
    if main_dir == 0:
        return "holds" if all(d == 0 for d in dirs) else "weakens"
    if any(d == -main_dir for d in dirs):
        return "flips"
    if any(d == 0 for d in dirs):
        return "weakens"
    return "holds"


def _read_daily(p: pj.Project) -> dict[str, pd.DataFrame]:
    path = p.dir / "series_daily.csv"
    if not path.exists() or not (p.dir / "analysis.json").exists():
        raise WirError("NOT_ANALYZED", "this project has not been analysed yet", fix="wir analyze",
                       exit_code=EXIT_NODATA)
    if (p.dir / ".stale").exists():
        raise WirError("STALE_ANALYSIS", "the project was changed after the last analysis", fix="wir analyze",
                       exit_code=EXIT_NODATA)
    df = pd.read_csv(path, parse_dates=["date"])
    return {lang: g.set_index("date").sort_index() for lang, g in df.groupby("lang")}


def run_verify(args) -> dict:
    p = pj.load(args.project)
    daily = _read_daily(p)
    analysis = json.loads((p.dir / "analysis.json").read_text("utf-8"))
    end = date.fromisoformat(analysis["window"]["end"])
    extra_say = []
    for lang, res in analysis["langs"].items():
        if not res.get("usable") or lang not in daily:
            continue
        df = daily[lang]
        topic, proj, despiked = df["views"].astype(float), df["project_views"].astype(float), df["despiked"].astype(float)
        first = _first_day(date.fromisoformat(res["created"]) if res.get("created") else None, topic)
        seasonal = bool(res.get("seasonality") and res["seasonality"]["strength"] >= 0.3)
        g_ds = st.growth_yoy(despiked, proj, end, first_day=first)
        g_half = st.growth_yoy(topic, proj, end, weeks=26, lag_weeks=52, first_day=first)
        m_start = sr.first_full_month(max(topic.index[0].date(), first or topic.index[0].date()))
        share_m = sr.share(sr.monthly(topic, m_start, end), sr.monthly(proj, m_start, end))
        tr24 = st.trend(share_m.tail(24), seasonal=seasonal)
        tr36 = st.trend(share_m.tail(36), seasonal=seasonal) if len(share_m) >= 36 else None
        main_dir = {"growing": 1, "declining": -1}.get((res.get("growth") or {}).get("verdict"), 0)
        dirs = [direction_of_growth(g_ds), direction_of_growth(g_half), direction_of_trend(tr24)]
        if tr36:
            dirs.append(direction_of_trend(tr36))
        outcome = verify_outcome(main_dir, dirs)
        res["verify"] = {"outcome": outcome, "variants": {
            "despiked": _growth_dict(g_ds), "half_year": _growth_dict(g_half),
            "trend_24m": asdict(tr24) if tr24 else None, "trend_36m": asdict(tr36) if tr36 else None}}
        trust = assess(TrustInputs(**{**res["trust_inputs"], "verify_outcome": outcome}))
        res["trust"] = {"level": trust.level, "reasons": [r.code for r in trust.reasons]}
        extra_say.append(t(p.ui, "verify.lang", lang=lang_name(lang, p.ui), outcome=t(p.ui, f"verify.{outcome}"),
                           trust=t(p.ui, f"trust.{trust.level}")))
    analysis["ranking"] = add_supply_rank_bh(p, analysis["langs"])
    return _finish(p, analysis, extra_say)
