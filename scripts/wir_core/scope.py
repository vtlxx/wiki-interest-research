"""`wir scope`: topic -> project with per-language articles and a coverage status."""
from __future__ import annotations

import re
import shlex

from . import project as pj
from .envelope import make
from .errors import EXIT_NODATA, EXIT_USAGE, WirError
from .i18n import lang_name, t
from .net import open_client
from .providers import get_provider
from .providers.base import (BADGE_REDIRECT, DISAMBIGUATION, MISSING, PROXY, SECTION, VIA_REDIRECT,
                             Candidate, PageInfo)

QID = re.compile(r"Q\d+", re.I)
PROBLEM_STATUSES = {MISSING, DISAMBIGUATION}
SNIPPET = 50  # characters of a search snippet shown in an option label (stdout stays <= 3000 bytes)


def pick_candidate(cands: list[Candidate]) -> Candidate | None:
    exact = [c for c in cands if c.exact]
    if len(exact) == 1:
        return exact[0]
    pool = exact or cands
    if len(pool) == 1:
        return pool[0]
    top, second = pool[0], pool[1]
    if top.sitelinks >= 5 and top.sitelinks >= 3 * max(second.sitelinks, 1):
        return top
    return None


def parse_assignment(text: str) -> tuple[str, str]:
    if "=" not in text:
        raise WirError("BAD_ASSIGNMENT", f"'{text}' is not in LANG=\"Title\" form",
                       fix='Example: --set pl="Głodówka lecznicza"', exit_code=EXIT_USAGE)
    lang, title = (part.strip() for part in text.split("=", 1))
    if len(title) >= 2 and title[0] == title[-1] and title[0] in "\"'":
        title = title[1:-1].strip()
    if not lang or not title:
        raise WirError("BAD_ASSIGNMENT", f"'{text}' needs both a language code and a title",
                       fix='Example: --set pl="Głodówka lecznicza"', exit_code=EXIT_USAGE)
    return lang, title


def _article(info: PageInfo, role: str = "main", status: str | None = None, proxy: bool = False) -> pj.Article:
    return pj.Article(title=info.title, role=role, status=status or info.status, proxy=proxy,
                      fragment=info.fragment, length=info.length,
                      created=info.created.isoformat() if info.created else None,
                      extract=info.extract, qid=info.qid)


def _entry_from_link(provider, lang: str, title: str | None, badges: list[str]) -> pj.LangEntry:
    if not title:
        return pj.LangEntry(lang, MISSING, badges=badges)
    info = provider.inspect(lang, [title])[title]
    if info.status in PROBLEM_STATUSES:
        return pj.LangEntry(lang, info.status, [], badges)
    status = SECTION if (set(badges) & BADGE_REDIRECT and info.status == VIA_REDIRECT) else info.status
    return pj.LangEntry(lang, status, [_article(info, status=status)], badges)


def _resolve_langs(provider, codes: list[str], ui: str, notes: list[str]) -> list[str]:
    langs: list[str] = []
    for code in codes:
        if not code.strip():
            continue
        lang, note = provider.resolve_lang(code)
        if note:
            notes.append(t(ui, "note.lang_alias", typed=code.strip(), lang=lang, name=lang_name(lang, ui)))
        if lang not in langs:
            langs.append(lang)
    return langs


def _topic_ask(topic: str, cands: list[Candidate], ui: str, flags: list[str]) -> dict:
    """flags: the creation flags (resolved langs, ui, source, window) that every option must repeat."""
    extra = shlex.join(flags)
    options = [{"label": t(ui, "opt.topic", label=c.label, description=c.description or "…", n=c.sitelinks),
                "cmd": f"wir scope {c.qid} {extra}"} for c in cands[:3]]
    return make("input_required", ask={"question": t(ui, "ask.which_topic", topic=topic), "options": options})


def _title_ask(provider, p: pj.Project, lang: str, title: str, reason_key: str, flag: str, notes: list[str]) -> dict:
    """flag: the edit flag that failed (--set or --add-article); every option repeats it with another title."""
    options = [{"label": f"{hit} — {snippet[:SNIPPET]}", "cmd": f"wir scope {flag} {lang}={shlex.quote(hit)}"}
               for hit, snippet in provider.search_in_wiki(lang, title, 4) if hit != title][:3]
    options.append({"label": t(p.ui, "opt.own"), "cmd": f'wir scope {flag} {lang}="<title>"'})
    return make("input_required", project=pj.rel(p.dir), caveats=notes, ask={
        "question": t(p.ui, "ask.bad_title", title=title, lang=lang_name(lang, p.ui), reason=t(p.ui, reason_key)),
        "options": options})


def _search_text(p: pj.Project, provider) -> str:
    """The label is in the user's language; another wiki is searched with the English one when it exists."""
    if p.qid and p.ui != "en":
        return provider.entity(p.qid, "en").label or p.label
    return p.label


