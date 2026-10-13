"""Client for the USPTO Open Data Portal (ODP) patent file-wrapper API.

API docs: https://data.uspto.gov/apis/patent-file-wrapper/search
An API key is required (free; request one at https://data.uspto.gov/myodp).
Set it in the ``USPTO_API_KEY`` environment variable.

The same parser also reads the ODP bulk JSON files (Patent File Wrapper bulk
dataset), which use the same record shape.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Iterator

from .db import Application, Event

API_ROOT = "https://api.uspto.gov/api/v1"
BASE_URL = f"{API_ROOT}/patent/applications/search"
# Scanned patent and pre-grant publication PDFs; public, no key needed.
PATENT_PDF_URL = "https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/{number}"
PAGE_SIZE = 100


class ApiError(RuntimeError):
    pass


def _date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_record(rec: dict[str, Any]) -> Application | None:
    """Convert one ``patentFileWrapperDataBag`` entry into an Application."""
    app_no = rec.get("applicationNumberText")
    if not app_no:
        return None
    meta = rec.get("applicationMetaData") or {}
    filing = _date(meta.get("filingDate"))
    # 371(c) date for national-stage entries; falls back to the filing date.
    nat_stage = _date(meta.get("nationalStageEntryDate") or meta.get("pctNationalStageEntryDate"))
    events = [
        Event(d, e.get("eventCode") or "", e.get("eventDescriptionText") or "")
        for e in rec.get("eventDataBag") or []
        if (d := _date(e.get("eventDate")))
    ]
    return Application(
        app_no=str(app_no),
        examiner=(meta.get("examinerNameText") or "").strip().upper() or None,
        art_unit=(meta.get("groupArtUnitNumber") or None),
        filing_date=filing,
        effective_date=nat_stage or filing,
        status_code=str(meta.get("applicationStatusCode") or "") or None,
        status_text=meta.get("applicationStatusDescriptionText"),
        status_date=_date(meta.get("applicationStatusDate")),
        patent_number=meta.get("patentNumber") or None,
        grant_date=_date(meta.get("grantDate")),
        title=meta.get("inventionTitle"),
        events=events,
    )


class Client:
    def __init__(self, api_key: str | None = None, base_url: str = BASE_URL,
                 pause: float = 0.25, retries: int = 4) -> None:
        self.api_key = api_key or os.environ.get("USPTO_API_KEY")
        if not self.api_key:
            raise ApiError("USPTO_API_KEY is not set. Get a free key at https://data.uspto.gov/myodp")
        self.base_url = base_url
        self.pause = pause
        self.retries = retries

    def _get(self, params: dict[str, Any], url: str | None = None) -> dict[str, Any]:
        url = f"{url or self.base_url}?{urllib.parse.urlencode(params)}" if params else (url or self.base_url)
        req = urllib.request.Request(url, headers={"X-API-KEY": self.api_key, "Accept": "application/json"})
        delay = 2.0
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code == 404:  # ODP answers 404 when a query has no hits
                    return {}
                if e.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise ApiError(f"{e.code} {e.reason}: {e.read()[:300]!r}") from e
            except urllib.error.URLError:
                if attempt < self.retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
        raise ApiError("unreachable")

    def search(self, query: str, limit: int | None = None) -> Iterator[Application]:
        offset = 0
        seen = 0
        while True:
            data = self._get({"q": query, "offset": offset, "limit": PAGE_SIZE})
            bag = data.get("patentFileWrapperDataBag") or []
            for rec in bag:
                if (app := parse_record(rec)) is not None:
                    yield app
                    seen += 1
                    if limit and seen >= limit:
                        return
            total = data.get("count") or 0
            offset += len(bag)
            if not bag or offset >= total:
                return
            time.sleep(self.pause)

    def by_examiner(self, name: str, limit: int | None = None) -> Iterator[Application]:
        return self.search(f'applicationMetaData.examinerNameText:"{name}"', limit)

    # -- single-application endpoints ------------------------------------- #

    def application_raw(self, app_no: str) -> dict[str, Any] | None:
        data = self._get({}, f"{API_ROOT}/patent/applications/{app_no}")
        bag = data.get("patentFileWrapperDataBag") or []
        return bag[0] if bag else None

    def find_raw(self, field: str, value: str) -> dict[str, Any] | None:
        data = self._get({"q": f'applicationMetaData.{field}:"{value}"', "limit": 1})
        bag = data.get("patentFileWrapperDataBag") or []
        return bag[0] if bag else None

    def documents(self, app_no: str) -> list[dict[str, Any]]:
        data = self._get({}, f"{API_ROOT}/patent/applications/{app_no}/documents")
        return data.get("documentBag") or []

    def assignments(self, app_no: str) -> list[dict[str, Any]]:
        data = self._get({}, f"{API_ROOT}/patent/applications/{app_no}/assignment")
        bag = data.get("patentFileWrapperDataBag") or []
        return (bag[0].get("assignmentBag") or []) if bag else []

    def download(self, url: str) -> bytes:
        """Fetch a document download URL taken from a ``documentBag`` entry."""
        req = urllib.request.Request(url, headers={"X-API-KEY": self.api_key})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()

    def by_art_unit(self, art_unit: str, limit: int | None = None) -> Iterator[Application]:
        return self.search(f"applicationMetaData.groupArtUnitNumber:{art_unit}", limit)


def fetch_patent_pdf(number: str) -> bytes:
    """Download the scanned PDF of a granted patent or pre-grant publication."""
    req = urllib.request.Request(PATENT_PDF_URL.format(number=number), headers={"User-Agent": "bumper/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        if "pdf" not in (resp.headers.get("Content-Type") or ""):
            raise ApiError(f"no PDF available for {number}")
        return resp.read()


def read_bulk(paths: Iterable[Path]) -> Iterator[Application]:
    """Yield applications from ODP bulk JSON files (one JSON document per file)."""
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        records = data.get("patentFileWrapperDataBag", []) if isinstance(data, dict) else data
        for rec in records:
            if (app := parse_record(rec)) is not None:
                yield app
