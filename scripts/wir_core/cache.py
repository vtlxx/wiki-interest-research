"""On-disk cache of HTTP responses and derived data (SQLite, zlib-compressed bodies)."""
from __future__ import annotations

import json
import sqlite3
import time
import zlib
from pathlib import Path
from typing import Any, Callable

from .config import cache_dir

TTL_RECENT = 7 * 86400      # series touching the last 13 months (Wikimedia backfills corrections)
TTL_OLD = 90 * 86400        # series ending before that
TTL_META = 7 * 86400        # search, sitelinks, redirects, page info
TTL_404 = 86400             # "no data" answers may become data tomorrow
TTL_STATIC = 365 * 86400    # published daily datasets, sitematrix-like reference data


class Cache:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, timeout=30)  # two `wir` processes may share the cache
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS http (key TEXT PRIMARY KEY, status INTEGER NOT NULL,"
            " body BLOB NOT NULL, fetched_at REAL NOT NULL, ttl INTEGER NOT NULL)")
        self._db.commit()
        self._clock = clock

    def get(self, key: str, allow_stale: bool = False) -> tuple[int, bytes] | None:
        row = self._db.execute("SELECT status, body, fetched_at, ttl FROM http WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        status, body, fetched_at, ttl = row
        if not allow_stale and fetched_at + ttl < self._clock():
            return None
        return status, zlib.decompress(body)

    def fetched_at(self, key: str) -> float | None:
        row = self._db.execute("SELECT fetched_at FROM http WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, status: int, body: bytes, ttl_s: int) -> None:
        self._db.execute("INSERT OR REPLACE INTO http VALUES (?, ?, ?, ?, ?)",
                         (key, status, zlib.compress(body), self._clock(), int(ttl_s)))
        self._db.commit()

    def latest(self, prefix: str) -> tuple[str, int, bytes] | None:
        """Newest entry (by fetch time, ignoring TTL) whose key starts with `prefix`, or None."""
        row = self._db.execute(
            "SELECT key, status, body FROM http WHERE substr(key, 1, ?) = ? ORDER BY fetched_at DESC LIMIT 1",
            (len(prefix), prefix)).fetchone()
        return None if row is None else (row[0], row[1], zlib.decompress(row[2]))

    def get_json(self, key: str, allow_stale: bool = False) -> Any | None:
        hit = self.get(key, allow_stale=allow_stale)
        return None if hit is None else json.loads(hit[1])

    def put_json(self, key: str, obj: Any, ttl_s: int) -> None:
        self.put(key, 200, json.dumps(obj, ensure_ascii=False).encode(), ttl_s)

    def close(self) -> None:
        self._db.close()


def open_default() -> Cache:
    return Cache(cache_dir() / "cache.sqlite")