def _entry(p: pj.Project, lang: str) -> pj.LangEntry:
    return p.entries.get(lang) or pj.LangEntry(lang, MISSING)


def coverage_envelope(p: pj.Project, provider, notes: list[str]) -> dict:
    ui = p.ui
    say = [t(ui, "scope.summary", label=p.label, qid=p.qid or "—", source=p.source, n=len(p.langs),
             period=pj.period_text(p))]
    facts, caveats = {}, list(dict.fromkeys(list(p.notes) + list(notes)))  # creation notes live in both
    for lang in p.langs:
        entry = _entry(p, lang)
        main = entry.main()
        name = lang_name(lang, ui)
        say.append(t(ui, f"coverage.{entry.status}", lang=name, title=main.title if main else "—"))
        extras = len(entry.articles) - 1
        if extras > 0:
            say.append(t(ui, "coverage.extra", lang=name, n=extras))
        if entry.status == SECTION and main:
            caveats.append(t(ui, "note.section", lang=name, title=main.title))
        if entry.status == PROXY and main:
            caveats.append(t(ui, "note.proxy", lang=name, title=main.title))
        facts[lang] = {"status": entry.status, "article": main.title if main else "—"}  # details: project.json
        if extras > 0:
            facts[lang]["articles"] = len(entry.articles)
    problem = next((lang for lang in p.langs if _entry(p, lang).status in PROBLEM_STATUSES), None)
    files = {"project": pj.rel(p.dir / "project.json")}
    if problem:
        name = lang_name(problem, ui)
        options = [{"label": t(ui, "opt.drop", lang=name), "cmd": f"wir scope --drop-lang {problem}"}]
        if len(p.langs) == 1:
            options = []  # dropping the only language leaves nothing to analyse
        if p.source == "wiktionary":
            question = t(ui, "ask.wiktionary")
            options = [{"label": t(ui, "opt.word", lang=lang_name(lang, ui)), "cmd": f'wir scope --set {lang}="<word>"'}
                       for lang in p.langs if _entry(p, lang).status in PROBLEM_STATUSES] + options
        else:
            question = t(ui, "ask.missing", lang=name, source=p.source, label=p.label)
            for hit, snippet in provider.search_in_wiki(problem, _search_text(p, provider), 5):
                options.append({"label": f"{hit} — {snippet[:SNIPPET]}",
                                "cmd": f"wir scope --set {problem}={shlex.quote(hit)}"})
            options.append({"label": t(ui, "opt.own"), "cmd": f'wir scope --set {problem}="<title>"'})
        return make("input_required", project=pj.rel(p.dir), say=say, facts=facts, caveats=caveats,
                    ask={"question": question, "options": options}, files=files)
    return make("ready", project=pj.rel(p.dir), say=say, facts=facts, caveats=caveats, files=files,
                next_=[{"why": t(ui, "next.analyze"), "cmd": "wir analyze"}])


def _save_edited(p: pj.Project, *, stale: bool = True) -> None:
    p.key = pj.project_key(p.qid or p.topic, p.source, p.langs, p.period_months, p.date_from, p.date_to, p.ui)
    if stale and (p.dir / "analysis.json").exists():
        (p.dir / ".stale").write_text("1")
    pj.save(p)


def _create(args, provider, ui: str, notes: list[str]):
    if not args.langs:
        raise WirError("MISSING_LANGS", "no languages given",
                       fix=f"wir scope {shlex.quote(args.topic)} --langs pl,cs --ui {ui}", exit_code=EXIT_USAGE)
    langs = _resolve_langs(provider, args.langs.split(","), ui, notes)
    period = pj.parse_period(args.period) if args.period else 24
    date_from = pj.parse_month(args.date_from).strftime("%Y-%m") if args.date_from else None
    date_to = pj.parse_month(args.date_to).strftime("%Y-%m") if args.date_to else None
    topic = args.topic.strip()
    source = provider.source
    flags = ["--langs", ",".join(langs), "--ui", ui] + (["--source", source] if args.source else [])
    flags += ["--period", f"{period}m"] if args.period else []
    flags += (["--from", date_from] if date_from else []) + (["--to", date_to] if date_to else [])
    if source == "wiktionary":
        cand = Candidate("", topic, "", 0, True)
    elif QID.fullmatch(topic):
        cand = provider.entity(topic.upper(), ui)
    else:
        cands = provider.search(topic, ui)
        if not cands:
            raise WirError("TOPIC_NOT_FOUND", f"nothing found in Wikidata for '{topic}'",
                           fix="Try the English name of the topic, or a Wikidata QID.", exit_code=EXIT_NODATA)
        cand = pick_candidate(cands)
        if cand is None:
            return None, _topic_ask(topic, cands, ui, flags), False
        notes.append(t(ui, "note.interpreted", topic=topic, label=cand.label, description=cand.description or "…",
                       qid=cand.qid))
    qid = cand.qid or None
    key = pj.project_key(qid or topic, source, langs, period, date_from, date_to, ui)
    existing = pj.find_by_key(key)
    if existing:
        pj.save(existing)  # becomes latest
        return existing, None, True
    p = pj.new_project(topic=topic, qid=qid, label=cand.label, description=cand.description, source=source,
                       langs=langs, ui=ui, period_months=period, date_from=date_from, date_to=date_to)
    links = provider.links(qid, langs) if qid else {lang: (None, []) for lang in langs}
    for lang in langs:
        title, badges = links[lang]
        p.entries[lang] = _entry_from_link(provider, lang, title, badges)
    p.notes = list(notes)
    pj.save(p)
    return p, None, False


