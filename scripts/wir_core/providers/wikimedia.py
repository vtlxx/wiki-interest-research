"""Wikimedia projects (Wikipedia, Wiktionary, Wikivoyage): metadata via MediaWiki/Wikidata APIs."""
from __future__ import annotations

import html
import json
import re
import sys
from dataclasses import asdict, replace
from datetime import date, timedelta
from urllib.parse import urlsplit

from ..cache import TTL_404, TTL_META, TTL_OLD, TTL_RECENT, TTL_STATIC
from ..config import assets_dir, today_utc
from ..errors import EXIT_NETWORK, EXIT_NODATA, EXIT_USAGE, WirError
from ..geo import parse_dp_lines
from ..net import HttpClient, encode_title
from .base import (DISAMBIGUATION, FOUND, MISSING, SECTION, VIA_REDIRECT, Candidate, GeoRow, Move,
                   PageInfo, Redirect)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
META_API = "https://meta.wikimedia.org/w/api.php"
SITE_CODE = {"wikipedia": "wiki", "wiktionary": "wiktionary", "wikivoyage": "wikivoyage"}
MAX_PV_REQUESTS = 6          # prop=pageviews continuation budget per call of views_60d
MAX_MOVE_LOOKUPS = 30        # move-log lookups per article
AQS = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
DATA_START = date(2015, 7, 1)                # pageviews start; earlier dates are silently ignored by AQS
DP_URL = "https://analytics.wikimedia.org/published/datasets/country_project_page/{day}.tsv"
DP_START = date(2023, 2, 6)                  # first day of the differential-privacy country/project/page dataset
_PUBLICATION = re.compile(r"\b(scholarly|scientific|journal) article\b|\bthesis\b|\bpreprint\b", re.I)
_TAG = re.compile(r"<[^>]+>")
# MediaWiki error codes that mean "try again later", not "bad input".
_TRANSIENT = {"ratelimited", "maxlag", "readonly", "internal_api_error_DBQueryError"}


def _parse_items(data: dict | None) -> dict[date, int]:
    out: dict[date, int] = {}
    for item in (data or {}).get("items", []):
        ts = item["timestamp"]
        out[date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))] = int(item["views"])
    return out


def _is_recent_month(year: int, month: int) -> bool:
    """True when (year, month) is one of the last 13 months relative to today (spec 5.5: that window is
    still short-TTL because Wikimedia backfills corrections into it, per spec A.5)."""
    today = today_utc()
    months_ago = (today.year - year) * 12 + (today.month - month)
    return 0 <= months_ago <= 12


def _segment_date(segment: str) -> date:
    """End-date URL segment of an AQS series ('YYYYMMDD' or 'YYYYMMDDHH') as a date."""
    return date(int(segment[:4]), int(segment[4:6]), int(segment[6:8]))


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _check(data: dict | None) -> dict:
    if data is None:
        raise WirError("MEDIAWIKI_ERROR", "empty answer from the MediaWiki API",
                       fix="Run the same command again.", exit_code=EXIT_NETWORK)
    if "error" in data:
        err = data["error"]
        code = str(err.get("code", ""))
        if code in _TRANSIENT or code.startswith("internal_api_error"):
            raise WirError("MEDIAWIKI_ERROR", f"{code}: {err.get('info')}",
                           fix="Wikimedia is busy; run the same command again in a minute.",
                           exit_code=EXIT_NETWORK)
        raise WirError("MEDIAWIKI_ERROR", f"{code}: {err.get('info')}",
                       fix="Check the language code and the title.", exit_code=EXIT_USAGE)
    return data


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    text = html.unescape(_TAG.sub("", text)).strip()
    return text[:300] or None


