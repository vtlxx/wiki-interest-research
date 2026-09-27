"""Provider interface: every data source (Wikimedia now; Fandom / MediaWiki later) implements it."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

FOUND = "found"
VIA_REDIRECT = "via_redirect"
SECTION = "section"
DISAMBIGUATION = "disambiguation"
MISSING = "missing"
PROXY = "proxy"
USABLE_STATUSES = {FOUND, VIA_REDIRECT, SECTION, PROXY}

BADGE_REDIRECT = {"Q70893996", "Q70894304"}   # sitelink to redirect / intentional sitelink to redirect
BADGE_GOOD = {"Q17437798"}
BADGE_FEATURED = {"Q17437796"}


@dataclass(frozen=True)
class Candidate:
    qid: str
    label: str
    description: str
    sitelinks: int
    exact: bool


@dataclass(frozen=True)
class PageInfo:
    lang: str
    requested: str
    title: str | None
    status: str
    fragment: str | None = None
    length: int | None = None
    created: date | None = None
    extract: str | None = None
    qid: str | None = None


@dataclass(frozen=True)
class Redirect:
    title: str
    views_60d: int | None
    fragment: str | None


@dataclass(frozen=True)
class Move:
    when: date
    source: str
    target: str


@dataclass(frozen=True)
class GeoRow:
    country: str
    code: str
    project: str
    title: str
    qid: str
    views: int


class Provider(Protocol):
    source: str
    capabilities: frozenset[str]

    def resolve_lang(self, code: str) -> tuple[str, str | None]: ...
    def lang_name(self, lang: str) -> str: ...
    def project_domain(self, lang: str) -> str: ...
    def aqs_project(self, lang: str) -> str: ...
    def article_url(self, lang: str, title: str) -> str: ...
    def search(self, text: str, lang: str, limit: int = 7) -> list[Candidate]: ...
    def entity(self, qid: str, ui: str) -> Candidate: ...
    def links(self, qid: str, langs: list[str]) -> dict[str, tuple[str | None, list[str]]]: ...
    def inspect(self, lang: str, titles: list[str]) -> dict[str, PageInfo]: ...
    def search_in_wiki(self, lang: str, text: str, limit: int = 5) -> list[tuple[str, str]]: ...
    def views_60d(self, lang: str, titles: list[str]) -> dict[str, int | None]: ...
    def redirects(self, lang: str, title: str) -> list[Redirect]: ...
    def moves(self, lang: str, titles: list[str]) -> list[Move]: ...
    def edits_on(self, lang: str, title: str, day: date) -> int: ...
    def article_daily(self, lang: str, title: str) -> dict[date, int]: ...
    def project_daily(self, lang: str) -> dict[date, int]: ...
    def countries(self, lang: str, year: int, month: int) -> list[tuple[str, int]]: ...
    def spike_geo(self, day: date, qids: list[str]) -> dict[str, list[GeoRow]]: ...
