import pytest

from wir_core.publish.numcheck import allowed_values, check, extract, nearest, nearest_values


@pytest.mark.parametrize("text,value,decimals", [
    ("+34%", 34, 0), ("-6%", 6, 0), ("−47 %", 47, 0), ("5.12", 5.12, 2), ("5,12", 5.12, 2),
    ("1,234,567", 1234567, 0), ("1 234 567", 1234567, 0), ("1 234", 1234, 0), ("12,5", 12.5, 1),
    ("2.7×", 2.7, 1), ("1,2 млн", 1_200_000, 1), ("3 тис.", 3000, 0), ("4k", 4000, 0), ("1.5M", 1_500_000, 1),
    ("1.5 million", 1_500_000, 1), ("2 мільйони", 2_000_000, 0), ("7 тисяч", 7000, 0)])
def test_extract_single_values(text, value, decimals):
    tokens = extract(text)
    assert len(tokens) == 1 and tokens[0].value == pytest.approx(value) and tokens[0].decimals == decimals


def test_extract_ranges_dates_and_ignores_qids():
    assert [t.value for t in extract("90% ДІ +12…+58%")] == [90, 12, 58]
    assert [t.value for t in extract("сплеск 2026-03-14")] == [2026, 3, 14]
    assert [t.value for t in extract("12–58% of Q1666254")] == [12, 58]


def test_extract_lists_and_sentence_ends():
    assert [t.value for t in extract("CZ 93%, SK 2%, US 1%.")] == [93, 2, 1]
    assert [t.value for t in extract("in 2024, 2025 and 2026.")] == [2024, 2025, 2026]
    assert [t.value for t in extract("5 km, 3 kg")] == [5, 3]


def test_percent_context():
    assert [t.percent for t in extract("47% (90% CI -55…-38%), 5.12 per million, 45 відсотків, 90% ДІ")] == \
        [True, False, True, True, False, True, False]


def summary():
    return {"say": ["Czech: 5.12 views per million; last 12 months vs the 12 before: -47% (90% CI -55…-38%) — declining; trust: medium.",
                    "Czech: readers of this edition are mostly in CZ 93%, SK 2% (whole edition, last 12 months)."],
            "facts": {"cs": {"share_per_m": "5.12", "growth": "-47%", "countries": ["CZ 93%"]}},
            "caveats": ["A language edition is not a country.",
                        "2025-05-11…2025-07-23: About 2% of pageviews from Europe and Asia were lost."]}


def analysis():
    return {"project": {"langs": ["cs", "pl"], "period_months": 24, "label": "COVID-19", "topic": "covid 19"},
            "window": {"start": "2024-09-01", "end": "2026-08-31"},
            "langs": {"cs": {"titles": [{"title": "A"}, {"title": "B"}], "usable": True}, "pl": {}}}


@pytest.mark.parametrize("text", [
    "Інтерес у чеській Вікіпедії впав на 47% (90% ДІ −55…−38%).",
    "Частка — 5,1 на мільйон, 93% читачів у Чехії.",                # 5.1 is a rounding of 5.12
    "За 2 роки (2024–2026) у 2 мовах.",                             # period in years, window years, language count
    "Share fell by about 47 percent over 12 months.",
    "Share is about 5 per million.",                                 # 5 is a rounding of 5.12
    "A spike on 2025-04-14 and another in 2026-03.",                 # dates inside the window years
    "Interest fell by forty-eight percent.",                         # words are not checked (documented)
    "Between −55% and −38% (90% ДІ).",                               # both ends of the interval are percentages
    "Interest in COVID-19 fell 47 percent; 5.12 per 1 million views, на 1 млн переглядів, per 1M.",
    "Сплеск 01.09.2025.",
])
def test_allowed_texts_pass(text):
    assert check(text, allowed_values(analysis(), summary())) == []


@pytest.mark.parametrize("text,bad", [
    ("Інтерес впав у 2,7 раза.", [2.7]),
    ("Interest fell 50%.", [50]),
    ("Interest fell 48%.", [48]),                                   # 47% is in the data, 48% is not
    ("Interest fell 47.4%.", [47.4]),                              # more precision than the data has
    ("Share is 5.3 per million.", [5.3]),                          # not a rounding of 5.12
    ("About 1,200 readers.", [1200]),
    ("Interest fell 7%.", [7]),                                    # small numbers are not free
    ("A spike on 2019-04-14.", [2019]),                            # year outside the window
    ("Interest fell 11%.", [11]),                                  # 11 only occurs inside a caveat's date
    ("Interest fell 23 percent.", [23]),
    ("Interest fell 90%, 12%, 24% and 52%.", [90, 12, 24, 52]),     # counts are not percentages
    ("Only 2 languages, 2% of views.", []),                        # 2% is in the caveats
    ("About 1.5 million readers.", [1_500_000]),
])
def test_invented_numbers_rejected(text, bad):
    assert [t.value for t in check(text, allowed_values(analysis(), summary()))] == bad


def test_html_comments_ignored():
    assert check("<!-- 999 -->Fell 47%.", allowed_values(analysis(), summary())) == []


def test_nearest():
    token = extract("5.3")[0]
    assert nearest(token, [5.12, 47.0, 93.0]) == 5.12
    assert nearest(token, []) is None
    allowed = allowed_values(analysis(), summary())
    assert nearest_values(extract("fell 46%")[0], allowed) == [47, 38, 55]   # percentages only
