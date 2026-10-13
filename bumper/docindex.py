"""Build the document search index from USPTO file wrappers and local files."""

from __future__ import annotations

import hashlib
import random
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from . import doccodes, search, textextract

SUBSTANTIVE = {c for c, (_, _, s) in doccodes.CODES.items() if s}
# Rendition preference when the USPTO offers several for one document.
MIME_ORDER = ["XML", "MS_WORD", "PDF"]


def _day(value: Any) -> str | None:
    return str(value)[:10] if value else None


def _options(doc: dict) -> dict[str, dict]:
    return {(o.get("mimeTypeIdentifier") or "").upper(): o for o in doc.get("downloadOptionBag") or []}


def _signature(text: str) -> tuple[str | None, str | None]:
    """Best-effort signer name and registration number from an applicant filing."""
    names = re.findall(r"/\s*([A-Z][A-Za-z.'\- ]{2,60}?)\s*/", text[-4000:])
    reg = re.search(r"Reg(?:istration)?\.?\s*No\.?:?\s*([\d,]{5,7})", text[-4000:], re.I)
    return (names[-1].strip() if names else None), (reg.group(1).replace(",", "") if reg else None)


def store_file_history(conn: sqlite3.Connection, app_no: str, docs: list[dict]) -> None:
    conn.execute("DELETE FROM file_docs WHERE app_no = ?", (app_no,))
    conn.executemany(
        "INSERT OR REPLACE INTO file_docs VALUES (?,?,?,?,?)",
        [(app_no, d.get("documentIdentifier"), d.get("documentCode"), _day(d.get("officialDate")),
          doccodes.direction(d.get("documentCode") or "", d.get("directionCategory")))
         for d in docs if d.get("documentIdentifier")])


def index_application(client, conn: sqlite3.Connection, app_no: str, pdf_dir: Path,
                      codes: set[str] | None = None, kb: str = "ex_parte") -> int:
    """Download and index one application's documents. Returns documents indexed."""
    search.ensure_schema(conn)
    codes = codes or SUBSTANTIVE
    raw = client.application_raw(app_no) or {}
    meta = raw.get("applicationMetaData") or {}
    corr = (raw.get("correspondenceAddressBag") or [{}])[0]
    docs = client.documents(app_no)
    store_file_history(conn, app_no, docs)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for d in docs:
        code = d.get("documentCode") or ""
        doc_id = d.get("documentIdentifier")
        if code not in codes or not doc_id:
            continue
        opts = _options(d)
        text, pdf_path, pages = "", None, None
        for mime in MIME_ORDER:
            if mime in opts and opts[mime].get("downloadUrl"):
                data = client.download(opts[mime]["downloadUrl"])
                if mime == "PDF":
                    pdf_path = pdf_dir / f"{doc_id}.pdf"
                    pdf_path.write_bytes(data)
                    pages = opts[mime].get("pageTotalQuantity")
                text = textextract.extract(data, mime)
                if text:
                    break
        if "PDF" in opts and pdf_path is None:
            pages = opts["PDF"].get("pageTotalQuantity")
        direction = doccodes.direction(code, d.get("directionCategory"))
        filer, reg = _signature(text) if direction == doccodes.INCOMING else (None, None)
        search.upsert_document(conn, {
            "doc_id": doc_id, "kb": kb, "app_no": app_no, "doc_code": code,
            "doc_desc": d.get("documentCodeDescriptionText") or doccodes.label(code),
            "direction": direction, "mail_date": _day(d.get("officialDate")),
            "examiner": meta.get("examinerNameText"), "art_unit": meta.get("groupArtUnitNumber"),
            "customer_number": str(meta.get("customerNumber") or "") or None,
            "correspondent": corr.get("nameLineOneText"),
            "filer": filer, "filer_reg": reg, "pages": pages,
            "pdf_url": (opts.get("PDF") or {}).get("downloadUrl"),
            "pdf_path": str(pdf_path) if pdf_path else None, "text": text,
        })
        count += 1
    search.trace_actions(conn, app_no, SUBSTANTIVE)
    conn.commit()
    return count


def sample_applications(conn: sqlite3.Connection, n: int, seed: int | None = None,
                        examiner: str | None = None, art_unit: str | None = None) -> list[str]:
    """A random selection of application numbers already in the statistics database."""
    where, params = [], []
    if examiner:
        where.append("examiner = ?")
        params.append(examiner.upper())
    if art_unit:
        where.append("art_unit = ?")
        params.append(art_unit)
    rows = [r[0] for r in conn.execute(
        f"SELECT app_no FROM applications {'WHERE ' + ' AND '.join(where) if where else ''}", params)]
    random.Random(seed).shuffle(rows)
    return rows[:n]