def _edit(args, p: pj.Project, provider, notes: list[str], window: bool) -> dict | None:
    """Apply edit flags; `window` = also apply --period/--from/--to. Returns an ask for the first unusable title."""
    ui = p.ui
    changed = False
    bad: tuple[str, str, str, str] | None = None
    for code in args.drop_lang:
        lang, _ = provider.resolve_lang(code)
        if lang in p.langs:
            p.langs.remove(lang)
            p.entries.pop(lang, None)
            changed = True
    new_langs = [lang for lang in _resolve_langs(provider, args.add_lang, ui, notes) if lang not in p.langs]
    if new_langs:
        links = provider.links(p.qid, new_langs) if p.qid else {lang: (None, []) for lang in new_langs}
        for lang in new_langs:
            p.langs.append(lang)
            p.entries[lang] = _entry_from_link(provider, lang, *links[lang])
        changed = True
    for text, role in [(x, "main") for x in args.set_title] + [(x, "extra") for x in args.add_article]:
        code, title = parse_assignment(text)
        lang = _resolve_langs(provider, [code], ui, notes)[0]
        entry = _entry(p, lang)
        if role == "extra" and not entry.main():
            raise WirError("NO_MAIN_ARTICLE", f"{lang} has no main article to add related articles to",
                           fix=f"wir scope --set {lang}={shlex.quote(title)}", exit_code=EXIT_USAGE)
        info = provider.inspect(lang, [title])[title]
        if info.status in PROBLEM_STATUSES:
            bad = bad or (lang, title, f"reason.{info.status}", "--set" if role == "main" else "--add-article")
            continue
        if lang not in p.langs:
            p.langs.append(lang)
        if role == "main":
            proxy = p.source != "wiktionary" and info.qid != p.qid
            status = PROXY if proxy else info.status
            entry = pj.LangEntry(lang, status, [_article(info, "main", status, proxy)] + entry.articles[1:],
                                 entry.badges)
        elif any(a.title == info.title for a in entry.articles):
            continue  # already in the basket
        else:
            entry.articles.append(_article(info, "extra"))
        p.entries[lang] = entry
        if info.extract:
            notes.append(t(ui, "note.set_checked", lang=lang_name(lang, ui), title=info.title, extract=info.extract))
        changed = True
    if window and (args.period or args.date_from or args.date_to):
        if args.period:  # a period replaces an explicit range unless the range is given again
            p.period_months, p.date_from, p.date_to = pj.parse_period(args.period), None, None
        p.date_from = pj.parse_month(args.date_from).strftime("%Y-%m") if args.date_from else p.date_from
        p.date_to = pj.parse_month(args.date_to).strftime("%Y-%m") if args.date_to else p.date_to
        changed = True
    if not p.langs:  # nothing left to analyse; refuse before anything is saved
        raise WirError("LAST_LANG", "the project needs at least one language; add another one before dropping this",
                       fix="wir scope --add-lang <code>", exit_code=EXIT_USAGE)
    if changed:
        _save_edited(p)
    return _title_ask(provider, p, *bad, notes) if bad else None


def run_scope(args) -> dict:
    notes: list[str] = []
    http = open_client()
    if args.topic:
        ui = args.ui or "en"
        provider = get_provider(args.source, http)
        p, ask, reused = _create(args, provider, ui, notes)
        if ask:
            return ask
        if reused:
            notes.append(t(ui, "scope.exists"))
    else:
        p = pj.load(args.project)
        if args.fork:
            p = pj.fork(p)
        provider = get_provider(p.source, http)
        if args.ui and args.ui != p.ui:
            p.ui = args.ui
            _save_edited(p, stale=False)
    # With a topic the window flags were used to create (or find) the project; without one they edit it.
    return _edit(args, p, provider, notes, window=not args.topic) or coverage_envelope(p, provider, notes)
