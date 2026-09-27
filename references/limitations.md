# Limitations

Each item: what the data cannot show → what that means for a conclusion.

- **Interest is not willingness to pay.** Pageviews measure curiosity; treat a growing topic as a lead to
  validate (surveys, landing pages, sales data), never as a sales forecast.
- **Readers are not target customers.** Students, journalists, researchers and editors read the same
  articles, so a large audience may contain few buyers.
- **A language is not a country.** Readers of one edition live in many countries (Spanish, English, Russian),
  and one country reads several editions; speak about countries only from the country data.
- **Bots misclassified as people.** Some automated traffic passes Wikimedia's filters; small editions and
  short periods are hit hardest, and the known cases are listed as data incidents.
- **History can be rewritten.** Wikimedia sometimes removes bot traffic from past months afterwards, so the
  same query can return different numbers later; the report carries its fetch date.
- **Overall Wikipedia traffic is falling** (search and AI answers show content without a visit). Share per
  million removes most of this, but not a shift that hits some topics more than others.
- **A topic is not an article.** A missing article is a content gap, not zero interest; a broader article,
  a section or a stand-in article measures something wider or narrower than the topic.
- **Redirects are checked within a request budget.** Rarely used redirects may stay unchecked and
  uncounted; their number is reported.
- **Merged or split articles are not detected.** A merge moves traffic between titles and can look like
  growth or decline.
- **Seasonality needs years.** With less than about 4 years of data the seasonality strength tends to be
  overestimated; it is not computed at all below 3 years.
- **Country data is rough.** It is rounded by Wikimedia and describes the whole edition, not the topic.
- **Spike country data is thresholded.** The daily country dataset starts on 2023-02-06 and publishes a
  country only above about 90 views a day, so small spikes have no country breakdown.
- **Numbers written in words are not checked** in notes.md; only digits are compared with the data.
- **PDF fonts cover Latin, Cyrillic and Greek only.** Notes in other scripts need an English report
  (`wir publish --ui en`); report.md keeps every script.
- **Only Wikimedia projects** (Wikipedia, Wiktionary, Wikivoyage) are supported; no search, app-store or
  sales data.
