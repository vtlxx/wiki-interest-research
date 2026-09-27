# wiki-interest-research

An Agent Skill that measures public interest in a topic across Wikipedia language editions from Wikimedia
pageviews, says how far the result can be trusted, and builds a one-page PDF report. It is written for
founders deciding which topic to build and which language market to research next, and it works with cheap
models: the `wir` tool does all data work and prints ready sentences, the agent routes and relays.

Questions it answers:
- "Compare the growth of interest in intermittent fasting on Polish and Czech Wikipedia over the last two years."
- "We are thinking of adding an astronomy course. Is interest growing on Ukrainian Wikipedia, and how far can we trust it?"
- "Compare interest in learning English in pl, cs, de, es and prepare a short report: which audiences should we research next?"

## Requirements
- [uv](https://docs.astral.sh/uv/) — it downloads Python 3.12 and the locked dependencies on first run.
- Internet access to `wikimedia.org`, `wikidata.org` and `analytics.wikimedia.org`.
- Optional: `WIR_CONTACT` — your e-mail or project URL, sent in the User-Agent as Wikimedia's API policy
  asks. Without it the tool sends this skill's repository URL.

## Install
```bash
./install.sh --project /path/to/your/project   # or: ./install.sh --user
```
The installer symlinks the skill into `.claude/skills/` (Claude Code, OpenCode) and `.agents/skills/` (Codex,
Gemini CLI, OpenCode and other clients), then installs the dependencies. Use `--agents claude` or
`--agents agents` to pick one. Running it again is safe.

## Quick start
Ask your agent one of the questions above. Under the hood it runs (outputs abbreviated from a real run):

```text
$ wir scope "intermittent fasting" --langs pl,cs --ui en          # exit 2: the user must decide
{"state":"input_required","say":["Topic: intermittent fasting (Q1666254) · wikipedia · 2 language(s) · …",
 "Polish: no article on this topic.","Czech: article “Přerušovaný půst”."],
 "ask":{"question":"Polish wikipedia has no article on “intermittent fasting”. What should be done?",
  "options":[{"label":"Continue without Polish","cmd":"wir scope --drop-lang pl"},
             {"label":"Głodówka lecznicza — …","cmd":"wir scope --set pl='Głodówka lecznicza'"}, …]}}

$ wir scope --drop-lang pl                                        # the option the user chose
{"state":"ready", …, "next":[{"why":"Fetch pageviews and compute trends","cmd":"wir analyze"}]}

$ wir analyze
{"state":"ready","say":["Czech: 3.04 views per million; year over year -48% (90% CI -62…-28%) — declining; trust: low.",
 "Czech — why this trust level: few views (under 300 a month), percentages are noisy; …", …],
 "facts":{"cs":{"share_per_m":"3.04","growth":"-48%","growth_ci":"-62…-28%","verdict":"declining","trust":"low", …}},
 "caveats":["Pageviews show curiosity, not willingness to pay: …", …],
 "files":{"data":"…/analysis.json","notes_template":"…/notes.template.md","share":"…/charts/share.png", …}}

$ wir verify
{"state":"ready","say":[…,"Czech: robustness check — the verdict holds; trust is now low.", …]}

$ cp …/notes.template.md …/notes.md   # the agent writes a short conclusion using only numbers from the data
$ wir publish
{"state":"ready","files":{"pdf":"…/report.pdf","md":"…/report.md"}}
```

Follow-up questions ("add Slovak", "over 5 years", "growth matters most to us") reuse the project and the
cache. `wir status` shows where a project stands.

## Outputs
Each project lives in `./wiki-interest-output/<date>-<topic>/`:
- `analysis.json` — every number, verdict and trust reason; `series_daily.csv`, `series_monthly.csv`.
- `charts/` — share per million, growth index, yearly change with intervals, reader countries, seasonality.
- `report.pdf` — one A4 page: conclusion, table, charts, limitations, sources.
- `report.md` — the full report with every article, redirect, caveat and the method.

## How trust is decided
Every language starts at high trust. Low volume, a short history, spikes that drive the result, known
Wikimedia data incidents, uncounted redirects, a renamed or young article, a shift of the whole edition or a
trend that disagrees with the yearly change each lower it; a verdict that reverses without spikes or under
`wir verify` makes it low. The full rules, formulas and thresholds: [references/methodology.md](references/methodology.md).

## Limitations
Pageviews show curiosity, not willingness to pay; a language is not a country; bots and data backfills
distort some months. The full list: [references/limitations.md](references/limitations.md).

## Testing
```bash
uv run pytest                 # offline: unit tests and end-to-end runs replayed from recorded API responses
uv run pytest -m live         # a few checks against the real Wikimedia APIs
uvx --from skills-ref agentskills validate ../wiki-interest-research
```
Agent-level evaluations on Claude Haiku 4.5 live in `evals/`. Details: [DEVELOPMENT.md](DEVELOPMENT.md).

## Privacy
The tool reads only public Wikimedia data and sends no user data anywhere. Requests carry a User-Agent with
`WIR_CONTACT` (or the repository URL). Responses are cached locally (`WIR_CACHE_DIR`, by default the OS
cache folder).

## License
MIT, see [LICENSE](LICENSE). Pageview data: Wikimedia Foundation, CC0; Wikidata: CC0.
