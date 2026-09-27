import json
import shlex

import pytest

from wir_core.cli import build_parser
from wir_core.errors import WirError
from wir_core.providers.base import Candidate
from wir_core.scope import parse_assignment, pick_candidate


def c(qid, sitelinks, exact):
    return Candidate(qid, qid, "", sitelinks, exact)


def test_single_exact_wins():
    assert pick_candidate([c("Q1", 5, True), c("Q2", 90, False)]).qid == "Q1"


def test_dominant_candidate_wins():
    assert pick_candidate([c("Q1", 80, True), c("Q2", 10, True)]).qid == "Q1"


def test_ambiguous_returns_none():
    assert pick_candidate([c("Q1", 80, True), c("Q2", 60, True), c("Q3", 50, True)]) is None


def test_single_candidate():
    assert pick_candidate([c("Q9", 2, False)]).qid == "Q9"


@pytest.mark.parametrize("text,expected", [('pl=Głodówka lecznicza', ("pl", "Głodówka lecznicza")),
                                           ('uk="Чорна діра"', ("uk", "Чорна діра")),
                                           ("en='A=B'", ("en", "A=B"))])
def test_parse_assignment(text, expected):
    assert parse_assignment(text) == expected


def test_parse_assignment_bad():
    with pytest.raises(WirError):
        parse_assignment("Głodówka")


def test_option_commands_parse():
    for cmd in ['wir scope --drop-lang pl', 'wir scope --set pl="Głodówka lecznicza"',
                'wir scope Q1666254 --langs pl,cs --ui uk --period 24m']:
        build_parser().parse_args(shlex.split(cmd)[1:])


# ---- run_scope against a fake provider (no network) ------------------------------------------
from argparse import Namespace  # noqa: E402
from datetime import date  # noqa: E402

from wir_core import project as pj  # noqa: E402
from wir_core import scope  # noqa: E402
from wir_core.envelope import emit  # noqa: E402
from wir_core.i18n import t  # noqa: E402
from wir_core.providers.base import DISAMBIGUATION, FOUND, MISSING, PageInfo  # noqa: E402

LABELS = {"uk": "Інтервальне голодування", "en": "intermittent fasting"}


class FakeProvider:
    source = "wikipedia"

    def __init__(self, links=None, cands=None):
        self.links_ = links or {"cs": "Přerušovaný půst"}
        self.cands = cands or [Candidate("Q1666254", LABELS["uk"], "дієта", 31, True)]
        self.pages = {("cs", "Přerušovaný půst"): ("Q1666254", FOUND),
                      ("pl", "Głodówka lecznicza"): ("Q352490", FOUND),
                      ("pl", "Post"): (None, DISAMBIGUATION),
                      ("uk", "Інтервальне голодування"): ("Q1666254", FOUND),
                      ("uk", "Голодування"): ("Q44602", FOUND)}
        self.searched: list[tuple[str, str]] = []

    def resolve_lang(self, code):
        code = code.strip().lower()
        return ("cs", "alias") if code == "cz" else (code, None)

    def search(self, text, lang, limit=7):
        return self.cands

    def entity(self, qid, ui):
        return Candidate(qid, LABELS.get(ui, qid), "", 31, True)

    def links(self, qid, langs):
        return {lang: (self.links_.get(lang), []) for lang in langs}

    def inspect(self, lang, titles):
        out = {}
        for title in titles:
            qid, status = self.pages.get((lang, title), (None, MISSING))
            out[title] = PageInfo(lang, title, None if status == MISSING else title, status,
                                  length=1000, created=date(2020, 10, 28), extract=f"{title} is a topic.", qid=qid)
        return out

    def search_in_wiki(self, lang, text, limit=5):
        self.searched.append((lang, text))
        return [("Głodówka lecznicza", "leczenie głodem"), ("Post", "wstrzemięźliwość")][:limit]


def scope_args(topic=None, **kw):
    base = dict(topic=topic, langs=None, source=None, period=None, date_from=None, date_to=None, ui=None,
                project=None, add_lang=[], drop_lang=[], set_title=[], add_article=[], fork=False)
    return Namespace(**{**base, **kw})


@pytest.fixture
def fake(monkeypatch, wir_env):
    provider = FakeProvider()
    monkeypatch.setattr(scope, "open_client", lambda: None)
    monkeypatch.setattr(scope, "get_provider", lambda source, http: provider)
    return provider


def cmds(env):
    return [o["cmd"] for o in env["ask"]["options"]]


def test_missing_language_searches_that_wiki_with_the_english_label(fake):
    env = scope.run_scope(scope_args("інтервальне голодування", langs="pl,cs", ui="uk"))
    assert env["state"] == "input_required" and ("pl", "intermittent fasting") in fake.searched
    assert "wir scope --set pl='Głodówka lecznicza'" in cmds(env)
    for cmd in cmds(env):
        build_parser().parse_args(shlex.split(cmd)[1:])


