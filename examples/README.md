# Example reports

Real runs of the skill's tool on the three example questions it was built for, plus one topic driven by a
news spike. Every number in these files comes from the tool; the short conclusions were written from the
tool's facts block and passed `wir publish`'s number check.

- Data: Wikimedia pageviews through 2026-09-26, window 2024-09-01 – 2026-08-31, fetched 2026-09-27.
- Tool commit: `717be22`.
- Numbers change when re-run: Wikimedia data changes every day and past months are sometimes corrected
  (bot traffic removed afterwards), so a re-run gives a different window and may give different values.

| File | Question | What it shows |
|---|---|---|
| [fasting-pl-cs.pdf](fasting-pl-cs.pdf) | Compare the growth of interest in intermittent fasting on Polish and Czech Wikipedia over the last two years. | Polish Wikipedia has no article, so the tool asks what to do and the user drops Polish (a content gap, not zero interest). Czech: −48% a year, low trust (few views). |
| [astronomy-uk.pdf](astronomy-uk.pdf) | Is interest in astronomy growing on Ukrainian Wikipedia, and how far can we trust it? | Falling faster than the whole edition, strongly seasonal (peaks in September and December), the robustness check holds, medium trust. |
| [astronomy-uk.uk.pdf](astronomy-uk.uk.pdf) | The same question asked in Ukrainian. | The same analysis with the Ukrainian interface. |
| [english-learning.pdf](english-learning.pdf) | Compare interest in learning English in Polish, Czech, German, Ukrainian and Spanish and say which audiences to research next. | Five editions on one scale (share per million), a ranking with its weights, reader countries per edition, German weakened to low trust by the robustness check. |
| [spike-liam-payne.pdf](spike-liam-payne.pdf) | Interest in Liam Payne on English and Polish Wikipedia. | A year dominated by one news spike (2024-10-17): trust is low, the robustness check weakens (English) or reverses (Polish) the verdict, and no audience is recommended. |
| [report-preview.png](report-preview.png) | — | Page 1 of `english-learning.pdf` as an image. |
| `english-learning-*.png` | — | Three charts of the same run: [share](english-learning-share.png), [growth](english-learning-growth.png), [countries](english-learning-countries.png). |

## How they were produced

`wir` is `scripts/wir` of this skill. Each run used a fresh output folder (`WIR_OUTPUT_DIR`) and ran the
commands below in order; after `wir verify` the notes were written into `notes.md` (copied from
`notes.template.md`) using only numbers from its facts block, then `wir publish` built the PDF.

```bash
# fasting-pl-cs.pdf
wir scope "intermittent fasting" --langs pl,cs --ui en   # exit 2: Polish has no article
wir scope --drop-lang pl                                  # the option chosen
wir analyze && wir verify && wir publish

# astronomy-uk.pdf
wir scope "astronomy" --langs uk --ui en
wir analyze && wir verify && wir publish

# astronomy-uk.uk.pdf
wir scope "астрономія" --langs uk --ui uk
wir analyze && wir verify && wir publish

# english-learning.pdf (and the three charts from its charts/ folder)
wir scope "English language" --langs pl,cs,de,uk,es --ui en
wir analyze && wir verify && wir publish

# spike-liam-payne.pdf
wir scope "Liam Payne" --langs en,pl --ui en
wir analyze && wir verify && wir publish
```

The preview image was rendered with macOS Quick Look: `qlmanage -t -s 1400 -o . english-learning.pdf`.
