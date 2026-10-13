"""Patent and publication full text from the USPTO weekly full-text XML files.

The USPTO publishes every granted patent (``ipgYYMMDD.zip``) and pre-grant
publication (``ipaYYMMDD.zip``) as weekly XML files. They are listed on the
Open Data Portal ("Patent Grant Full-Text Data" and "Patent Application
Full-Text Data"). Each file is many XML documents concatenated together.
Loading them gives searchable text without OCR of the scanned PDFs.
"""

from __future__ import annotations

import io
import re
import sqlite3
import zipfile
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree

SCHEMA = """
CREATE TABLE IF NOT EXISTS patent_text (
    number      TEXT PRIMARY KEY,   -- patent number or 11-digit publication number
    kind        TEXT,
    app_no      TEXT,
    pub_date    TEXT,
    title       TEXT,
    abstract    TEXT,
    claims      TEXT,
    description TEXT
);
CREATE INDEX IF NOT EXISTS ix_patent_text_app ON patent_text(app_no);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _text(el: ElementTree.Element | None) -> str:
    if el is None:
        return ""
    return re.sub(r"[ \t]+", " ", "".join(el.itertext())).strip()


def _paragraphs(el: ElementTree.Element | None, tag: str) -> str:
    if el is None:
        return ""
    return "\n\n".join(t for t in (_text(p) for p in el.iter(tag)) if t)


def _first(root: ElementTree.Element, *paths: str) -> ElementTree.Element | None:
    for path in paths:
        el = root.find(path)
        if el is not None:
            return el
    return None


def normalize_number(number: str) -> str:
    """'US 10,000,000 B2' -> '10000000'; 'US 2020/0123456 A1' -> '20200123456'."""
    n = re.sub(r"^US", "", number.strip().upper())
    n = re.sub(r"[A-Z]\d?$", "", n.replace(" ", ""))
    n = re.sub(r"[^0-9A-Z]", "", n)
    return n.lstrip("0") if n.isdigit() and len(n) < 11 else n


def parse_document(xml: bytes) -> dict | None:
    # Drop the DOCTYPE so the parser does not try to resolve the external DTD.
    xml = re.sub(rb"<!DOCTYPE[^>]*>", b"", xml)
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None
    if root.tag not in ("us-patent-grant", "us-patent-application"):
        return None
    biblio = _first(root, "us-bibliographic-data-grant", "us-bibliographic-data-application")
    pub = biblio.find("publication-reference/document-id") if biblio is not None else None
    app = root.find(".//application-reference/document-id")
    if pub is None:
        return None
    claims = root.find("claims")
    return {
        "number": normalize_number(_text(pub.find("doc-number"))),
        "kind": _text(pub.find("kind")),
        "app_no": _text(app.find("doc-number")) if app is not None else None,
        "pub_date": _text(pub.find("date")),
        "title": _text(biblio.find("invention-title")) if biblio is not None else "",
        "abstract": _paragraphs(root.find("abstract"), "p"),
        "claims": "\n\n".join(_text(c) for c in claims.iter("claim")) if claims is not None else "",
        "description": _paragraphs(root.find("description"), "p"),
    }


def split_documents(stream: io.BufferedIOBase) -> Iterator[bytes]:
    buf: list[bytes] = []
    for line in stream:
        if line.startswith(b"<?xml") and buf:
            yield b"".join(buf)
            buf = []
        buf.append(line)
    if buf:
        yield b"".join(buf)


def load(conn: sqlite3.Connection, path: Path) -> int:
    """Load one weekly file (.zip or .xml). Returns the number of documents stored."""
    ensure_schema(conn)

    def streams() -> Iterator[io.BufferedIOBase]:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():
                    if name.lower().endswith(".xml"):
                        with z.open(name) as fh:
                            yield fh
        else:
            with open(path, "rb") as fh:
                yield fh

    count = 0
    for stream in streams():
        for chunk in split_documents(stream):
            doc = parse_document(chunk)
            if doc and doc["number"]:
                conn.execute("INSERT OR REPLACE INTO patent_text VALUES (:number,:kind,:app_no,:pub_date,"
                             ":title,:abstract,:claims,:description)", doc)
                count += 1
    conn.commit()
    return count


def get(conn: sqlite3.Connection, number: str) -> dict | None:
    ensure_schema(conn)
    row = conn.execute("SELECT number, kind, app_no, pub_date, title, abstract, claims, description "
                       "FROM patent_text WHERE number = ?", (normalize_number(number),)).fetchone()
    if row is None:
        return None
    return dict(zip(["number", "kind", "app_no", "pub_date", "title", "abstract", "claims", "description"], row))