def test_only_language_missing_does_not_offer_to_drop_it(fake):
    env = scope.run_scope(scope_args("Q1666254", langs="pl", ui="en"))
    assert env["state"] == "input_required" and not any("--drop-lang" in c for c in cmds(env))


def test_ambiguous_topic_options_keep_window_and_resolved_langs(fake):
    fake.cands = [Candidate("Q308", "Mercury", "planet", 80, True), Candidate("Q925", "mercury", "element", 70, True)]
    env = scope.run_scope(scope_args("Mercury", langs="cz, de", ui="en", date_from="2024-09", date_to="2026-08"))
    assert cmds(env)[0] == "wir scope Q308 --langs cs,de --ui en --from 2024-09 --to 2026-08"
    for cmd in cmds(env):
        args = build_parser().parse_args(shlex.split(cmd)[1:])
        assert (args.langs, args.date_from, args.date_to) == ("cs,de", "2024-09", "2026-08")


def test_topic_option_label_is_translated(fake):
    fake.cands = [Candidate("Q308", "Меркурій", "планета", 80, True), Candidate("Q925", "ртуть", "", 70, True)]
    env = scope.run_scope(scope_args("Меркурій", langs="uk", ui="uk"))
    assert env["ask"]["options"][0]["label"] == t("uk", "opt.topic", label="Меркурій", description="планета", n=80)


def test_bad_set_title_asks_but_keeps_the_other_edits(fake):
    scope.run_scope(scope_args("Q1666254", langs="pl,cs,uk", ui="en"))
    env = scope.run_scope(scope_args(drop_lang=["uk"], set_title=["pl=Post", "cs=Přerušovaný půst"]))
    assert env["state"] == "input_required" and "disambiguation" in env["ask"]["question"]
    assert "wir scope --set pl='Głodówka lecznicza'" in cmds(env) and "wir scope --set pl=Post" not in cmds(env)
    saved = pj.load(None)
    assert saved.langs == ["pl", "cs"] and saved.entries["pl"].status == MISSING
    assert any("Přerušovaný půst is a topic." in c for c in env["caveats"])


@pytest.mark.parametrize("text", ["pl=", "=Głodówka", 'pl=""'])
def test_parse_assignment_rejects_empty_parts(text):
    with pytest.raises(WirError) as err:
        parse_assignment(text)
    assert err.value.code == "BAD_ASSIGNMENT"


def test_set_marks_proxy_and_returns_first_sentence(fake):
    scope.run_scope(scope_args("Q1666254", langs="pl,cs", ui="en"))
    env = scope.run_scope(scope_args(set_title=['pl="Głodówka lecznicza"']))
    assert env["state"] == "ready" and env["facts"]["pl"]["status"] == "proxy"
    assert any("Głodówka lecznicza is a topic." in c for c in env["caveats"])
    env = scope.run_scope(scope_args(set_title=["cs=Přerušovaný půst"]))
    assert env["facts"]["cs"]["status"] == "found"


def test_add_article_dedupes_and_needs_a_main_article(fake):
    fake.links_ = {"uk": "Інтервальне голодування"}
    scope.run_scope(scope_args("Q1666254", langs="pl,uk", ui="en"))
    scope.run_scope(scope_args(add_article=["uk=Голодування"]))
    (pj.load(None).dir / "analysis.json").write_text("{}")
    env = scope.run_scope(scope_args(add_article=["uk=Голодування"]))
    assert env["facts"]["uk"]["articles"] == 2 and not (pj.load(None).dir / ".stale").exists()
    assert [a.role for a in pj.load(None).entries["uk"].articles] == ["main", "extra"]


def test_edit_marks_analysed_project_stale_and_fork_keeps_original(fake):
    scope.run_scope(scope_args("Q1666254", langs="pl,cs", ui="en"))
    original = pj.load(None)
    (original.dir / "analysis.json").write_text("{}")
    scope.run_scope(scope_args(drop_lang=["pl"], fork=True))
    forked = pj.load(None)
    assert forked.id != original.id and forked.langs == ["cs"] and (forked.dir / ".stale").exists()
    assert pj.load(original.id).langs == ["pl", "cs"] and not (original.dir / ".stale").exists()


def test_ui_change_is_saved(fake):
    scope.run_scope(scope_args("Q1666254", langs="cs", ui="en"))
    scope.run_scope(scope_args(ui="uk"))
    assert pj.load(None).ui == "uk"


