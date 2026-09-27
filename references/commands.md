# wir — command reference

Contents: output format · exit codes · error codes · `wir scope` · `wir analyze` · `wir verify` · `wir publish` ·
`wir status` · project files · environment variables.

Run the tool as `<skill-dir>/scripts/wir <command>` from the user's working directory. `wir` in every `cmd`
the tool prints means that same script.

All commands print one JSON object (at most about 3 KB): `ok, state, project, say, facts, caveats, ask, next,
files, error`. Keys without a value are left out. Progress messages go to stderr.

- `state`: `ready` (continue), `input_required` (ask the user `ask.question`), `failed` (see `error`).
- `ask`: `{"question", "options": [{"label", "cmd"}]}`. A `cmd` or `error.fix` with `<title>`, `<word>` or
  `<codes>` needs the exact title, word or language codes from the user in place of the placeholder.
- `next`: `[{"why", "cmd"}]`. `error`: `{"code", "message", "fix"}`.
- When the full answer does not fit, the last `say` or `caveats` line says the rest is in `analysis.json`.

| Exit code | Meaning | What to do |
|---|---|---|
| 0 | ready | continue |
| 2 | input_required | ask the user `ask.question`, run the chosen option's `cmd` |
| 3 | usage error | follow `error.fix` |
| 4 | network / rate limit | wait a minute and retry, or add `--offline` |
| 5 | no data / not cached / no project | follow `error.fix` |
| 6 | numbers in notes.md not found in the data | replace the listed numbers, run `wir publish` again |

## Error codes

| Code | Exit | Meaning |
|---|---|---|
| `BAD_ARGS` | 3 | unknown flag or wrong argument; `fix` names the right `--help` |
| `BAD_PERIOD`, `BAD_MONTH`, `BAD_WINDOW` | 3 | period not like `24m`/`2y`, month not `YYYY-MM`, or no complete month in the range |
| `BAD_ASSIGNMENT` | 3 | `--set`/`--add-article` not in the form `LANG="Title"` |
| `BAD_WEIGHTS` | 3 | `--weights` key not in level, momentum, size, gap, or a negative value |
| `MISSING_LANGS` | 3 | a new project needs `--langs`: ask the user which languages to compare |
| `LAST_LANG` | 3 | the only language of a project cannot be dropped |
| `UNKNOWN_LANG`, `UNKNOWN_SOURCE` | 3 | no open wiki with that code / unknown `--source` |
| `NOTES_MISSING`, `NOTES_INCOMPLETE`, `NOTES_TOO_LONG` | 3 | notes.md absent, a required section empty, or a section too long |
| `SCRIPT_UNSUPPORTED` | 3 | the notes use a script the PDF font cannot draw or right-to-left text; write English notes and use `--ui en` |
| `PDF_OVERFLOW` | 3 | the report does not fit one page even in its most compact form; shorten notes.md |
| `UV_MISSING`, `DEPS_MISSING` | 3 | uv is not installed / dependencies missing; `fix` has the install command |
| `INTERNAL` | 3 | unexpected failure; run the command once more, then report the message |
| `BAD_REQUEST`, `MEDIAWIKI_ERROR` | 3 or 4 | the API refused the request; 4 = temporary, run again in a minute |
| `NETWORK`, `UPSTREAM_ERROR`, `RATE_LIMITED`, `FORBIDDEN` | 4 | network failure, server error, too many requests, blocked User-Agent |
| `NO_PROJECT`, `TOPIC_NOT_FOUND`, `UNKNOWN_QID` | 5 | no project yet / nothing found for the topic / no such Wikidata item |
| `NOT_CACHED` | 5 | `--offline` and the data is not in the cache |
| `NOTHING_TO_ANALYZE` | 5 | no language has a usable article |
| `NOT_ANALYZED`, `STALE_ANALYSIS` | 5 | run `wir analyze` first / again (the project changed after the analysis) |
| `NUMBERS_NOT_IN_DATA` | 6 | numbers in notes.md are not in the data; the message lists each with the closest values |

## wir scope

```
usage: wir scope [-h] [--langs LANGS]
                 [--source {wikipedia,wiktionary,wikivoyage}]
                 [--period PERIOD] [--from YYYY-MM] [--to YYYY-MM] [--ui UI]
                 [--project PROJECT] [--add-lang CODE] [--drop-lang CODE]
                 [--set LANG="Title"] [--add-article LANG="Title"] [--fork]
                 [topic]

positional arguments:
  topic                 topic text or Wikidata QID, e.g. "intermittent
                        fasting" or Q1666254

options:
  -h, --help            show this help message and exit
  --langs LANGS         comma-separated wiki language codes, e.g. pl,cs
  --source {wikipedia,wiktionary,wikivoyage}
                        default: wikipedia
  --period PERIOD       window length, e.g. 24m or 2y (default 24m)
  --from YYYY-MM        window start month
  --to YYYY-MM          window end month
  --ui UI               language the user writes in, e.g. uk or en (default
                        en)
  --project PROJECT     project directory or id (default: latest)
  --add-lang CODE
  --drop-lang CODE
  --set LANG="Title"    use this article for LANG (checked by code)
  --add-article LANG="Title"
                        add a related article to the topic basket for LANG
  --fork                copy the project before changing it
```

