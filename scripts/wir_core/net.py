"""The only place that talks HTTP: User-Agent, throttling, retries, cache, fixture record/replay."""
from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import quote, urlencode, urlsplit

import httpx

from .cache import TTL_404, Cache, open_default
from .config import user_agent
from .errors import EXIT_NETWORK, EXIT_NODATA, EXIT_USAGE, WirError
from .fixtures import FixtureTransport, write_fixture

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RECORD_BYTES = 5_000_000


class BudgetExceeded(Exception):
    """Raised before a network request when the command's time budget is used up."""


class Deadline:
    def __init__(self, seconds: float | None, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._end = None if seconds is None else clock() + seconds

    def remaining(self) -> float | None:
        return None if self._end is None else self._end - self._clock()

    def check(self) -> None:
        if self._end is not None and self._clock() > self._end:
            raise BudgetExceeded()


def encode_title(title: str) -> str:
    return quote(title.replace(" ", "_"), safe="")


def build_url(url: str, params: dict | None = None) -> str:
    if not params:
        return url
    items = sorted((str(k), str(v)) for k, v in params.items())
    return url + ("&" if "?" in url else "?") + urlencode(items, quote_via=quote)


def _default_transport() -> httpx.BaseTransport | None:
    dirs = os.environ.get("WIR_FIXTURES")
    if not dirs:
        return None
    return FixtureTransport([Path(d) for d in dirs.split(os.pathsep) if d])


class HttpClient:
    def __init__(self, cache: Cache, *, offline: bool = False, transport: httpx.BaseTransport | None = None,
                 min_interval: float = 0.6, max_retries: int = 3, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, deadline: Deadline | None = None,
                 record_dir: Path | None = None, timeout: float = 60.0):
        self.cache = cache
        self.offline = offline
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.sleep = sleep
        self.clock = clock
        self.deadline = deadline
        rec = record_dir or os.environ.get("WIR_RECORD")
        self.record_dir = Path(rec) if rec else None
        self.requests_made = 0
        self._last: float | None = None
        self._client = httpx.Client(headers={"User-Agent": user_agent()}, timeout=timeout,
                                    transport=transport or _default_transport(), follow_redirects=True)

    # -- internals -------------------------------------------------------------------------
    def _throttle(self) -> None:
        if self._last is not None:
            wait = self.min_interval - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                value = float(retry_after)
            except ValueError:
                value = math.nan
            if math.isfinite(value) and value >= 0:
                return min(value, 60.0)
        return min(5.0 * (2 ** attempt), 60.0)

    def _pause(self, seconds: float) -> None:
        """Sleep before a retry, unless that would run past the command's time budget."""
        if self.deadline:
            remaining = self.deadline.remaining()
            if remaining is not None and remaining < seconds:
                raise BudgetExceeded()
        self.sleep(seconds)

    def _before_attempt(self) -> None:
        if self.deadline:
            self.deadline.check()
        self._throttle()
        self.requests_made += 1

    def _give_up(self, status: int | None, attempts: int, detail: str = "") -> WirError:
        if status == 429:
            return WirError("RATE_LIMITED", f"Wikimedia rate limit (HTTP 429) after {attempts} attempts",
                            fix="Wait one minute and run the same command again, or add --offline to use cached data.",
                            exit_code=EXIT_NETWORK)
        if status is None:
            return WirError("NETWORK", f"cannot reach Wikimedia: {detail}",
                            fix="Check the internet connection and run the same command again; "
                                "--offline works with cached data.", exit_code=EXIT_NETWORK)
        what = f"HTTP {status}, {detail}" if detail else f"HTTP {status}"
        return WirError("UPSTREAM_ERROR", f"Wikimedia answered {what} after {attempts} attempts",
                        fix="Run the same command again in a minute.", exit_code=EXIT_NETWORK)

    def _http_error(self, url: str, status: int, text: str) -> WirError:
        """Final (non-retried) HTTP error other than 404."""
        if status >= 500:
            return self._give_up(status, 1)
        detail = text[:200]
        try:
            body = json.loads(text)
            if isinstance(body, dict) and body.get("detail"):
                detail = str(body["detail"])[:200]
        except ValueError:
            pass
        host = urlsplit(url).netloc
        if status == 403:
            return WirError("FORBIDDEN", f"HTTP 403 from {host}: {detail}",
                            fix="Wikimedia refused the request (User-Agent policy or a temporary block). "
                                "Set WIR_CONTACT to your URL or e-mail, wait a few minutes and run the same "
                                "command again.", exit_code=EXIT_NETWORK)
        return WirError("BAD_REQUEST", f"HTTP {status} from {host}: {detail}",
                        fix="Check language codes and article titles, then run `wir scope` again.",
                        exit_code=EXIT_USAGE)

    def _request(self, url: str) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            self._before_attempt()
            try:
                resp = self._client.get(url)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise self._give_up(None, attempt + 1, str(exc)) from exc
                print(f"[wir] {type(exc).__name__}, retrying", file=sys.stderr)
                self._pause(self._backoff(attempt, None))
                continue
            except httpx.RequestError as exc:  # redirect loop, undecodable body: retrying will not help
                raise self._give_up(None, attempt + 1, f"{type(exc).__name__}: {exc}") from exc
            if resp.status_code in RETRY_STATUSES:
                if attempt == self.max_retries:
                    raise self._give_up(resp.status_code, attempt + 1)
                print(f"[wir] HTTP {resp.status_code}, retrying", file=sys.stderr)
                self._pause(self._backoff(attempt, resp.headers.get("retry-after")))
                continue
            return resp
        raise AssertionError("unreachable")

    def _record(self, resp: httpx.Response) -> None:
        if self.record_dir and len(resp.content) <= MAX_RECORD_BYTES:
            # Replay looks up the URL we asked for, not the one a redirect ended on.
            requested = resp.history[0].request.url if resp.history else resp.request.url
            write_fixture(self.record_dir, str(requested), resp.status_code, resp.text,
                          resp.headers.get("content-type", "application/json"))

    # -- public API --------------------------------------------------------------------------
    def get_json(self, url: str, params: dict | None = None, *, ttl: int) -> Any | None:
        """JSON body, or None when the server says 404 (Wikimedia: 'no data')."""
        full = build_url(url, params)
        hit = self.cache.get(full, allow_stale=self.offline)
        if hit is not None:
            status, body = hit
            return None if status == 404 else json.loads(body)
        if self.offline:
            raise WirError("NOT_CACHED", "this data is not in the local cache",
                           fix="Run the same command without --offline (needs internet).", exit_code=EXIT_NODATA)
        resp = self._request(full)
        self._record(resp)
        if resp.status_code == 404:
            self.cache.put(full, 404, b"", TTL_404)
            return None
        if resp.status_code >= 400:
            raise self._http_error(full, resp.status_code, resp.text)
        try:
            data = resp.json()
        except ValueError as exc:
            raise self._give_up(resp.status_code, 1, "response is not JSON") from exc
        self.cache.put(full, 200, resp.content, ttl)
        return data

    def iter_lines(self, url: str) -> Iterator[str]:
        """Stream a (large) text file line by line. Not cached here; callers cache what they keep.

        Failures before the first line are retried like get_json; a connection lost mid-file is not
        (lines were already handed out), it raises NETWORK instead."""
        if self.offline:
            raise WirError("NOT_CACHED", "this file is not in the local cache",
                           fix="Run the same command without --offline (needs internet).", exit_code=EXIT_NODATA)
        for attempt in range(self.max_retries + 1):
            self._before_attempt()
            started = False
            try:
                with self._client.stream("GET", url) as resp:
                    if resp.status_code == 404:
                        return
                    if resp.status_code in RETRY_STATUSES:
                        if attempt == self.max_retries:
                            raise self._give_up(resp.status_code, attempt + 1)
                        wait = self._backoff(attempt, resp.headers.get("retry-after"))
                        print(f"[wir] HTTP {resp.status_code}, retrying", file=sys.stderr)
                    elif resp.status_code >= 400:
                        raise self._http_error(url, resp.status_code, resp.read().decode("utf-8", "replace"))
                    else:
                        for line in resp.iter_lines():
                            started = True
                            yield line
                        return
            except httpx.TransportError as exc:
                if started or attempt == self.max_retries:
                    raise self._give_up(None, attempt + 1, str(exc)) from exc
                wait = self._backoff(attempt, None)
                print(f"[wir] {type(exc).__name__}, retrying", file=sys.stderr)
            except httpx.RequestError as exc:
                raise self._give_up(None, attempt + 1, f"{type(exc).__name__}: {exc}") from exc
            self._pause(wait)

    def close(self) -> None:
        self._client.close()


def open_client(offline: bool = False, deadline: Deadline | None = None) -> HttpClient:
    replaying = bool(os.environ.get("WIR_FIXTURES"))
    return HttpClient(open_default(), offline=offline, deadline=deadline, min_interval=0.0 if replaying else 0.6)
