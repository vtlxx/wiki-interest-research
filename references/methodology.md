# How the numbers are computed

Contents: data · topic and redirects · share per million · yearly change · trend · spikes · seasonality ·
data incidents · trust · verify · supply · ranking · countries.

## Data
- Wikimedia Pageviews API, daily, `agent=user` (people, not known bots), `access=all-access` (desktop +
  mobile web + apps), UTC days. Days without a row count as 0. Data exists from 2015-07-01.
- Every language uses one common window: the last N complete calendar months (default 24) ending at the
  last day that every fetched series of every language covers. `--from/--to` set the months directly.
- Edition totals ("all views of the language edition") come from the aggregate endpoint with the same filters.

## Topic = articles + redirects
- The topic's views in a language = main article + basket articles (`--add-article`) + counted redirects.
- A redirect is counted when its views over the last 60 days are ≥ 1% of the main article's, or when it is an
  old title of the article (a rename) — renamed titles always count. Redirects to a section of the article
  are counted like the others.
- Coverage = counted views ÷ all checked views (main + redirects). A dominant redirect carries > 30% of them.
  Redirects whose 60-day views could not be checked within the request budget are listed as a count.
- Young article: if it was created less than 90 days before the window start (or later), the analysis
  starts at the first full month that begins 90 days or more after creation.

## Share per million
share = topic views ÷ views of the whole language edition × 1,000,000, per month. The headline value is the
mean of the last 12 months of the window. It is the only fair level comparison across languages: editions
differ in size by orders of magnitude, raw counts do not compare.

## Yearly change (G) — the main number
- Take the last 104 weeks ending on the window's last day; weekly share = topic views ÷ edition views.
- G = mean share of the last 52 weeks ÷ mean share of the 52 weeks before − 1.
- 90% interval: moving-block bootstrap (4-week blocks, 2,000 resamples, fixed seed), 5th and 95th percentiles.
- Verdict: **growing** if the interval is above 0 and G ≥ +5%; **declining** if the interval is below 0 and
  G ≤ −5%; **stable** if the whole interval lies within ±10%; otherwise **no clear change**.
- Context lines: change of raw topic views and of the whole edition over the same two years.
- Not computed when the 104 weeks start before the article existed.

## Trend (supporting)
- Monthly share inside the window, log scale (zero months replaced by half the smallest positive month),
  at least 12 months.
- With seasonality strength ≥ 0.3 and ≥ 24 months: seasonal Mann–Kendall test + seasonal Sen slope.
  Otherwise: Theil–Sen slope (90% interval) + Mann–Kendall with the Hamed–Rao autocorrelation correction.
- Reported as % per year. Significant when p < 0.1; with ≥ 4 languages the Benjamini–Hochberg q-value
  (q < 0.1) is used instead.

## Spikes
- Daily share; rolling median and MAD over 29 days (centred). A day is a spike when share > median +
  5 × 1.4826 × MAD, share ≥ 3 × median and it has ≥ 100 extra views.
- Spike days less than 3 days apart form one episode. Spike days are replaced by the expected views
  (median share × edition views) → the spike-free series used by the spike-free G.
- Spike share = extra views of all episodes ÷ all topic views in the window.
- The largest episodes (at most 3 per run, only from 2023-02-06) get a country breakdown and the article's
  edit count on the peak day.

## Seasonality
- Needs ≥ 36 months of share history. Log share; a centred 2×12 moving average removes the trend; the
  monthly profile is the median of each calendar month, centred to mean 0.
- Strength = max(0, 1 − var(residual) ÷ var(seasonal + residual)): weak < 0.3, moderate < 0.6, strong ≥ 0.6.
- Peaks = the two months with the highest profile.

## Data incidents
A calendar of known Wikimedia data problems (bot traffic counted as people, data loss, backfills). Severity
describes how reliable the data is today, not how big the problem was. Every incident inside the window is
a caveat; a **high** one inside the 104 weeks of G lowers trust; medium and high ones are shaded on charts.

## Trust (per language)
Start at **high**. Any critical reason → **low**. Each minor rule lowers one level (a rule with two codes
counts once). A stand-in article caps trust at **medium**. At most 5 reasons are shown.

| Code | Kind | Meaning |
|---|---|---|
| `tiny_volume` | critical | median monthly views < 30 |
| `short_history` | critical | < 12 months of data |
| `spike_driven` | critical | spike share > 50% |
| `flips_without_spikes` | critical | G and spike-free G point in opposite directions |
| `verify_flips` | critical | `wir verify` reversed the verdict |
| `low_volume` | minor | median monthly views < 300 |
| `history_lt_24` | minor | 12–23 months of data |
| `spiky` | minor | spike share 20–50% |
| `verify_weakens` | minor | `wir verify`: spike-free G has no clear direction or a variant points the other way; or G has none and a variant has one |
| `data_incident` | minor | a high-severity incident overlaps the 104 weeks of G |
| `redirect_coverage`, `dominant_redirect` | minor (one rule) | coverage < 90%, or one redirect > 30% |
| `young_article`, `renamed` | minor (one rule) | created shortly before the window, or renamed inside it |
| `project_shift` | minor | the whole edition changed by more than 25% in a year |
| `trend_conflict` | minor | a significant trend points against the yearly verdict |
| `proxy` | cap | a stand-in article (another Wikidata item) is used |

## Verify
Four variants from the saved data: spike-free G; half-year G (last 26 weeks vs the same 26 weeks a year
earlier); trend over the last 24 months; trend over the last 36 months (if available). Each gives +1, −1 or
0 (G: growing/declining; trend: sign when significant — with ≥ 4 languages by the Benjamini–Hochberg
q-value). If G has a direction: any opposite variant → **flips**; spike-free G at 0, or any variant whose
estimate points the other way even without significance → **weakens**; else **holds** (a same-sign half-year
or trend that is not significant does not weaken). If G has none: all 0 → holds, else weakens. Trust and
ranking are recomputed.

## Supply (is there content in that language?)
missing (no article) · short (a section, a stand-in, or < 30% of the median length of the other languages'
articles, with ≥ 2 of them) · good / featured (Wikidata badges) · regular.

## Ranking of audiences (≥ 2 languages)
- Components: level = percentile of share per million; momentum = percentile of the spike-free G; size =
  percentile of log(1 + mean monthly views, last 12 months); gap = 1 if supply is missing or short, else 0.
- Score = weighted mean. Default weights: level 0.35, momentum 0.35, size 0.2, gap 0.1 (`--weights`).
- Eligible: trust is not low and G is known. The top 3 eligible languages are "worth researching next".
  If none is eligible, the answer says no audience can be recommended yet and names the top 3 by score.

## Countries
- Readers of the whole edition (not of the topic) by country: top-by-country, last 12 complete months,
  top 5 shares. Wikimedia publishes rounded upper bounds.
- Spike breakdown: Wikimedia's differential-privacy dataset of daily views by country and page, from
  2023-02-06, published only for about 90+ views a day from one country.
