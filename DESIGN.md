# Design

Why the skill works the way it does: the pipeline, every key decision with the reason for it, the common
alternative and what it gets wrong, the evidence measured on real data, and the test that holds the decision in
place. How each number is computed (formulas, thresholds) is in
[references/methodology.md](references/methodology.md); this document never restates a threshold differently.

Contents: 1 what it optimises for · 2 the pipeline · 3 decisions · 4 trade-offs accepted · 5 what the checks
caught.

Unless stated otherwise, evidence was measured on 2026-09-27 over the window 2024-09-01 – 2026-08-31 (data
through 2026-09-26) with the tool at commit `717be22`. Wikimedia data changes, so a re-run gives slightly
different numbers.

## 1. What the skill optimises for

- **A decision, not a chart.** A founder asks "which topic, which language next?"; every run ends in a verdict per
  language, a trust level with its reasons, a ranking and a one-page report.
- **Honesty over precision.** An interval, a verdict of "no clear change" and a named reason for low trust are
  better answers than a precise-looking percentage.
- **Robust on a small model.** The tool does all data work and prints ready sentences; the model routes, asks
  the user and relays. Nothing depends on the model computing or remembering a rule.
- **Reproducible.** Locked dependencies, one common window, recorded API responses in tests, the fetch date and
  request parameters in every report.

## 2. The pipeline

```
wir scope    topic text or QID ─► Wikidata item ─► article per language ─► project.json
             (asks the user at every decision: ambiguous topic, missing article, stand-in, missing languages)
wir analyze  daily views of articles + redirects + old titles, edition totals ─► one common window
             ─► share per million ─► yearly change, trend, spikes, seasonality ─► incidents, trust
             ─► reader countries, supply, ranking ─► analysis.json, CSV, charts, ready sentences
wir verify   saved daily data ─► four alternative calculations ─► holds / weakens / reverses ─► trust, ranking
wir publish  notes.md ─► number check against the data ─► report.pdf (one page) + report.md
wir status   where a project stands (no network)
```

- **scope.** Input: a topic in any language or a Wikidata QID, language codes, the user's UI language, a period.
  The code resolves the Wikidata item and the article in each language and checks every title. Whatever the
  code cannot decide alone becomes an `ask`: a question with options, each carrying a ready command. The user
  picks; the agent runs the command. Output: `project.json`, reused by every follow-up.
- **analyze.** Input: the project. The code fetches everything first, cuts one window shared by all languages,
  then computes every number and verdict. Output: `analysis.json` (every number, verdict and reason),
  `series_daily.csv`, `series_monthly.csv`, charts, `notes.template.md` with a facts block, and a JSON answer
  of at most about 3 KB whose sentences the agent can relay as they are.
- **verify.** Input: the saved daily data (no network). Recomputes the verdict four other ways and records the
  outcome in trust and ranking.
- **publish.** Input: `notes.md` written by the agent from the facts block. Every number in it is checked against
  the data; only then are the PDF and the full Markdown report built.

## 3. Decisions

Each decision: **Decision** · **Why** · **Instead of** (the common alternative and what it gets wrong) ·
**Evidence** (where measured) · **Checked by** (tests that fail if the decision is undone).

### 3.1 Topic resolution

**Decision.** A topic becomes a Wikidata item, and the item's sitelinks give the article in each language. The
code, never the model, decides whether a match is certain; when it is not — several candidate items, no article
in a language, a title that is a disambiguation page — the tool asks the user with ready options. Common
mistyped language codes are corrected with a note (`cz` → `cs`, `ua` → `uk`). A language without an article is
searched in its own wiki with the topic's English label and the hits are offered as options. A title the model
or user proposes (`--set`, `--add-article`) is checked by code: it must exist, not be a disambiguation page, and
if it belongs to another Wikidata item it is marked a stand-in, which caps trust at medium; the tool returns the
article's first sentence so the user can confirm it is the right subject.

**Why.** Article titles differ between languages and are easy to guess wrongly; a wrong article silently
produces a confident answer about something else.

