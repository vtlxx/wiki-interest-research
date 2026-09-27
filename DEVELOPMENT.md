# Development

Contents: layout · module map · data flow · design rules · tests · adding a data provider · adding a UI
language · how AI-generated work was verified · verification results.

## Layout
```
SKILL.md                 what the agent reads (≤ 200 lines)
references/              loaded by the agent only when needed
scripts/wir              bash wrapper: runs wir.py through uv with the locked dependencies
scripts/wir.py           entry point (stdlib only; reports missing dependencies as JSON)
scripts/wir_core/        the tool
assets/                  incidents.json (data-problem calendar), language_aliases.json
tests/                   pytest; tests/fixtures/ holds recorded Wikimedia responses
install.sh               symlinks the skill into agent skill folders
```

## Module map (`scripts/wir_core/`)
| Module | Role |
|---|---|
| `cli.py` | argument parsing and dispatch; every path ends in exactly one JSON line on stdout |
| `envelope.py` | the JSON object every command prints (`ok, state, project, say, facts, caveats, ask, next, files, error`), kept ≤ 3 KB |
| `errors.py` | `WirError` (code, message, fix, exit code) and the exit codes 0/2/3/4/5/6 |
| `config.py` | version, User-Agent, cache/output paths, default ranking weights, `WIR_TODAY` pin |
| `net.py` | the only HTTP client: throttling (≥ 0.6 s between requests), retries with Retry-After, time budget, cache, record/replay |
| `cache.py` | SQLite cache of responses with a TTL per kind of data |
| `fixtures.py` | record and replay HTTP responses as JSON files named by URL hash |
| `providers/base.py` | the `Provider` protocol and its data classes |
| `providers/wikimedia.py` | Wikipedia/Wiktionary/Wikivoyage: languages, Wikidata, page status, redirects, moves, daily series, countries, spike geo |
| `project.py` | project state on disk (`project.json`, latest pointer, fork, `wir status`) |
| `scope.py` | `wir scope`: topic → articles per language, with an `ask` at every decision the user must make |
| `series.py` | daily/monthly series, windows, redirect selection, share per million |
| `stats.py` | yearly change with block bootstrap, trend (Theil–Sen, Mann–Kendall variants), spikes, seasonality, Benjamini–Hochberg |
| `incidents.py` | known data problems and their overlap with a window |
| `trust.py` | rule-based trust level with reason codes |
| `rank.py` | supply status and audience ranking |
| `geo.py` | reader countries and spike country breakdowns |
| `pipeline.py` | `wir analyze` and `wir verify` |
| `summary.py`, `fmt.py`, `i18n.py`, `locales/` | analysis → ready sentences in the user's language; the only place numbers become text |
| `charts.py` | PNG charts from `analysis.json` (drawing only, no statistics) |
| `publish/` | `wir publish`: notes parsing, number check (`numcheck.py`), one-page PDF, full Markdown report |

## Data flow
```
wir scope    topic ─► Wikidata item ─► article per language (+ asks) ─► project.json
wir analyze  project.json ─► provider: daily views of articles + redirects, edition totals
             ─► series (common window, share) ─► stats (G, trend, spikes, seasonality)
             ─► incidents + trust ─► countries, supply, ranking ─► analysis.json, CSV, charts
             ─► summary (say/facts/caveats) ─► envelope on stdout
wir verify   series_daily.csv ─► four variants ─► outcome per language ─► trust/ranking updated
wir publish  notes.md ─► numcheck against analysis.json ─► report.pdf + report.md
```

## Design rules
- The model never computes: every number the user sees comes from `summary.py` via `fmt.py`.
- Every decision that belongs to the user is an `ask` with ready commands; every error has a `fix`.
- Network code lives only in `net.py` and `providers/`; analysis modules are pure functions over pandas series.
- Wikimedia calls use `agent=user`, `access=all-access`, one request at a time, and a User-Agent with a contact.
- The skill directory holds only what the product needs.

## Tests
```bash
uv run pytest -q                          # offline (default): unit tests + end-to-end replays
uv run pytest -q -W error                 # the same with every warning as an error
uv run pytest -m live -q                  # real Wikimedia calls (set WIR_CONTACT first)
WIR_REFRESH_FIXTURES=1 uv run pytest tests/test_analyze_cli.py   # re-record fixtures from the live API
```
- Recorded responses live in `tests/fixtures/<scenario>/`; delete a folder before re-recording it (stale
  files are not removed). Recording uses `WIR_CONTACT` if exported.
- For manual runs: `WIR_RECORD=<dir> scripts/wir …` records every response into `<dir>`;
  `WIR_FIXTURES=<dir> scripts/wir …` replays them without network (a missing file is an error, a missing
  daily dataset file is a 404). `WIR_TODAY=YYYY-MM-DD` pins "today" so replays are stable.
- `WIR_CACHE_DIR` and `WIR_OUTPUT_DIR` isolate a run from the user cache and output.
- `tests/test_skill_md.py` checks the SKILL.md frontmatter and size budget, that every `wir …` command in
  SKILL.md parses with the real CLI, and that the references have no placeholders.
- `uvx --from skills-ref agentskills validate <path to this folder>` validates the skill format.

## Adding a data provider
1. Implement the `providers/base.Provider` protocol in `providers/<name>.py` (metadata, daily series,
   optional countries).
2. Declare `capabilities` — the subset of `project_totals, redirects, moves, geo, spike_geo, wikidata` it
   supports. The pipeline skips redirects, moves, reader countries (`geo`) and spike countries when they
   are not declared; `project_totals` (edition totals for share per million) is required today.
3. Return it from `get_provider()` in `providers/__init__.py` for its `--source` value, and add the value
   to the `--source` choices in `cli.py`.
4. Record fixtures for it and add an end-to-end replay test.

## Adding a UI language
Copy `scripts/wir_core/locales/en.json` to `<code>.json`, translate every value (keep the `{placeholders}`),
and add the code to `SUPPORTED` in `i18n.py`. `tests/test_i18n.py::test_locales_have_same_keys` fails until
every key exists. Check that the PDF font covers the script (`publish/pdf.py: font_covers`).

## How AI-generated work was verified
The code, tests and documents were written with AI coding agents under human direction. The output was
not trusted by default:
- **Statistics by TDD on synthetic data with known answers** — e.g. a doubling series, a planted 20% a year
  trend, a planted spike next to a small bump that must be ignored, a pure seasonal wave — before the real
  data was touched.
- **Recorded real API responses** replayed in end-to-end tests, so behaviour is checked against what
  Wikimedia actually returns (404 for missing data, partial months, redirects, renames).
- **An independent reviewer agent per block** read the spec, the plan and the diff, ran the real commands
  and reported must-fix / should-fix issues; every must-fix was fixed and re-reviewed.
- **Real calls for the three task examples** at every stage, with the outputs checked for plausibility
  against manual research notes.
- **Visual inspection** of every chart and PDF produced during the real calls (legibility, Cyrillic,
  one page, numbers equal to `analysis.json`).
- **Dry runs on Claude Haiku 4.5**: the cheap target model followed SKILL.md on the task examples; every
  number in its answers was checked against the data with `numcheck`, and SKILL.md was reworded wherever
  Haiku went wrong (invented next steps and trust reasons, a skipped robustness check).
- **Still to be recorded below:** a cross-check of pageview totals against pageviews.wmcloud.org for several
  articles, and scripted evaluation runs on Haiku 4.5 with a grader for the command order, the reaction to
  `ask` and the numbers in the answer.

## Verification results
Filled after the evaluation run.
