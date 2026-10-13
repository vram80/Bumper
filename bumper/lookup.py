"""Look up one application, patent or publication and assemble everything about it."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import db, doccodes, epo, fulltext, search, textextract, uspto

CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS odp_cache (
    key       TEXT PRIMARY KEY,
    json      TEXT NOT NULL,
    fetched   REAL NOT NULL
);
"""
CACHE_TTL = 24 * 3600


class NotFound(LookupError):
    pass


def normalize(kind: str, number: str) -> str:
    """Canonical number for a lookup type ('app', 'pat' or 'pub')."""
    s = number.strip().upper()
    if kind == "app":
        s = re.sub(r"^US", "", s)
        return re.sub(r"[^0-9]", "", s) if not re.match(r"^PCT", s) else s.replace(" ", "")
    if kind == "pat":
        s = re.sub(r"^US", "", s).replace(" ", "")
        s = re.sub(r"(B\d|E|S|P\d?)$", "", s)
        s = re.sub(r"[^0-9A-Z]", "", s)
        prefix = re.match(r"^(RE|PP|D|H|T)", s)
        return (prefix.group(1) + s[len(prefix.group(1)):].lstrip("0")) if prefix else s.lstrip("0")
    if kind == "pub":
        s = re.sub(r"^US", "", s).replace(" ", "")
        s = re.sub(r"A\d$", "", s)
        digits = re.sub(r"[^0-9]", "", s)
        # 2020/123456 (old 6-digit serial form) -> 20200123456
        if len(digits) == 10:
            digits = digits[:4] + "0" + digits[4:]
        return digits
    raise ValueError(f"unknown lookup type {kind!r}")


