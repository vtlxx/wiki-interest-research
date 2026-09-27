"""Record/replay of HTTP responses for offline tests. Fixture file = {url, status, body, content_type}."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx


def fixture_name(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".json"


def write_fixture(directory: Path, url: str, status: int, body: str, content_type: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / fixture_name(url)).write_text(json.dumps(
        {"url": url, "status": status, "body": body, "content_type": content_type}, ensure_ascii=False),
        encoding="utf-8")


class FixtureTransport(httpx.BaseTransport):
    def __init__(self, dirs: list[Path], strict: bool = True):
        self.dirs = [Path(d) for d in dirs]
        self.strict = strict
        self.hits: list[str] = []
        self.misses: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for directory in self.dirs:
            path = directory / fixture_name(url)
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                self.hits.append(url)
                return httpx.Response(data["status"], content=data["body"].encode("utf-8"),
                                      headers={"content-type": data.get("content_type", "application/json")},
                                      request=request)
        self.misses.append(url)
        if url.endswith(".tsv"):  # daily dataset files exceed the recording limit and are never recorded
            return httpx.Response(404, content=b"", request=request)
        if self.strict:
            raise AssertionError(f"no fixture for {url} (record it with WIR_RECORD=<dir>)")
        return httpx.Response(404, content=b"", request=request)