# --------------------------------------------------------------------------- #
# Local files: a private knowledge base of a firm's own documents
# --------------------------------------------------------------------------- #

GUESSES = [
    (r"this action is made final|final rejection", "CTFR"),
    (r"notice of allowan|reasons for allowance", "NOA"),
    (r"restriction (is|requirement)|election of species", "CTRS"),
    (r"ex parte quayle", "CTEQ"),
    (r"advisory action", "CTAV"),
    (r"examiner'?s answer", "APEA"),
    (r"appeal brief|brief on appeal", "AP.B"),
    (r"request for continued examination", "RCEX"),
    (r"non-?final|detailed action|claim rejections", "CTNF"),
    (r"remarks|amendments? to the claims|response to (the )?office action", "A..."),
]
APP_NO = re.compile(r"\b(\d{2})/(\d{3}),(\d{3})\b|\bApplication No\.?:?\s*(\d{8})\b", re.I)


def guess_code(text: str) -> str:
    head = text[:6000].lower()
    for pattern, code in GUESSES:
        if re.search(pattern, head):
            return code
    return "LET."


def index_files(conn: sqlite3.Connection, paths: Iterable[Path], kb: str = "firm") -> int:
    search.ensure_schema(conn)
    count = 0
    for path in paths:
        data = path.read_bytes()
        text = textextract.extract(data, name=path.name)
        m = APP_NO.search(text) or APP_NO.search(path.name)
        app_no = (m.group(1) + m.group(2) + m.group(3) if m and m.group(1) else (m.group(4) if m else None))
        code = guess_code(text)
        dates = re.findall(r"\b(20\d\d|19\d\d)-(\d\d)-(\d\d)\b", text[:3000])
        filer, reg = _signature(text)
        search.upsert_document(conn, {
            "doc_id": f"{kb}:{hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:16]}",
            "kb": kb, "app_no": app_no, "doc_code": code, "doc_desc": f"{doccodes.label(code)} ({path.name})",
            "direction": doccodes.direction(code), "mail_date": "-".join(dates[0]) if dates else None,
            "filer": filer, "filer_reg": reg,
            "pdf_path": str(path.resolve()) if path.suffix.lower() == ".pdf" else None, "text": text,
        })
        count += 1
    conn.commit()
    return count


# --------------------------------------------------------------------------- #
# PTAB trials (IPR, PGR, CBM): the "inter partes" knowledge base
# --------------------------------------------------------------------------- #

def _first_list_of_dicts(data: Any) -> list[dict]:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data
    if isinstance(data, dict):
        for v in data.values():
            found = _first_list_of_dicts(v)
            if found:
                return found
    return []


def _find(rec: dict, *needles: str) -> Any:
    for key, value in rec.items():
        k = key.lower()
        if any(n in k for n in needles) and not isinstance(value, (dict, list)):
            return value
    for value in rec.values():
        if isinstance(value, dict) and (hit := _find(value, *needles)) is not None:
            return hit
    return None


def index_ptab(client, conn: sqlite3.Connection, query: str, pdf_dir: Path, limit: int = 200) -> int:
    """Index PTAB trial documents matching an ODP query (e.g. a trial number or patent owner).

    The ODP PTAB endpoints were added in 2025; field names are matched loosely
    so small schema differences do not break ingestion.
    """
    search.ensure_schema(conn)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    data = client._get({"q": query, "limit": min(limit, 100)},
                       f"{client.base_url.rsplit('/patent/', 1)[0]}/patent/trials/documents/search")
    count = 0
    for rec in _first_list_of_dicts(data)[:limit]:
        doc_id = _find(rec, "documentidentifier", "documentid")
        url = _find(rec, "downloaduri", "downloadurl", "fileuri")
        if not doc_id:
            continue
        text, pdf_path = "", None
        if url:
            blob = client.download(url)
            if blob[:5] == b"%PDF-":
                pdf_path = pdf_dir / f"ptab-{doc_id}.pdf"
                pdf_path.write_bytes(blob)
            text = textextract.extract(blob)
        search.upsert_document(conn, {
            "doc_id": f"ptab:{doc_id}", "kb": "inter_partes",
            "app_no": _find(rec, "trialnumber", "proceedingnumber"),
            "doc_code": str(_find(rec, "documenttypename", "documenttype", "documentcategory") or "PTAB"),
            "doc_desc": _find(rec, "documenttitle", "documentname") or "PTAB document",
            "direction": "", "mail_date": _day(_find(rec, "filingdate", "documentdate")),
            "correspondent": _find(rec, "patentownername", "respondentpartyname"),
            "filer": _find(rec, "filingpartycategory", "filingparty"),
            "pdf_url": url, "pdf_path": str(pdf_path) if pdf_path else None, "text": text,
        })
        count += 1
    conn.commit()
    return count
