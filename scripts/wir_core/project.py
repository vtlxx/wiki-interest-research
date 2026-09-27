"""Project state on disk: ./wiki-interest-output/<id>/project.json plus a '.latest' pointer."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from .config import DEFAULT_WEIGHTS, output_root, today_utc  # DEFAULT_WEIGHTS re-exported for callers
from .envelope import make
from .errors import EXIT_NODATA, EXIT_USAGE, WirError
from .i18n import t
from .providers.base import USABLE_STATUSES

LATEST = ".latest"


@dataclass
class Article:
    title: str
    role: str = "main"
    status: str = "found"
    proxy: bool = False
    fragment: str | None = None
    length: int | None = None
    created: str | None = None
    extract: str | None = None
    qid: str | None = None


@dataclass
class LangEntry:
    lang: str
    status: str
    articles: list[Article] = field(default_factory=list)
    badges: list[str] = field(default_factory=list)
    note: str | None = None

    def main(self) -> Article | None:
        return self.articles[0] if self.articles else None

    def usable(self) -> bool:
        return self.status in USABLE_STATUSES and bool(self.articles)


@dataclass
class Project:
    id: str
    topic: str
    qid: str | None
    label: str
    description: str
    source: str
    langs: list[str]
    ui: str
    period_months: int = 24
    date_from: str | None = None
    date_to: str | None = None
    entries: dict[str, LangEntry] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    notes: list[str] = field(default_factory=list)
    key: str = ""
    created_at: str = ""

    @property
    def dir(self) -> Path:
        return output_root() / self.id

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "Project":
        entries = {lang: LangEntry(lang=e["lang"], status=e["status"],
                                   articles=[Article(**a) for a in e.get("articles", [])],
                                   badges=e.get("badges", []), note=e.get("note"))
                   for lang, e in data.get("entries", {}).items()}
        return cls(**{**data, "entries": entries})


def parse_period(text: str) -> int:
    m = re.fullmatch(r"\s*(\d+)\s*([my])\s*", (text or "").lower())
    months = int(m.group(1)) * (12 if m.group(2) == "y" else 1) if m else 0
    if not 6 <= months <= 120:
        raise WirError("BAD_PERIOD", f"period '{text}' is not between 6 months and 10 years",
                       fix="Use --period 24m (or 12m, 36m, 5y).", exit_code=EXIT_USAGE)
    return months


def parse_month(text: str) -> date:
    try:
        return datetime.strptime(text.strip(), "%Y-%m").date()
    except (ValueError, AttributeError) as exc:
        raise WirError("BAD_MONTH", f"'{text}' is not a month in YYYY-MM form",
                       fix="Use e.g. --from 2024-09 --to 2026-08.", exit_code=EXIT_USAGE) from exc


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:40]


def project_key(qid_or_topic: str, source: str, langs: list[str], period_months: int,
                date_from: str | None, date_to: str | None, ui: str) -> str:
    raw = json.dumps([qid_or_topic, source, sorted(langs), period_months, date_from, date_to, ui])
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def rel(path: Path) -> str:
    try:
        return os.path.relpath(path)
    except ValueError:
        return str(path)


def new_project(*, topic: str, qid: str | None, label: str, description: str, source: str, langs: list[str],
                ui: str, period_months: int, date_from: str | None, date_to: str | None) -> Project:
    base = f"{today_utc().isoformat()}-{slugify(label) or slugify(topic) or (qid or 'topic').lower()}"
    ident, n = base, 1
    while (output_root() / ident).exists():
        n += 1
        ident = f"{base}-{n}"
    return Project(id=ident, topic=topic, qid=qid, label=label, description=description, source=source,
                   langs=list(langs), ui=ui, period_months=period_months, date_from=date_from, date_to=date_to,
                   key=project_key(qid or topic, source, langs, period_months, date_from, date_to, ui),
                   created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def save(p: Project) -> None:
    p.dir.mkdir(parents=True, exist_ok=True)
    (p.dir / "project.json").write_text(json.dumps(p.to_json(), ensure_ascii=False, indent=2), "utf-8")
    (output_root() / LATEST).write_text(p.id, "utf-8")


def load(ref: str | None) -> Project:
    root = output_root()
    if ref:
        candidate = Path(ref)
        if candidate.name == "project.json":
            candidate = candidate.parent
        path = candidate if (candidate / "project.json").exists() else root / ref
    else:
        latest = root / LATEST
        path = root / latest.read_text("utf-8").strip() if latest.exists() else None
    if path is None or not (path / "project.json").exists():
        raise WirError("NO_PROJECT", f"no project found{' for ' + ref if ref else ''}",
                       fix='Create one first: wir scope "<topic>" --langs <codes> --ui <user language>',
                       exit_code=EXIT_NODATA)
    return Project.from_json(json.loads((path / "project.json").read_text("utf-8")))


def find_by_key(key: str) -> Project | None:
    root = output_root()
    if not root.exists():
        return None
    for path in sorted(root.glob("*/project.json")):
        data = json.loads(path.read_text("utf-8"))
        if data.get("key") == key:
            return Project.from_json(data)
    return None


def fork(p: Project) -> Project:
    base, n = f"{p.id}-fork", 1
    ident = base
    while (output_root() / ident).exists():
        n += 1
        ident = f"{base}{n}"
    shutil.copytree(p.dir, output_root() / ident)
    forked = Project.from_json({**p.to_json(), "id": ident, "key": ""})
    save(forked)
    return forked


def period_text(p: Project) -> str:
    if p.date_from or p.date_to:
        return t(p.ui, "period.range", start=p.date_from or "…", end=p.date_to or "…")
    return t(p.ui, "period.months", n=p.period_months)


def run_status(args) -> dict:
    p = load(getattr(args, "project", None))
    ui = p.ui
    say = [t(ui, "scope.summary", label=p.label, qid=p.qid or "—", source=p.source, n=len(p.langs),
             period=period_text(p))]
    facts = {}
    for lang in p.langs:
        entry = p.entries.get(lang)
        main = entry.main() if entry else None
        facts[lang] = {"status": entry.status if entry else "missing", "article": main.title if main else "—"}
    analysis = p.dir / "analysis.json"
    report = p.dir / "report.pdf"
    say.append(t(ui, "status.analyzed", when=datetime.fromtimestamp(analysis.stat().st_mtime).date().isoformat())
               if analysis.exists() else t(ui, "status.not_analyzed"))
    say.append(t(ui, "status.published", path=rel(report)) if report.exists() else t(ui, "status.not_published"))
    stale = (p.dir / ".stale").exists()
    nxt = [{"why": t(ui, "next.analyze"), "cmd": "wir analyze"}] if stale or not analysis.exists() else []
    files = {"project": rel(p.dir / "project.json")}
    if analysis.exists():
        files["data"] = rel(analysis)
    return make("ready", project=rel(p.dir), say=say, facts=facts, next_=nxt, files=files,
                caveats=[t(ui, "note.stale")] if stale else None)