class WikimediaProvider:
    def __init__(self, source: str, http: HttpClient):
        if source not in SITE_CODE:
            raise WirError("UNKNOWN_SOURCE", f"unknown source '{source}'",
                           fix="Use --source wikipedia, wiktionary or wikivoyage.")
        self.source = source
        self.http = http
        base = {"project_totals", "redirects", "moves", "geo", "spike_geo"}
        self.capabilities = frozenset(base | ({"wikidata"} if source != "wiktionary" else set()))
        self._sites_cache: dict[str, dict] | None = None
        self._closed: set[str] = set()
        self._created_cache: dict[tuple[str, str], date | None] = {}
        self._through: dict[str, date] = {}  # series URL without its end-date segment -> end date used

    # ---- languages ---------------------------------------------------------------------------
    def _sites(self) -> dict[str, dict]:
        if self._sites_cache is None:
            data = _check(self.http.get_json(META_API, {"action": "sitematrix", "smtype": "language",
                                                        "format": "json"}, ttl=TTL_OLD))
            sites: dict[str, dict] = {}
            for key, entry in data["sitematrix"].items():
                if not key.isdigit():
                    continue
                for site in entry.get("site", []):
                    if site.get("code") != SITE_CODE[self.source]:
                        continue
                    lang = urlsplit(site["url"]).netloc.split(".")[0]
                    if "closed" in site:
                        self._closed.add(lang)
                        continue
                    sites[lang] = {"dbname": site["dbname"],
                                   "name": entry.get("localname") or entry.get("name") or lang}
            self._sites_cache = sites
        return self._sites_cache

    def resolve_lang(self, code: str) -> tuple[str, str | None]:
        typed = code.strip().lower()
        sites = self._sites()
        if typed in sites:
            return typed, None
        aliases = json.loads((assets_dir() / "language_aliases.json").read_text())
        alias = aliases.get(typed)
        if alias and alias in sites:
            return alias, f"'{code}' is not a {self.source} language code; using '{alias}' ({sites[alias]['name']})."
        what = "is a closed" if typed in self._closed else "is not an open"
        raise WirError("UNKNOWN_LANG", f"'{code}' {what} {self.source} language edition",
                       fix="Use wiki language codes such as uk, pl, cs, en, de, fr, es "
                           "(list: https://meta.wikimedia.org/wiki/Special:SiteMatrix).")

    def lang_name(self, lang: str) -> str:
        return self._sites().get(lang, {}).get("name", lang)

    def project_domain(self, lang: str) -> str:
        return f"{lang}.{self.source}.org"

    def aqs_project(self, lang: str) -> str:
        return f"{lang}.{self.source}"

    def article_url(self, lang: str, title: str) -> str:
        return f"https://{self.project_domain(lang)}/wiki/{encode_title(title)}"

    def _api(self, lang: str, params: dict, ttl: int = TTL_META) -> dict:
        url = f"https://{self.project_domain(lang)}/w/api.php"
        return _check(self.http.get_json(url, {**params, "format": "json", "formatversion": 2}, ttl=ttl))

    def _wikidata(self, params: dict) -> dict:
        return _check(self.http.get_json(WIKIDATA_API, {**params, "format": "json"}, ttl=TTL_META))

    # ---- Wikidata ----------------------------------------------------------------------------
    def _sitelink_counts(self, qids: list[str]) -> dict[str, int]:
        dbnames = {site["dbname"] for site in self._sites().values()}
        counts: dict[str, int] = {}
        for chunk in _chunks(qids, 50):
            data = self._wikidata({"action": "wbgetentities", "ids": "|".join(chunk), "props": "sitelinks"})
            for qid, ent in data.get("entities", {}).items():
                counts[qid] = sum(1 for db in ent.get("sitelinks", {}) if db in dbnames)
        return counts

    def search(self, text: str, lang: str, limit: int = 7) -> list[Candidate]:
        found: dict[str, dict] = {}
        needle = text.strip().casefold()
        for search_lang in dict.fromkeys([lang, "en"]):
            data = self._wikidata({"action": "wbsearchentities", "search": text.strip(), "language": search_lang,
                                   "uselang": search_lang, "type": "item", "limit": limit})
            for hit in data.get("search", []):
                exact = hit.get("match", {}).get("text", "").casefold() == needle
                prev = found.get(hit["id"])
                found[hit["id"]] = {
                    "label": prev["label"] if prev else hit.get("label", hit["id"]),
                    "description": (prev["description"] if prev else "") or hit.get("description", ""),
                    "exact": exact or bool(prev and prev["exact"]),
                }
        if not found:
            return []
        counts = self._sitelink_counts(list(found))
        cands = [Candidate(q, v["label"], v["description"], counts.get(q, 0), v["exact"]) for q, v in found.items()]
        cands = [c for c in cands if c.sitelinks > 0 and not _PUBLICATION.search(c.description)]
        return sorted(cands, key=lambda c: (not c.exact, -c.sitelinks))[:limit]

    def entity(self, qid: str, ui: str) -> Candidate:
        data = self._wikidata({"action": "wbgetentities", "ids": qid, "props": "labels|descriptions|sitelinks",
                               "languages": "|".join(dict.fromkeys([ui, "en"]))})
        ent = data.get("entities", {}).get(qid)
        if not ent or "missing" in ent:
            raise WirError("UNKNOWN_QID", f"Wikidata item {qid} does not exist",
                           fix="Search by topic text instead of a QID.", exit_code=EXIT_NODATA)
        labels, descs = ent.get("labels", {}), ent.get("descriptions", {})
        pick = lambda d: (d.get(ui) or d.get("en") or {}).get("value", "")  # noqa: E731
        dbnames = {site["dbname"] for site in self._sites().values()}
        return Candidate(qid, pick(labels) or qid, pick(descs),
                         sum(1 for db in ent.get("sitelinks", {}) if db in dbnames), True)

    def links(self, qid: str, langs: list[str]) -> dict[str, tuple[str | None, list[str]]]:
        data = self._wikidata({"action": "wbgetentities", "ids": qid, "props": "sitelinks"})
        ent = data.get("entities", {}).get(qid, {})
        if "missing" in ent:
            raise WirError("UNKNOWN_QID", f"Wikidata item {qid} does not exist", exit_code=EXIT_NODATA)
        sitelinks, sites = ent.get("sitelinks", {}), self._sites()
        out: dict[str, tuple[str | None, list[str]]] = {}
        for lang in langs:
            link = sitelinks.get(sites[lang]["dbname"]) if lang in sites else None
            out[lang] = (link["title"], list(link.get("badges", []))) if link else (None, [])
        return out

    # ---- MediaWiki page metadata -------------------------------------------------------------
    def _created(self, lang: str, title: str) -> date | None:
        key = (lang, title)
        if key not in self._created_cache:
            data = self._api(lang, {"action": "query", "titles": title, "prop": "revisions", "rvlimit": 1,
                                    "rvdir": "newer", "rvprop": "timestamp"}, ttl=TTL_OLD)
            pages = data.get("query", {}).get("pages", [])
            revs = pages[0].get("revisions", []) if pages else []
            self._created_cache[key] = date.fromisoformat(revs[0]["timestamp"][:10]) if revs else None
        return self._created_cache[key]

    def inspect(self, lang: str, titles: list[str]) -> dict[str, PageInfo]:
        """Canonical page for each requested title; 'Title#Section' is looked up as a section of 'Title'."""
        out: dict[str, PageInfo] = {}
        for chunk in _chunks(list(dict.fromkeys(titles)), 20):
            bases = {t: t.partition("#")[0].strip() for t in chunk}
            data = self._api(lang, {"action": "query", "titles": "|".join(dict.fromkeys(bases.values())),
                                    "redirects": 1, "converttitles": 1,
                                    "prop": "info|pageprops|extracts", "ppprop": "disambiguation|wikibase_item",
                                    "exintro": 1, "explaintext": 1, "exsentences": 1, "exlimit": 20})
            q = data.get("query", {})
            norm = {n["from"]: n["to"] for n in q.get("normalized", [])}
            conv = {c["from"]: c["to"] for c in q.get("converted", [])}  # script variants (zh, sr, kk, ...)
            redirs = {r["from"]: r for r in q.get("redirects", [])}
            pages = {p["title"]: p for p in q.get("pages", [])}
            for requested in chunk:
                name = norm.get(bases[requested], bases[requested])
                name, fragment, was_redirect = conv.get(name, name), None, False
                for _ in range(3):  # follow short redirect chains
                    r = redirs.get(name)
                    if not r:
                        break
                    was_redirect, fragment, name = True, r.get("tofragment") or fragment, r["to"]
                asked_section = requested.partition("#")[2].strip()
                if asked_section:
                    was_redirect, fragment = True, asked_section
                page = pages.get(name)
                if page is None or page.get("missing") or page.get("invalid") or page.get("ns", 0) != 0:
                    out[requested] = PageInfo(lang, requested, None, MISSING)
                    continue
                props = page.get("pageprops", {})
                if "disambiguation" in props:
                    status = DISAMBIGUATION
                elif was_redirect and fragment:
                    status = SECTION
                elif was_redirect:
                    status = VIA_REDIRECT
                else:
                    status = FOUND
                out[requested] = PageInfo(lang, requested, page["title"], status, fragment, page.get("length"),
                                          None, _clean(page.get("extract")), props.get("wikibase_item"))
        for requested, info in list(out.items()):
            if info.title and info.status != DISAMBIGUATION:
                out[requested] = replace(info, created=self._created(lang, info.title))
        return out

    def search_in_wiki(self, lang: str, text: str, limit: int = 5) -> list[tuple[str, str]]:
        data = self._api(lang, {"action": "query", "list": "search", "srsearch": text, "srlimit": limit,
                                "srnamespace": 0, "srprop": "snippet"})
        return [(hit["title"], _clean(hit.get("snippet")) or "") for hit in data.get("query", {}).get("search", [])]

    def views_60d(self, lang: str, titles: list[str]) -> dict[str, int | None]:
        result: dict[str, int | None] = {t: None for t in titles}
        requests = 0
        for chunk in _chunks(list(dict.fromkeys(titles)), 50):
            cont: dict = {}
            while requests < MAX_PV_REQUESTS:
                data = self._api(lang, {"action": "query", "titles": "|".join(chunk), "prop": "pageviews",
                                        "pvipdays": 60, **cont})
                requests += 1
                q = data.get("query", {})
                back: dict[str, list[str]] = {}
                for n in q.get("normalized", []):
                    back.setdefault(n["to"], []).append(n["from"])
                for page in q.get("pages", []):
                    views = page.get("pageviews")
                    if views is None:
                        continue
                    for title in (page.get("title"), *back.get(page.get("title"), [])):
                        if title in result:
                            result[title] = int(sum(v or 0 for v in views.values()))
                if "continue" not in data:
                    break
                cont = data["continue"]
        return result

    def redirects(self, lang: str, title: str) -> list[Redirect]:
        items: list[tuple[str, str | None]] = []
        cont: dict = {}
        for _ in range(3):
            data = self._api(lang, {"action": "query", "titles": title, "prop": "redirects",
                                    "rdprop": "title|fragment", "rdlimit": "max", "rdnamespace": 0, **cont})
            for page in data.get("query", {}).get("pages", []):
                items.extend((r["title"], r.get("fragment")) for r in page.get("redirects", []))
            if "continue" not in data:
                break
            cont = data["continue"]
        views = self.views_60d(lang, [t for t, _ in items]) if items else {}
        return [Redirect(t, views.get(t), f) for t, f in items]

    def moves(self, lang: str, titles: list[str]) -> list[Move]:
        """Article-to-article renames whose old title is one of `titles` (the move log is indexed by the old
        title). Moves into other namespaces (drafts, page-swap scratch titles) are dropped. A rename whose old
        title is no longer a redirect to the article is only found if the caller passes that old title."""
        unique = list(dict.fromkeys(titles))
        if len(unique) > MAX_MOVE_LOOKUPS:
            print(f"[wir] move log checked for {MAX_MOVE_LOOKUPS} of {len(unique)} titles", file=sys.stderr)
        out: set[Move] = set()
        for title in unique[:MAX_MOVE_LOOKUPS]:
            data = self._api(lang, {"action": "query", "list": "logevents", "letype": "move", "letitle": title,
                                    "lelimit": 50, "leprop": "title|details|timestamp"})
            for ev in data.get("query", {}).get("logevents", []):
                params = ev.get("params", {})
                target = params.get("target_title")
                if target and ev.get("title") and ev.get("ns") == 0 and params.get("target_ns") == 0:
                    out.add(Move(date.fromisoformat(ev["timestamp"][:10]), ev["title"], target))
        return sorted(out, key=lambda m: (m.when, m.source))

    def edits_on(self, lang: str, title: str, day: date) -> int:
        ttl = TTL_OLD if day < today_utc() - timedelta(days=2) else TTL_404
        data = self._api(lang, {"action": "query", "titles": title, "prop": "revisions", "rvprop": "timestamp",
                                "rvlimit": 500, "rvstart": f"{day.isoformat()}T23:59:59Z",
                                "rvend": f"{day.isoformat()}T00:00:00Z"}, ttl=ttl)
        pages = data.get("query", {}).get("pages", [])
        return len(pages[0].get("revisions", [])) if pages else 0

    # ---- pageview series (AQS) ------------------------------------------------------------------
    def _series(self, url: str) -> dict | None:
        """Series URLs end with the end date; offline mode falls back to the newest cached copy of the
        SAME series (the cache key up to the final '/' — the date segment is what varies day to day).
        The end date of the copy actually returned is remembered for series_through()."""
        prefix, end = url.rsplit("/", 1)
        if self.http.offline:
            hit = self.http.cache.latest(prefix + "/")
            if hit is not None:
                key, status, body = hit
                self._through[prefix] = _segment_date(key.rsplit("/", 1)[1])
                return None if status == 404 else json.loads(body)
        data = self.http.get_json(url, ttl=TTL_RECENT)
        self._through[prefix] = _segment_date(end)
        return data

    def _article_prefix(self, lang: str, title: str) -> str:
        return (f"{AQS}/per-article/{self.aqs_project(lang)}/all-access/user/{encode_title(title)}"
                f"/daily/{DATA_START:%Y%m%d}")

    def _project_prefix(self, lang: str) -> str:
        return f"{AQS}/aggregate/{self.aqs_project(lang)}/all-access/user/daily/{DATA_START:%Y%m%d}00"

    def article_daily(self, lang: str, title: str) -> dict[date, int]:
        end = today_utc() - timedelta(days=1)
        return _parse_items(self._series(f"{self._article_prefix(lang, title)}/{end:%Y%m%d}"))

    def project_daily(self, lang: str) -> dict[date, int]:
        end = today_utc() - timedelta(days=1)
        return _parse_items(self._series(f"{self._project_prefix(lang)}/{end:%Y%m%d}00"))

    def series_through(self, lang: str, title: str | None = None) -> date | None:
        """Last day covered by the daily series returned earlier by this provider (title None = the project
        series), or None if it was not fetched. Offline, article and project copies can end on different
        days; callers should cut the analysis at the earliest of these dates."""
        prefix = self._project_prefix(lang) if title is None else self._article_prefix(lang, title)
        return self._through.get(prefix)

    def countries(self, lang: str, year: int, month: int) -> list[tuple[str, int]]:
        ttl = TTL_RECENT if _is_recent_month(year, month) else TTL_OLD
        data = self.http.get_json(f"{AQS}/top-by-country/{self.aqs_project(lang)}/all-access/{year}/{month:02d}",
                                  ttl=ttl)
        items = (data or {}).get("items", [])
        rows = items[0].get("countries", []) if items else []
        return [(r["country"], int(r["views_ceil"])) for r in rows if r.get("country") not in (None, "--")]

    def spike_geo(self, day: date, qids: list[str]) -> dict[str, list[GeoRow]]:
        """Country x project breakdown of one day's traffic to the given Wikidata items, from the
        differential-privacy dataset. Streamed and cached per (day, qid), including empty results, so a
        repeated call for the same day never re-downloads the file, even when it only re-asks for a subset
        of the QIDs already seen; a QID not seen before for that day still triggers one more download.
        A file that is not published yet (404, no lines) is not cached and raises NOT_PUBLISHED (exit 5)."""
        if day < DP_START:
            return {q: [] for q in qids}
        cache = self.http.cache
        out: dict[str, list[GeoRow]] = {}
        missing: list[str] = []
        for qid in dict.fromkeys(qids):
            hit = cache.get_json(f"dp:{day.isoformat()}:{qid}", allow_stale=True)
            if hit is None:
                missing.append(qid)
            else:
                out[qid] = [GeoRow(**row) for row in hit]
        if missing:
            # If the download breaks mid-file, parse_dp_lines raises before returning and this assignment
            # never completes, so no qid is cached from a partial file (HANDOFF open issue #6).
            seen = [0]

            def counted(lines):
                for line in lines:
                    seen[0] += 1
                    yield line

            rows = parse_dp_lines(counted(self.http.iter_lines(DP_URL.format(day=day.isoformat()))), set(missing))
            if not seen[0]:  # no lines = file not published yet (404): it may appear later, so cache nothing
                raise WirError("NOT_PUBLISHED", f"the country dataset for {day.isoformat()} is not published yet",
                               fix="Run the same command again in a day or two.", exit_code=EXIT_NODATA)
            for qid in missing:
                out[qid] = rows.get(qid, [])
                cache.put_json(f"dp:{day.isoformat()}:{qid}", [asdict(r) for r in out[qid]], TTL_STATIC)
        return out