Creating: `wir scope "<topic or QID>" --langs pl,cs --ui uk [--source wikipedia|wiktionary|wikivoyage] [--period 24m | --from YYYY-MM --to YYYY-MM]`
Editing the latest project (or `--project <dir>`): `--add-lang`, `--drop-lang`, `--set LANG="Title"`,
`--add-article LANG="Title"`, `--period`, `--from`/`--to`, `--ui`, `--fork`.

- `--add-lang` and `--drop-lang` take one code, a comma list (`sk,de`) or can be repeated. `--set`,
  `--add-article` can be repeated.
- `--set` checks the title (missing, disambiguation, redirect, section) and returns the article's first
  sentence; an article whose Wikidata item differs from the topic's is kept as a stand-in and caps trust at
  medium.
- `ask` appears when the topic is ambiguous, a language has no article, a title is unusable or a basket
  article is added before a main one. Every option is a ready command. A corrected language code (e.g.
  `cz` → `cs`) is reported in `caveats`.
- Editing an analysed project marks it stale: run `wir analyze` and `wir verify` again before `wir publish`.
  A new `wir analyze` also replaces earlier verify results.

## wir analyze

```
usage: wir analyze [-h] [--project PROJECT] [--offline] [--weights WEIGHTS]

options:
  -h, --help         show this help message and exit
  --project PROJECT  project directory or id (default: latest)
  --offline          use cached data only
  --weights WEIGHTS  ranking weights, e.g.
                     level=0.35,momentum=0.35,size=0.2,gap=0.1
```

- Downloads daily pageviews, computes share, yearly change, trend, spikes, seasonality, trust, reader
  countries, supply and ranking, draws the charts, writes `analysis.json` and the CSV files.
- One run spends at most about 90 seconds on downloads. If `next` contains `wir analyze`, run it again: it
  continues from the cache.
- `--weights` changes only the given keys (the others keep their defaults) and is saved in the project.
- `--offline` makes no network requests; optional country steps are skipped with a caveat.

## wir verify

```
usage: wir verify [-h] [--project PROJECT]

options:
  -h, --help         show this help message and exit
  --project PROJECT  project directory or id (default: latest)
```

Recomputes each verdict four other ways from the saved data (no network) and updates trust and ranking.
Outcome per language: holds, weakens or flips (see methodology.md).

## wir publish

```
usage: wir publish [-h] [--project PROJECT] [--notes NOTES] [--ui UI]

options:
  -h, --help         show this help message and exit
  --project PROJECT  project directory or id (default: latest)
  --notes NOTES      notes file (default: <project>/notes.md)
  --ui UI            report language override, e.g. en (default: the project's
                     language)
```

- Before: copy `notes.template.md` to `notes.md` in the project folder and write the first two sections
  (conclusion and recommendation, at most 420 characters each; the third, "what to check next", is optional,
  at most 260). Keep the headings.
- Every number in notes.md must be a number of the data (`say`, `facts`, `caveats`) or a correct rounding of
  it; percentages must match percentages. Years of the window, the period length and counts of languages or
  articles are also accepted. Numbers written in words are not checked.
- Result: `files.pdf` (one A4 page) and `files.md` (full report).

## wir status

```
usage: wir status [-h] [--project PROJECT]

options:
  -h, --help         show this help message and exit
  --project PROJECT  project directory or id (default: latest)
```

Shows the topic, languages, articles, whether the analysis and the report are done. No network.

## Files in wiki-interest-output/<date>-<topic>/
project.json · analysis.json (all results) · series_daily.csv · series_monthly.csv · charts/*.png ·
notes.template.md → notes.md (written by you) · report.pdf (one page) · report.md (full)

`<topic>` is a slug of the topic's label, or `q<QID>` when the label has no Latin letters. The newest
project is the default for every command; `--project` takes a folder path or its name.

## Environment variables
WIR_CONTACT (contact put in the User-Agent; set it to your e-mail or project URL) · WIR_CACHE_DIR ·
WIR_OUTPUT_DIR (default: `./wiki-interest-output`)