**Instead of** searching each wiki with a translated title, or letting the model pick the "obvious" candidate
— a translation can match an unrelated article, and the model's pick is invisible to the user.

**Evidence.** Example 1 (intermittent fasting, Polish and Czech): the Wikidata item has no Polish article. The
tool says so, offers "Continue without Polish" or Polish search hits, and the answer reports the missing
article as a content gap ([examples/fasting-pl-cs.pdf](examples/fasting-pl-cs.pdf)).

**Checked by** `tests/test_scope_cli.py::test_fasting_pl_missing_then_drop`,
`tests/test_scope_units.py::test_ambiguous_returns_none`,
`tests/test_scope_units.py::test_set_marks_proxy_and_returns_first_sentence`,
`tests/test_scope_units.py::test_missing_language_searches_that_wiki_with_the_english_label`,
`tests/test_provider_units.py::test_resolve_lang_valid_alias_closed_unknown`.

### 3.2 A topic is its articles, redirects and old titles

**Decision.** The topic's views in a language are the main article + basket articles the user added + counted
redirects. Old titles from the move log (renames) are always counted, so the history before a rename is merged
into the series. Other redirects are counted by the rule in
[methodology](references/methodology.md#topic--articles--redirects); the share of views they cover and the
number of redirects that could not be checked are printed, and low coverage or one dominant redirect lowers
trust.

**Why.** A rename moves all traffic to the new title; the old title becomes a redirect that holds the whole
history. Without it the article looks brand new and explosively growing.

**Instead of** measuring the current title only — a renamed article gets a fake growth figure.

**Evidence.** en "X (social network)", renamed from "Twitter" on 2026-02-25. Current title only: yearly change
+2429% (90% CI +1053…+5401%), "growing". Merged with the old title: −3.5% (−8.9…+3.2%), "stable". The old title
carried 6,689,922 of the 8,345,464 views in the window.

**Checked by** `tests/test_provider_units.py::test_moves_keep_only_article_renames`,
`tests/test_provider_meta.py::test_move_log_twitter`,
`tests/test_series.py::test_select_redirects_threshold_moves_unchecked_dominant`,
`tests/test_series.py::test_select_redirects_unknown_main_views_claims_no_coverage_or_dominance`.

### 3.3 Data hygiene

**Decision.** Views of people only (`agent=user`), all access methods, UTC days; days without a row are zeros;
only complete months and weeks enter a calculation; one window for all languages, ending on the last day every
fetched series covers; an article created shortly before the window starts later, and no yearly change is
computed over a span that begins before the article existed; offline copies of series are cut at the earliest
last day among them.

**Why.** Each rule removes a known way for the data to lie: bot traffic counted as interest, a partial current
month read as a collapse, languages compared over different months, days before an article existed read as
zero interest, a fresh edition total paired with a stale article series.

**Instead of** taking the API's monthly numbers as they come — the current month is partial for single articles
but not for edition totals, and missing days are simply absent.

**Checked by** `tests/test_series.py::test_fill_daily_zero_fills_and_clips`,
`tests/test_series.py::test_last_complete_day_uses_project_series_and_yesterday`,
`tests/test_stats.py::test_growth_young_article_is_none_when_the_compared_span_predates_it`,
`tests/test_provider_series_units.py::test_series_through_offline_reports_the_cached_copy_actually_used`.

### 3.4 Share per million, not raw views

**Decision.** The level and every change are measured as the topic's share of all views of its language edition
(views per million). Raw views appear only as audience size and as a context line ("the whole edition changed
X%; the topic's raw views Y%; its share Z%").

**Why.** Wikipedia traffic as a whole is falling, at different speeds per edition, and editions differ in size
by orders of magnitude. A share separates "people care less about this topic" from "people read less
Wikipedia".

**Instead of** comparing raw pageviews — every topic in a shrinking edition looks like it is losing interest,
and a large edition always "wins".

**Evidence.** Change of the whole edition in a year: Ukrainian −24.6%, Spanish −20.8%, Czech −12.5%, Polish
−8.8%, German −7.3%, English −7.0%. With the same bootstrap on raw views instead of share, 2 of 16 series get a
different verdict: German "Englische Sprache" raw −7.2% "declining" vs share −0.2% "stable"; English
"X (social network)" raw −10.8% "declining" vs share −3.5% "stable". Raw views exaggerate every decline, e.g.
Spanish "Idioma inglés" raw −29.0% vs share −9.5%.

**Checked by** `tests/test_stats.py::test_growth_uses_share_not_raw`.

### 3.5 Yearly change G with an honest interval

**Decision.** The main number compares the mean weekly share of the last 52 weeks with the 52 weeks before, so
each season is compared with itself. The 90% interval comes from a moving-block bootstrap over 4-week blocks.
The verdict is "growing" or "declining" only when the interval excludes zero and the change is large enough,
"stable" when the whole interval is small, otherwise "no clear change"
([rule](references/methodology.md#yearly-change-g--the-main-number)).

**Why.** Neighbouring weeks of pageviews are correlated (news cycles, school terms). Resampling single weeks as
if they were independent makes the interval too narrow and turns noise into a verdict.

**Instead of** a bootstrap over single weeks — the interval is too narrow.

**Evidence.** Over 15 real series the single-week bootstrap interval was 9–42% narrower than the block
bootstrap in every one (Ukrainian "Астрономія" 10.4 vs 16.7 percentage points; English "Semaglutide" 4.9 vs 8.4).
Polish "Astronomia", G −9.7%: single weeks give −18.3…−1.2%, "declining"; 4-week blocks give −21.6…+4.6%,
"no clear change".

**Checked by** `tests/test_stats.py::test_growth_doubling_is_growing_with_positive_ci`,
`tests/test_stats.py::test_growth_flat_is_stable`, `tests/test_stats.py::test_classify`,
`tests/test_stats.py::test_growth_deterministic_and_short_history`.

### 3.6 Trend as a supporting signal

**Decision.** Inside the window, the monthly share gets a Theil–Sen slope (% per year) and a Mann–Kendall test:
the seasonal variant when seasonality is at least moderate, otherwise the variant corrected for
autocorrelation. With four or more languages significance uses Benjamini–Hochberg q-values. A significant trend
against the yearly verdict lowers trust.

**Why.** The yearly change looks at two blocks of a year; the trend looks at the path between them. They
disagree when a change is recent or temporary, and that disagreement is worth a trust deduction. Correcting
for many languages keeps a comparison of five editions from finding a "significant" trend by chance.

**Checked by** `tests/test_stats.py::test_trend_detects_20pct_per_year`,
`tests/test_stats.py::test_trend_seasonal_with_growth_recovers_pct_per_year`,
`tests/test_stats.py::test_mk_hamed_rao_never_more_significant_than_plain_mk`,
`tests/test_stats.py::test_bh_adjust`.

### 3.7 Spikes are found, removed and explained as hypotheses

**Decision.** Spikes are detected on the daily share with a rolling median and median absolute deviation
(Hampel filter); spike days are replaced by the expected views to get a spike-free series and a spike-free G.
The spike share of all views drives trust. For the largest episodes the tool adds the countries the spike came
from and the article's edit count on the peak day — offered as hypotheses, not causes.

**Why.** One news day can outweigh a year of steady reading; a verdict that exists only because of a spike says
nothing about lasting interest.

**Instead of** reporting the change of total views — a single event reads as a trend, up in the year of the event
and down the year after.

**Evidence.** Liam Payne (died 2024-10-17): the spike episodes carry 42% of English and 52% of Polish views in
the window; the English peak alone added about 7.0 million views. G is −82% (English) and −76% (Polish), both
"declining", and trust is low because of the spikes. On the peak day 93% of the Polish article's views came from
Poland ([examples/spike-liam-payne.pdf](examples/spike-liam-payne.pdf)).

**Checked by** `tests/test_stats.py::test_spike_episode_detected_and_despiked`,
`tests/test_stats.py::test_low_volume_blip_ignored`.

### 3.8 Seasonality from the whole history

**Decision.** Seasonality strength and the peak months are computed from the article's whole monthly history
(at least 36 months), not from the analysis window, and are reported as weak, moderate or strong with the two
peak months.

**Why.** Two years hold only two examples of each month; the seasonal pattern needs more. A founder can act on
peaks (when to launch a course), and seasonality decides which trend test is valid.

**Evidence.** Ukrainian "Астрономія": strong seasonality, peaks in September and December
([examples/astronomy-uk.pdf](examples/astronomy-uk.pdf)).

**Checked by** `tests/test_stats.py::test_seasonality_strong_with_peaks`,
`tests/test_stats.py::test_seasonality_weak_for_noise_and_none_when_short`.

### 3.9 A calendar of known Wikimedia data problems

**Decision.** `assets/incidents.json` lists known problems in Wikimedia's pageview data — bot traffic counted as
people, data loss, history rewritten afterwards — with dates, affected projects and a severity that describes
how reliable the data is today (a problem that was later corrected is low). Every incident inside the window
becomes a dated caveat; medium and high ones are shaded on the charts; a high one inside the 104 weeks of the
yearly change lowers trust by one level.

**Why.** These problems are published by Wikimedia but invisible in the numbers the API returns; a month of bot
traffic looks exactly like a month of interest.

**Instead of** trusting every month the API returns — the jump is absorbed into the growth figure without a
trace.

**Evidence.** The November 2025 bot month (never corrected) in the monthly share, compared with the median of
the two months on each side: Italian "Astronomia" +221%, Polish "Astronomia" +141%; most other series moved
between −20% and +13%.

**Checked by** `tests/test_incidents.py::test_overlap_severity_filter_and_none`,
`tests/test_charts.py::test_incident_spans_clipped_to_window_and_low_severity_skipped`.

### 3.10 Trust from explicit rules with reasons

**Decision.** Each language starts at high trust. Critical reasons (tiny volume, under a year of data, a
spike-driven result, a verdict that reverses when spikes are removed or under `wir verify`) make it low; each minor rule
lowers it one level; a stand-in article caps it at medium
([table of reasons](references/methodology.md#trust-per-language)). Every deduction has a reason code, and the
tool turns the codes into a sentence ("why this trust level: …") in the user's language.

**Why.** A founder needs to know what to distrust, not only how much. Rules are also stable: the same data gives
the same level and the same reasons, and one rule never deducts twice.

**Instead of** a weighted confidence score such as 0.73 — the number cannot say why, and a model asked to explain
it invents the reasons.

**Evidence.** Example 1, Czech: low trust, "few views (under 300 a month) … a known Wikimedia data problem
overlaps the compared years".

**Checked by** `tests/test_trust.py::test_critical_reason_forces_low`,
`tests/test_trust.py::test_minor_reasons_step_down_and_floor`,
`tests/test_trust.py::test_redirect_pair_counts_as_one_deduction`, `tests/test_trust.py::test_proxy_caps_medium`.

### 3.11 A robustness check the user can run

**Decision.** `wir verify` recomputes each verdict four other ways from the saved data: spike-free G, a half-year
comparison, and trends over the last 24 and 36 months. The outcome is "holds", "weakens" or "reverses"
([rule](references/methodology.md#verify)); trust and the ranking are recomputed. It needs no network, so the
skill runs it every time.

**Why.** A verdict that survives other reasonable calculations is worth more than one that depends on a single
choice of window or method.

**Instead of** one calculation per question — a result that hinges on one spike or one window is presented with
the same confidence as a solid one.

**Evidence.** Ukrainian "Астрономія": holds (every variant declining). "English language" in five editions: holds
in Polish, Czech, Ukrainian and Spanish; weakens in German, where G is stable but the 36-month trend is −5% a
year (q 0.024), and trust drops to low. Liam Payne: weakens in English; reverses in Polish (the half-year change
has no clear direction, the 36-month trend is +80% a year).

**Checked by** `tests/test_verify_logic.py::test_verify_outcome`,
`tests/test_analyze_cli.py::test_offline_rerun_and_verify`.

### 3.12 A language is not a country

**Decision.** Reader countries come from Wikimedia's top-by-country data for the whole edition over the last 12
months (top 5 shares, rounded upper bounds); spike countries come from the daily differential-privacy dataset
of views by country and page. The answer speaks about countries only from these data and always carries the
caveat that an edition is not a country.

**Why.** Founders think in markets; editions do not map to markets. Spanish, English and Russian are read across
many countries, and one country reads several editions.

**Instead of** treating "Spanish Wikipedia" as Spain — most of the audience can be elsewhere.

**Evidence.** Share of an edition's views from outside its largest country (2025-09 – 2026-08): Spanish 69% (ES
31%, MX 16%, AR 12%), English 58% (US 42%), Ukrainian 28%, German 24% (AT 8%, CH 5%), Czech 18%, Polish 14%.

**Checked by** `tests/test_geo.py::test_top_countries_sums_months`,
`tests/test_geo.py::test_spike_breakdown_shares_within_project`.

### 3.13 Supply: is there anything to read in that language?

**Decision.** Each language gets a supply status: missing, short (a section, a stand-in, or much shorter than the
same article in the other languages), good or featured (Wikidata badges), or regular. A missing or short article
is a "gap" component of the ranking.

**Why.** For a founder, readers without content in their language are an opportunity; a missing article is a
finding, not zero interest.

**Evidence.** Intermittent fasting: no Polish article. Astronomy: the German article is short compared with the
other editions' articles, the Polish one carries a "good article" badge.

**Checked by** `tests/test_rank.py::test_supply_status`.

### 3.14 A ranking with visible weights

**Decision.** With two or more languages the tool ranks audiences by a weighted mean of percentiles: level
(share per million), momentum (spike-free G), size (views) and gap (supply). The default weights are printed in
the ranking sentence and can be changed (`--weights`); languages with low trust or no yearly change are never
recommended. When none is eligible the answer says so.

**Why.** "Which audience next" depends on what the founder values; printed weights make the ranking an argument
that can be challenged instead of an oracle.

**Evidence.** "English language": "Audiences to explore next: Spanish, Ukrainian, Polish (weights: level=0.35,
momentum=0.35, size=0.2, gap=0.1)". Liam Payne: "No audience can be recommended yet".

**Checked by** `tests/test_rank.py::test_rank_orders_and_eligibility`,
`tests/test_rank.py::test_weights_change_ranking`,
`tests/test_summary.py::test_no_eligible_language_still_gets_a_ranking_line_in_the_core`.

### 3.15 An interface built for small models

**Decision.** Every command prints one JSON object of at most about 3 KB with fixed keys: ready sentences
(`say`), compact values (`facts`), limitations (`caveats`), a question with ready commands (`ask`), suggested
commands (`next`), file paths, and errors with a `fix`. Exit codes separate "ask the user" from failures. When a
long answer must be shortened, the headline of every language, the ranking, the trust reasons and the core
caveats are kept first. The model never computes; SKILL.md tells it to take numbers only from `say`/`facts`.

**Why.** A small model is good at routing and relaying and bad at arithmetic, long JSON and remembering rules
from a long document. Each thing it could get wrong was moved into the tool's output.

**Instead of** asking the model to write analysis code, or giving it the full analysis file to summarise — every
unguarded freedom became a mistake in the dry-runs.

**Evidence.** Dry-runs of SKILL.md on Claude Haiku 4.5 (six runs over the three example questions): on the first
version the model invented "next steps" (mixing up languages and countries), padded the trust reasons with its
own, skipped the robustness check and quoted ranking scores from report.md. Each was fixed in the tool's output or
in SKILL.md; the later runs followed the workflow with every number in the answer found in the data (see
[DEVELOPMENT.md](DEVELOPMENT.md#how-ai-generated-work-was-verified)).

**Checked by** `tests/test_envelope.py::test_emit_shrinks_to_max_bytes`,
`tests/test_compose.py::test_core_survives_for_many_languages_and_verify_lines`,
`tests/test_scope_units.py::test_option_commands_parse`,
`tests/test_skill_md.py::test_every_command_example_parses`.

### 3.16 Reports that cannot contain invented numbers

**Decision.** The agent writes a short conclusion and recommendation into `notes.md` from the facts block. `wir
publish` extracts every number in it and accepts only numbers of the data or a correct rounding of them, with
percentages matched only to percentages; otherwise it refuses to build the PDF and lists each wrong number in
context with the closest values in the data. The PDF is one A4 page (it compacts itself in up to five steps and
asks for shorter notes if even the most compact form does not fit); `report.md` holds everything else — every article, redirect, caveat, the method and the
request parameters. Labels are in English or Ukrainian; the PDF font covers Latin, Cyrillic and Greek, notes in
other scripts are refused with a clear fix, and data text the font cannot draw is kept in report.md.

**Why.** The report is what gets shared; one invented or re-computed figure in it undoes the rest of the work.

**Instead of** trusting the model to copy numbers — models re-compute ("the topic fell 35% more than the
edition") and round freely, and the result looks exactly as credible.

**Evidence.** A note on the astronomy project saying "the topic lost 35% more than the edition" (−60 − (−25))
and "about 26% of the edition's readers live outside Ukraine" (100 − 74) was refused with exit code 6:
"35% → 33% / 25% / 45%", "26% → 25% / 33% / 45%".

**Checked by** `tests/test_numcheck.py::test_invented_numbers_rejected`,
`tests/test_publish_cli.py::test_publish_rejects_invented_number`,
`tests/test_pdf.py::test_pdf_is_one_page_with_cyrillic`, `tests/test_pdf.py::test_pdf_fits_with_fifteen_languages`,
`tests/test_pdf.py::test_data_text_the_font_cannot_draw_is_replaced`.

### 3.17 Network and cache

**Decision.** All HTTP goes through one client: one request at a time with at least 0.6 s between requests, a
User-Agent with a contact, up to 4 attempts that honour `Retry-After`, and a time budget per command — when it
runs out, `wir analyze` answers "run me again" and continues from the cache. Responses live in an SQLite cache
whose lifetime depends on the data's age: a week for series that touch the last 13 months (Wikimedia corrects
recent months), 90 days for older ones, a day for "no data", a year for published daily datasets. `--offline`
works from the cache alone. Tests replay recorded real responses.

**Why.** Wikimedia rate-limits clients and asks for identification; follow-up questions ("add Slovak", "over 5
years") should cost seconds, not minutes; and an agent should never be stuck in a command that hangs.

**Checked by** `tests/test_net.py::test_throttle_spacing`, `tests/test_net.py::test_retry_after_honoured`,
`tests/test_net.py::test_deadline_stops_before_network`, `tests/test_cache.py::test_ttl_expiry_and_allow_stale`,
`tests/test_net.py::test_record_then_replay`.

### 3.18 Extensibility

**Decision.** Everything that talks to a data source sits behind a `Provider` protocol with declared
capabilities (edition totals, redirects, moves, countries, spike countries, Wikidata); the pipeline skips the
steps a provider cannot do. Wikipedia, Wiktionary and Wikivoyage use the same provider; Wiktionary has no
Wikidata items, so the tool asks for the words to measure. User-facing text lives in locale files (`en`, `uk`);
a new UI language is one JSON file.

**Why.** The analysis should not change when the source does; new sources and languages should be additions,
not rewrites. How to add either: [DEVELOPMENT.md](DEVELOPMENT.md#adding-a-data-provider).

**Checked by** `tests/test_provider_units.py::test_wiktionary_has_no_wikidata_capability`,
`tests/test_scope_cli.py::test_wiktionary_asks_for_words`, `tests/test_i18n.py::test_locales_have_same_keys`.

## 4. Trade-offs accepted

- **Merged or split articles are not detected.** A merge moves traffic between titles and can look like growth or
  decline; only renames are followed.
- **Renames without a redirect are missed.** The move log is looked up by old title; an old title that was
  moved without leaving a redirect, or later reused, is not found.
- **Redirects are checked within a request budget.** Rarely used redirects may stay unchecked; their number is
  printed (en "X (social network)": 46 unchecked, coverage 95%).
- **Country data describes the whole edition,** not the topic, and is rounded; spike countries exist only from
  2023-02-06 and above about 90 views a day from one country.
- **Seasonality is biased upward with less than about 4 years** of history and is not computed below 3 years.
- **The seasonal trend test has little power on 24 months.** It compares each calendar month with itself, which
  gives only 12 pairs, so its p-value takes a few coarse values (0.009, 0.043, 0.149 were seen). Spanish
  "Astronomía" has a clearly declining G (−34%) but a trend p of 0.149. The verdict comes from G; the trend only
  supports it.
- **The incident rule is blunt.** The one uncorrected high-severity month (November 2025) lowers trust for every
  language whose yearly change spans it, even where that month looks normal in the data.
- **The number check checks digits, not meaning.** Numbers written in words, signs and what a sentence claims
  are not checked; a note can still describe a correct number wrongly.
- **Young articles get no yearly change** until 104 weeks of their existence are available.
- **Only Wikimedia projects.** No search, app-store or sales data; interest is not willingness to pay.

## 5. How the design was checked — what the checks caught

The code, tests and documents were written by AI coding agents under human direction. Nothing was accepted on
trust: statistics were built test-first on synthetic series with known answers, end-to-end tests replay recorded
real API responses, an independent reviewer agent checked every block against the specification and ran the real
commands, every chart and PDF was looked at, and the cheap target model was dry-run on the example questions.
Concrete errors these checks caught:

- **A non-existent article in early research notes.** The first analysis of the task named a Polish article on
  intermittent fasting; checking the Wikidata sitelinks showed Polish Wikipedia has none. That became the design
  rule that the tool reports a missing article and asks instead of guessing.
- **Trend slopes biased toward zero** by a small constant added to every month before taking logarithms; the
  seasonal trend also used a plain slope. Caught by review, fixed in `56d6928`.
- **The autocorrelation correction could make the trend test more significant** than the plain test under
  negative autocorrelation. Caught by review, fixed in `996310e`.
- **A false "declining"** when an offline run paired fresh edition totals with a stale article series whose
  missing tail counted as zeros. Caught by review, fixed in `36947b9`.
- **Days before an article existed counted as zero interest,** inflating its growth. Caught by review, fixed in
  `542e1cd`.
- **One trust rule deducted twice** when both of its triggers fired. Caught by review, fixed in `f68daeb`.
- **A daily country file not yet published was cached as "no rows"** for a year. Caught by review, fixed in
  `223b0f9`.
- **With five languages the answer lost headlines and the ranking** when it was shortened to fit 3 KB. Caught by
  a real run of example 3 and by review, fixed in `4f8b212` and `2d93da4`.
- **Dates in caveats leaked day numbers into the allowed set,** so an invented "30%" could pass the number
  check. Caught by review, fixed in `abf0608`.
- **Charts were unreadable at PDF size** and date labels overlapped on long windows. Caught by the reviewer opening
  every chart, fixed in `22146c4`.
- **The small model invented next steps and trust reasons and skipped the robustness check** (fixed in
  `6d71714`), **and quoted ranking scores read from report.md** (fixed in `7c668c6`). Caught by the Haiku 4.5
  dry-runs.
- **Seasonality strength on pure noise came out too high with 36–48 months** of data. Found while writing the noise
  test before the code; the test uses 10 years and the bias is documented as a limitation.