def test_many_languages_fit_the_output_limit_without_truncation(fake, capsys, monkeypatch):
    from wir_core.envelope import TRUNCATED_NOTE
    titles = {"cs": "Přerušovaný půst", "uk": "Інтервальне голодування", "de": "Intermittierendes Fasten",
              "fr": "Jeûne intermittent", "es": "Ayuno intermitente", "it": "Digiuno intermittente",
              "sk": "Prerušovaný pôst"}  # live sitelinks of Q1666254; pl has none
    langs = ["pl", *titles]
    fake.links_ = titles
    fake.pages.update({(lang, title): ("Q1666254", FOUND) for lang, title in titles.items()})
    fake.cands = [Candidate("Q1666254", "Інтервальне голодування",
                            "a diet that cycles between a period of fasting and non-fasting", 31, True)]
    hits = [(f"Skróty i skrótowce używane w medycynie {i}", "długi fragment wyniku wyszukiwania " * 6)
            for i in range(5)]
    monkeypatch.setattr(fake, "search_in_wiki", lambda lang, text, limit=5: hits[:limit])
    env = scope.run_scope(scope_args("інтервальне голодування", langs=",".join(langs), ui="uk"))
    assert env["state"] == "input_required" and len(env["ask"]["options"]) == 7
    emit(env)
    out = capsys.readouterr().out
    assert len(out.strip().encode()) <= 3000 and TRUNCATED_NOTE not in out
    assert len(json.loads(out)["say"]) == 1 + len(langs)


def test_period_edit_replaces_an_explicit_range(fake):
    scope.run_scope(scope_args("Q1666254", langs="cs", ui="en", date_from="2024-09", date_to="2026-08"))
    env = scope.run_scope(scope_args(period="36m"))
    p = pj.load(None)
    assert (p.period_months, p.date_from, p.date_to) == (36, None, None)
    assert t("en", "period.months", n=36) in env["say"][0]


def test_missing_langs_fix_asks_the_user_and_gives_a_runnable_command(fake):
    with pytest.raises(WirError) as err:
        scope.run_scope(scope_args('the "best" diet'))
    ask, _, cmd = err.value.fix.partition("run: ")
    assert "Ask the user" in ask and "pl,cs" not in err.value.fix      # never default to languages nobody named
    args = build_parser().parse_args(shlex.split(cmd.replace("<codes>", "de"))[1:])
    assert args.topic == 'the "best" diet' and args.langs == "de"


def test_bad_basket_title_offers_add_article_and_keeps_the_main_article(fake):
    scope.run_scope(scope_args("Q1666254", langs="pl,cs", ui="en"))
    env = scope.run_scope(scope_args(add_article=["cs=Post"]))
    assert env["state"] == "input_required" and cmds(env)
    assert all(c.startswith("wir scope --add-article cs=") for c in cmds(env))
    assert 'wir scope --add-article cs="<title>"' in cmds(env)
    for cmd in cmds(env):
        build_parser().parse_args(shlex.split(cmd)[1:])
    assert [(a.title, a.role) for a in pj.load(None).entries["cs"].articles] == [("Přerušovaný půst", "main")]


def test_dropping_the_last_language_is_refused_and_the_project_is_kept(fake):
    scope.run_scope(scope_args("Q1666254", langs="cs", ui="en"))
    with pytest.raises(WirError) as err:
        scope.run_scope(scope_args(drop_lang=["cs"]))
    assert err.value.code == "LAST_LANG" and err.value.exit_code == 3
    assert err.value.fix == "wir scope --add-lang <code>"
    build_parser().parse_args(shlex.split(err.value.fix)[1:])
    assert pj.load(None).langs == ["cs"] and "cs" in pj.load(None).entries


@pytest.mark.parametrize("ui", ["en", "uk"])
def test_basket_article_without_a_main_article_asks_instead_of_promoting_it(fake, ui):
    scope.run_scope(scope_args("Q1666254", langs="pl,cs", ui=ui))
    env = scope.run_scope(scope_args(add_article=["pl=Głodówka lecznicza", "cs=Přerušovaný půst"]))
    assert env["state"] == "input_required" and "error" not in env
    assert env["ask"]["question"] == t(ui, "ask.no_main", lang=scope.lang_name("pl", ui), title="Głodówka lecznicza")
    labels = [o["label"] for o in env["ask"]["options"]]
    assert labels == [t(ui, "opt.use_as_main", title="Głodówka lecznicza"), t(ui, "opt.choose_main")]
    assert cmds(env) == ["wir scope --set pl='Głodówka lecznicza'", 'wir scope --set pl="<title>"']
    for cmd in cmds(env):
        build_parser().parse_args(shlex.split(cmd)[1:])
    saved = pj.load(None)
    assert saved.entries["pl"].status == MISSING and not saved.entries["pl"].articles


def test_add_and_drop_lang_accept_comma_and_space_separated_lists(fake):
    scope.run_scope(scope_args("Q1666254", langs="cs", ui="en"))
    args = build_parser().parse_args(shlex.split("scope --add-lang de,fr --add-lang 'it sk'"))
    scope.run_scope(scope_args(add_lang=args.add_lang))
    assert pj.load(None).langs == ["cs", "de", "fr", "it", "sk"]
    scope.run_scope(scope_args(drop_lang=["de, fr", "it"]))
    assert pj.load(None).langs == ["cs", "sk"] and set(pj.load(None).entries) == {"cs", "sk"}