def _pick(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return default


def _day(value: Any) -> str | None:
    return str(value)[:10] if value else None


def biblio_from_record(rec: dict) -> dict:
    """Flatten an ODP file-wrapper record into the fields the lookup page shows."""
    meta = rec.get("applicationMetaData") or {}
    entity = meta.get("entityStatusData") or {}
    corr = (rec.get("correspondenceAddressBag") or [{}])[0]
    cls = _pick(meta, "uspcSymbolText") or "/".join(x for x in (meta.get("class"), meta.get("subclass")) if x)
    inventors = []
    for inv in meta.get("inventorBag") or []:
        addr = (inv.get("correspondenceAddressBag") or [{}])[0]
        name = _pick(inv, "inventorNameText") or " ".join(
            x for x in (inv.get("firstName"), inv.get("middleName"), inv.get("lastName")) if x)
        place = ", ".join(x for x in (addr.get("cityName"), addr.get("geographicRegionCode"),
                                      addr.get("countryCode")) if x)
        inventors.append({"name": name, "location": place})
    aia = meta.get("firstInventorToFileIndicator")
    return {
        "application_number": rec.get("applicationNumberText"),
        "title": meta.get("inventionTitle"),
        "filing_date": _day(meta.get("filingDate")),
        "effective_filing_date": _day(meta.get("effectiveFilingDate")),
        "application_type": _pick(meta, "applicationTypeLabelName", "applicationTypeCategory"),
        "status": meta.get("applicationStatusDescriptionText"),
        "status_date": _day(meta.get("applicationStatusDate")),
        "examiner": meta.get("examinerNameText"),
        "art_unit": meta.get("groupArtUnitNumber"),
        "customer_number": _pick(meta, "customerNumber"),
        "attorney_docket": _pick(meta, "docketNumber"),
        "class_subclass": cls or None,
        "cpc": meta.get("cpcClassificationBag") or [],
        "entity_status": _pick(entity, "businessEntityStatusCategory"),
        "aia": {"Y": True, "N": False, True: True, False: False}.get(aia),
        "earliest_publication_number": meta.get("earliestPublicationNumber"),
        "earliest_publication_date": _day(meta.get("earliestPublicationDate")),
        "patent_number": meta.get("patentNumber"),
        "issue_date": _day(meta.get("grantDate")),
        "correspondent": corr.get("nameLineOneText"),
        "applicants": [_pick(a, "applicantNameText") for a in meta.get("applicantBag") or [] if a],
        "inventors": inventors,
        "last_updated": _day(rec.get("lastIngestionDateTime")),
        "transactions": [
            {"date": _day(e.get("eventDate")), "code": e.get("eventCode"), "description": e.get("eventDescriptionText")}
            for e in sorted(rec.get("eventDataBag") or [], key=lambda e: e.get("eventDate") or "", reverse=True)
        ],
    }


def documents_from_bag(bag: list[dict]) -> list[dict]:
    out = []
    for d in sorted(bag, key=lambda d: (d.get("officialDate") or "", d.get("documentIdentifier") or ""), reverse=True):
        opts = {(o.get("mimeTypeIdentifier") or "").upper(): o for o in d.get("downloadOptionBag") or []}
        code = d.get("documentCode") or ""
        out.append({
            "doc_id": d.get("documentIdentifier"),
            "date": _day(d.get("officialDate")),
            "code": code,
            "description": d.get("documentCodeDescriptionText") or doccodes.label(code),
            "direction": doccodes.direction(code, d.get("directionCategory")),
            "pages": (opts.get("PDF") or {}).get("pageTotalQuantity"),
            "formats": sorted(opts),
        })
    return out


def assignments_from_bag(bag: list[dict]) -> list[dict]:
    out = []
    for a in bag:
        out.append({
            "reel_frame": _pick(a, "reelAndFrameNumber") or "/".join(
                str(x) for x in (a.get("reelNumber"), a.get("frameNumber")) if x),
            "recorded": _day(a.get("assignmentRecordedDate")),
            "conveyance": a.get("conveyanceText"),
            "assignors": [{"name": x.get("assignorName"), "executed": _day(x.get("executionDate"))}
                          for x in a.get("assignorBag") or []],
            "assignees": [x.get("assigneeNameText") for x in a.get("assigneeBag") or []],
        })
    return out


class Service:
    def __init__(self, db_path: str, data_dir: str = "data") -> None:
        self.db_path = db_path
        self.data_dir = Path(data_dir)

    # -- plumbing ---------------------------------------------------------- #

    def _conn(self) -> sqlite3.Connection:
        conn = db.connect(self.db_path)
        conn.executescript(CACHE_SCHEMA)
        search.ensure_schema(conn)
        fulltext.ensure_schema(conn)
        return conn

    def _client(self) -> uspto.Client | None:
        try:
            return uspto.Client()
        except uspto.ApiError:
            return None

    def _epo(self) -> epo.Client | None:
        try:
            return epo.Client()
        except epo.OpsError:
            return None

    def _cached(self, conn: sqlite3.Connection, key: str, fetch) -> Any:
        row = conn.execute("SELECT json, fetched FROM odp_cache WHERE key = ?", (key,)).fetchone()
        if row and time.time() - row[1] < CACHE_TTL:
            return json.loads(row[0])
        value = fetch()
        conn.execute("INSERT OR REPLACE INTO odp_cache VALUES (?,?,?)", (key, json.dumps(value), time.time()))
        conn.commit()
        return value

    # -- lookup ------------------------------------------------------------ #

    def resolve(self, kind: str, number: str) -> str:
        """Application number for a patent, publication or application number."""
        n = normalize(kind, number)
        if kind == "app":
            return n
        conn = self._conn()
        try:
            col = "patent_number" if kind == "pat" else None
            if col:
                row = conn.execute("SELECT app_no FROM applications WHERE patent_number = ?", (n,)).fetchone()
                if row:
                    return row[0]
            row = conn.execute("SELECT app_no FROM patent_text WHERE number = ?", (n,)).fetchone()
            if row and row[0]:
                return row[0]
            client = self._client()
            if client is None:
                raise NotFound(f"{n} is not in the local database and USPTO_API_KEY is not set")
            field = "patentNumber" if kind == "pat" else "earliestPublicationNumber"
            value = n if kind == "pat" else f"US{n}A1"
            rec = self._cached(conn, f"find:{field}:{value}", lambda: client.find_raw(field, value))
            if not rec and kind == "pub":
                rec = self._cached(conn, f"find:{field}:US{n}", lambda: client.find_raw(field, f"US{n}"))
            if not rec:
                raise NotFound(f"no application found for {kind} {n}")
            return rec["applicationNumberText"]
        finally:
            conn.close()

    def lookup(self, kind: str, number: str) -> dict:
        app_no = self.resolve(kind, number)
        conn = self._conn()
        try:
            client = self._client()
            result: dict[str, Any] = {"query": {"type": kind, "number": normalize(kind, number)},
                                      "source": "uspto" if client else "local", "warnings": []}
            if client:
                rec = self._cached(conn, f"app:{app_no}", lambda: client.application_raw(app_no))
                if not rec:
                    raise NotFound(f"application {app_no} not found")
                result["biblio"] = biblio_from_record(rec)
                result["documents"] = documents_from_bag(
                    self._cached(conn, f"docs:{app_no}", lambda: client.documents(app_no)))
                try:
                    result["assignments"] = assignments_from_bag(
                        self._cached(conn, f"assign:{app_no}", lambda: client.assignments(app_no)))
                except uspto.ApiError as e:
                    result["assignments"] = []
                    result["warnings"].append(f"assignments unavailable: {e}")
            else:
                result.update(self._local(conn, app_no))
                result["warnings"].append("USPTO_API_KEY not set: showing locally stored data only")
            b = result["biblio"]
            result["links"] = {
                "patent_pdf": f"/api/patent/pdf?type=pat&n={b['patent_number']}" if b.get("patent_number") else None,
                "publication_pdf": (f"/api/patent/pdf?type=pub&n={normalize('pub', b['earliest_publication_number'])}"
                                    if b.get("earliest_publication_number") else None),
            }
            result["family"] = self._family(conn, b, result["warnings"])
            return result
        finally:
            conn.close()

    def _local(self, conn: sqlite3.Connection, app_no: str) -> dict:
        apps = db._load(conn, "a.app_no = ?", (app_no,))
        docs = conn.execute("SELECT doc_id, mail_date, doc_code, doc_desc, direction, pages FROM documents "
                            "WHERE app_no = ? ORDER BY mail_date DESC", (app_no,)).fetchall()
        if not apps and not docs:
            raise NotFound(f"application {app_no} is not in the local database")
        a = apps[0] if apps else None
        biblio = {
            "application_number": app_no, "title": a.title if a else None,
            "filing_date": a.filing_date.isoformat() if a and a.filing_date else None,
            "status": a.status_text if a else None,
            "status_date": a.status_date.isoformat() if a and a.status_date else None,
            "examiner": a.examiner if a else None, "art_unit": a.art_unit if a else None,
            "patent_number": a.patent_number if a else None,
            "issue_date": a.grant_date.isoformat() if a and a.grant_date else None,
            "inventors": [],
            "transactions": [{"date": e.date.isoformat(), "code": e.code, "description": e.description}
                             for e in sorted(a.events, key=lambda e: e.date, reverse=True)] if a else [],
        }
        return {
            "biblio": biblio,
            "documents": [{"doc_id": d[0], "date": d[1], "code": d[2], "description": d[3], "direction": d[4],
                           "pages": d[5], "formats": ["TEXT"], "indexed": True} for d in docs],
            "assignments": [],
        }

    def _family(self, conn: sqlite3.Connection, biblio: dict, warnings: list[str]) -> list[dict]:
        number = biblio.get("patent_number") or biblio.get("earliest_publication_number")
        if not number:
            return []
        client = self._epo()
        if client is None:
            warnings.append("EPO_OPS_KEY not set: patent family unavailable")
            return []
        try:
            return self._cached(conn, f"family:{number}", lambda: client.family(number))
        except (epo.OpsError, OSError) as e:
            warnings.append(f"patent family unavailable: {e}")
            return []

    # -- files ------------------------------------------------------------- #

    def patent_pdf(self, kind: str, number: str) -> bytes:
        n = normalize(kind, number)
        path = self.data_dir / "patents" / f"{n}.pdf"
        if path.exists():
            return path.read_bytes()
        try:
            data = uspto.fetch_patent_pdf(n)
        except (uspto.ApiError, OSError):
            client = self._epo()
            if client is None:
                raise NotFound(f"no PDF for {n} from the USPTO, and EPO OPS is not configured")
            data = client.pdf(n)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return data

    def patent_text(self, kind: str, number: str) -> dict:
        n = normalize(kind, number)
        conn = self._conn()
        try:
            hit = fulltext.get(conn, n)
        finally:
            conn.close()
        if hit:
            return {"source": "uspto_fulltext", **hit}
        text = textextract.pdf_text(self.patent_pdf(kind, n))
        if not text:
            return {"source": "none", "number": n, "description": "",
                    "note": "The USPTO PDF is a scan without a text layer. Load the weekly full-text files "
                            "(bumper fulltext load) or install tesseract for OCR."}
        return {"source": "pdf", "number": n, "description": text}

    def document_pdf(self, app_no: str, doc_id: str) -> bytes:
        conn = self._conn()
        try:
            row = conn.execute("SELECT pdf_path FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
            if row and row[0] and Path(row[0]).exists():
                return Path(row[0]).read_bytes()
            path = self.data_dir / "pdfs" / f"{doc_id}.pdf"
            if path.exists():
                return path.read_bytes()
            client = self._client()
            if client is None:
                raise NotFound("document not stored locally and USPTO_API_KEY is not set")
            bag = self._cached(conn, f"docs:{app_no}", lambda: client.documents(app_no))
        finally:
            conn.close()
        doc = next((d for d in bag if d.get("documentIdentifier") == doc_id), None)
        pdf = next((o for o in (doc or {}).get("downloadOptionBag") or []
                    if (o.get("mimeTypeIdentifier") or "").upper() == "PDF"), None)
        if not pdf:
            raise NotFound(f"no PDF for document {doc_id}")
        data = client.download(pdf["downloadUrl"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return data
