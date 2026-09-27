---
name: wiki-interest-research
description: >-
  Measure and compare public interest in a topic across Wikipedia language editions (pageviews) to decide
  which topics to build and which languages or markets to launch in. Use for interest trends, growth and how
  far it can be trusted, comparing languages or countries, choosing audiences to research next, and one-page
  PDF reports. Also Wiktionary and Wikivoyage. Keywords: Wikipedia pageviews, Wikimedia, topic interest,
  language markets, інтерес до теми, перегляди Вікіпедії, мовні розділи.
license: MIT
compatibility: >-
  Needs uv (it installs Python 3.12 itself) and internet access to wikimedia.org, wikidata.org and
  analytics.wikimedia.org. Tested with Claude Code on Claude Haiku 4.5.
metadata:
  version: "0.1.0"
---

# Wikipedia interest research

Answers questions like "Is interest in X growing in language Y, and can we trust it?", "Compare X in
languages A and B", "Which audiences should we research next?" using Wikimedia pageview data.
The `wir` tool does ALL data work: fetching, statistics, charts, PDF. You run commands, relay results and
write a short conclusion.

## When not to use
- Sales, revenue or price forecasts; app-store or Google Trends data — this skill only has pageviews of
  Wikipedia, Wiktionary and Wikivoyage.
- Traffic of websites outside Wikimedia projects.

## How to run
Run `<skill-dir>/scripts/wir <command>` from the user's working directory (`<skill-dir>` = the folder of this
file). `wir` in every command below and in the tool's `cmd` fields means `<skill-dir>/scripts/wir`.
Never call python directly and never read the tool's source. Every command prints ONE JSON object:
- `state`: `ready` | `input_required` | `failed`
- `say`: ready sentences, numbers already formatted · `facts`: values per language · `caveats`: limits to mention
- `ask`: question for the user + `options`, each with a ready `cmd` · `next`: suggested commands
- `error.fix`: what to do when `state` is `failed` · `files`: paths of outputs

## Workflow — follow in order
1. `wir scope "<topic>" --langs <codes> --ui <user's language code>`
   The topic can be in any language or a Wikidata QID (e.g. Q1666254).
2. If `state` is `input_required`: ask the user `ask.question`, list the `ask.options` labels, run the `cmd`
   of the option the user picks. Never pick yourself. If that `cmd` contains `<title>`, ask the user for the
   exact title and put it in place of `<title>`. Repeat until `state` is `ready`.
3. `wir analyze`. If its `next` contains `wir analyze` again, run it again (downloads continue from cache).
4. If the user asks how far to trust the result, or any trust is not high: `wir verify`.
5. Answer in chat with the template below.
6. If the user wants a report/PDF (or asked for "a short report"):
   a. Copy the file `files.notes_template` to `notes.md` in the same folder.
   b. Write ≤ 3 sentences (≤ 400 characters) under each of the first two headings (conclusion, recommendation)
      in the user's language. Keep the headings. Use only numbers from `say`/`facts`.
   c. `wir publish`. On `NUMBERS_NOT_IN_DATA`: replace the listed numbers with values from `say`/`facts`, run again.
      On `SCRIPT_UNSUPPORTED`: rewrite notes.md in English and run `wir publish --ui en`.
   d. Give the user `files.pdf` and `files.md`.

## Request → flags
| User says | Flag |
|---|---|
| "last two years" / "за останні два роки" | `--period 24m` (default) |
| "last 5 years" | `--period 5y` |
| "from 2023 to 2025" | `--from 2023-01 --to 2025-12` |
| Polish, Czech, Slovak, Ukrainian, German, English, Spanish, French, Russian | `pl`, `cs`, `sk`, `uk`, `de`, `en`, `es`, `fr`, `ru` |
| user writes in Ukrainian / English / other | `--ui uk` / `--ui en` / `--ui <code>` (unsupported → English labels; still answer in the user's language) |
| words, vocabulary | `--source wiktionary` |
| travel destinations | `--source wikivoyage` |
| broad topic ("astronomy") | after scope add 2–5 key sub-articles: `wir scope --add-article uk="Сонячна система"` |

## Follow-ups — reuse the project (data comes from cache)
| User says | Commands |
|---|---|
| "add Slovak" | `wir scope --add-lang sk`, then `wir analyze` |
| "over 5 years" | `wir scope --period 5y`, then `wir analyze` |
| "use another article for Polish" | `wir scope --set pl="Głodówka lecznicza"` (the tool checks it; tell the user the first sentence it returns), then `wir analyze` |
| "growth matters most to us" | `wir analyze --weights momentum=0.6,level=0.2` |
| "keep the previous version" | add `--fork`: `wir scope --add-lang sk --fork` |
| new chat / "where were we?" | `wir status` |

## Answer template (in the user's language)
**Short answer:** 1–2 sentences taken from `say`.
**Data:** one line per language — share per million, 12-month change with CI, verdict, trust (from `facts`).
**Why this trust level:** 1–3 reasons (from `say`).
**Limitations:** 2–3 most relevant `caveats` (always: interest is not willingness to pay).
**Next:** 1–2 items from `next`; offer the PDF if it is not built yet.

## Rules
- Never calculate numbers (no ratios like "2.7×", no sums, no averages). Quote numbers only from `say`/`facts`.
- Name the topic exactly as the first `say` line of `wir scope` or `wir status` does; never guess what a QID means.
- Never invent article titles; propose them only with `--set` so the tool verifies them.
- Never compare raw view counts across languages; compare share per million and change.
- Say "interest", never "demand" or "people will pay".
- Never skip `ask`: the user decides.
- A missing article is a finding (content gap), not zero interest: tell the user about every dropped language.
- A language is not a country: speak about countries only from `facts.countries` and `say`.
- Do not edit files in `wiki-interest-output/` except `notes.md`.
- When `state` is `failed`, follow `error.fix` exactly; do not improvise.

## Examples (exact command sequences)
1. "Порівняй зростання інтересу до інтервального голодування в польськомовній та чеськомовній Вікіпедії за останні два роки."
   `wir scope "інтервальне голодування" --langs pl,cs --ui uk --period 24m` → `input_required` (no Polish article) →
   ask the user → e.g. `wir scope --drop-lang pl` → `wir analyze` → answer, stating that Polish Wikipedia has no such article.
2. "Ми думаємо додати курс з астрономії. Чи зростає інтерес в україномовній Вікіпедії, і наскільки цьому можна довіряти?"
   `wir scope "астрономія" --langs uk --ui uk` → `wir scope --add-article uk="Сонячна система" --add-article uk="Чорна діра"` →
   `wir analyze` → `wir verify` → answer with the trust reasons and seasonality.
3. "Порівняй інтерес до вивчення англійської у pl, cs, de, es і підготуй короткий звіт: які аудиторії дослідити далі?"
   `wir scope "англійська мова" --langs pl,cs,de,es --ui uk` → (answer `ask` if any) → `wir analyze` → `wir verify` →
   answer with the ranking sentence → notes.md → `wir publish`.

## More detail (read only when needed)
- `references/commands.md` — every flag, exit code, output file (`wir <command> --help` also works).
- `references/methodology.md` — how each number is computed (use when the user asks "how").
- `references/limitations.md` — full list of limitations.
