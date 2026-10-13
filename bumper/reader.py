"""Data for the patent reader (see docs/specs/patent-reader.md).

Combines the ODP application record with the patent's full-text XML and its
scanned PDF: bibliographic table (R4), claims (R9), abstract and description
with numeral and figure labels (R7), citations, classifications and legal
events (R3), and the drawing sheets (R8).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from . import drawings, lookup

OCR_LABEL = re.compile(r"^(?:FIG\.?\s*\d+[A-Z]?|\d{1,4}[a-z]?'*)$", re.I)


def _t(el: ElementTree.Element | None) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def _date(value: str | None) -> str | None:
    if not value or not re.fullmatch(r"\d{8}", value):
        return value or None
    return f"{value[:4]}-{value[4:6]}-{value[6:]}" if value[6:] != "00" else f"{value[:4]}-{value[4:6]}"


def _doc_number(d: ElementTree.Element) -> dict:
    country = d.findtext("country") or ""
    number = d.findtext("doc-number") or ""
    kind = d.findtext("kind") or ""
    linkable = country == "US" and bool(re.fullmatch(r"(?:\d{4}/?\d{7}|(?:D|RE|PP)?\d{4,8})", number.replace(",", "")))
    clean = number.replace("/", "").replace(",", "")
    return {"country": country, "number": number, "kind": kind, "name": d.findtext("name"),
            "date": _date(d.findtext("date")),
            "link": ({"type": "pub" if len(clean) == 11 else "pat", "n": clean} if linkable else None)}


def parse_claims(root: ElementTree.Element) -> list[dict]:
    """Claims as parts (text and claim references); independent = no reference to another claim (R9)."""
    out = []
    for claim in root.iter("claim"):
        parts: list[dict] = []

        def add(t: str | None, raw: bool = False) -> None:
            if not t:
                return
            if not raw:  # XML whitespace, including line breaks, is just a space
                t = re.sub(r"\s+", " ", t)
            if parts and parts[-1]["t"] == "text":
                parts[-1]["v"] += t
            else:
                parts.append({"t": "text", "v": t})

        def walk(node: ElementTree.Element, depth: int) -> None:
            add(node.text)
            for child in node:
                if child.tag == "claim-ref":
                    parts.append({"t": "ref", "v": _t(child), "to": child.get("idref")})
                elif child.tag == "claim-text":
                    if depth:  # each nested element starts its own indented line
                        add("\n" + "    " * depth, raw=True)
                    walk(child, depth + 1)
                else:
                    walk(child, depth)
                add(child.tail)

        walk(claim, 0)
        for p in parts:
            if p["t"] == "text":
                p["v"] = re.sub(r" *\n *", lambda m: "\n", p["v"])
                p["v"] = re.sub(r"\n(?=\S)", "\n", p["v"])
        # Re-indent: a newline marker is followed by the indentation we added.
        if parts and parts[0]["t"] == "text":
            parts[0]["v"] = parts[0]["v"].lstrip()
        out.append({"id": claim.get("id"), "num": int(claim.get("num") or 0),
                    "independent": not any(p["t"] == "ref" for p in parts), "parts": parts})
    return out


def parse_xml(xml: bytes) -> dict:
    root = ElementTree.fromstring(re.sub(rb"<!DOCTYPE[^>]*>", b"", xml))
    biblio = root.find("us-bibliographic-data-grant")
    if biblio is None:
        biblio = root.find("us-bibliographic-data-application")
    pub = biblio.find("publication-reference/document-id") if biblio is not None else None
    citations, npl = [], []
    for cit in root.iter("us-citation"):
        cat = cit.findtext("category") or ""
        pc = cit.find("patcit/document-id")
        if pc is not None:
            citations.append({**_doc_number(pc), "by_examiner": "examiner" in cat})
        elif cit.find("nplcit") is not None:
            npl.append({"text": _t(cit.find("nplcit")), "by_examiner": "examiner" in cat})
    for cit in root.iter("citation"):  # older grants
        pc = cit.find("patcit/document-id")
        if pc is not None:
            citations.append({**_doc_number(pc), "by_examiner": "examiner" in (cit.findtext("category") or "")})
    cpc = []
    for c in root.iter("classification-cpc"):
        sym = f"{c.findtext('section') or ''}{c.findtext('class') or ''}{c.findtext('subclass') or ''}" \
              f"{c.findtext('main-group') or ''}/{c.findtext('subgroup') or ''}"
        if sym not in cpc:
            cpc.append(sym)
    ipc = []
    for c in root.iter("classification-ipcr"):
        sym = f"{c.findtext('section') or ''}{c.findtext('class') or ''}{c.findtext('subclass') or ''}" \
              f"{c.findtext('main-group') or ''}/{c.findtext('subgroup') or ''}"
        if sym not in ipc:
            ipc.append(sym)
    uspc = []
    nat = biblio.find("classification-national") if biblio is not None else None
    if nat is not None:
        for tag in ("main-classification", "further-classification"):
            for el in nat.findall(tag):
                v = (el.text or "").strip()
                if v:
                    uspc.append(f"{v[:3].strip()}/{v[3:].strip()}")
    related = [_doc_number(d) for d in root.iter("related-publication") for d in d.findall("document-id")]
    priority = [{"country": p.findtext("country"), "number": p.findtext("doc-number"), "date": _date(p.findtext("date"))}
                for p in root.iter("priority-claim")]
    assignees = [a.findtext(".//orgname") or " ".join(x for x in (a.findtext(".//first-name"), a.findtext(".//last-name")) if x)
                 for a in root.iter("assignee")]
    inventors = []
    for inv in list(root.iter("inventor")) or [a for a in root.iter("applicant") if a.get("app-type") == "applicant-inventor"]:
        name = " ".join(x for x in (inv.findtext(".//first-name"), inv.findtext(".//last-name")) if x)
        if name and name not in inventors:
            inventors.append(name)
    return {
        "title": (biblio.findtext("invention-title") if biblio is not None else "") or "",
        "publication": _doc_number(pub) if pub is not None else None,
        "abstract": [drawings._parts(p) for p in root.findall("abstract/p")] or
                    ([drawings._parts(root.find("abstract"))] if root.find("abstract") is not None else []),
        "claims": parse_claims(root),
        "citations": citations, "npl": npl,
        "classifications": {"cpc": cpc, "ipc": ipc, "uspc": uspc},
        "related": related, "priority": priority, "assignees": [a for a in assignees if a],
        "inventors": inventors,
        **drawings.analyze(xml),
    }


def ocr_sheet_labels(images: list[Path]) -> list[list[str]] | None:
    """Labels found on each sheet image by tesseract, or None if OCR is unavailable (R7)."""
    if not shutil.which("tesseract"):
        return None
    out = []
    for img in images:
        r = subprocess.run(["tesseract", str(img), "-", "--psm", "11"], capture_output=True, timeout=300)
        words = r.stdout.decode("utf-8", "replace").split()
        labels, i = [], 0
        while i < len(words):
            w = words[i].strip(".,;:()[]")
            if re.fullmatch(r"(?i)FIG\.?", w) and i + 1 < len(words):
                nxt = words[i + 1].strip(".,;:()[]").upper()
                if re.fullmatch(r"\d+[A-Z]?", nxt):
                    labels.append(f"FIG. {nxt}")
                    i += 2
                    continue
            m = re.fullmatch(r"(?i)FIG\.?(\d+[A-Z]?)", w)
            if m:
                labels.append(f"FIG. {m.group(1).upper()}")
            elif re.fullmatch(r"\d{1,4}[a-z]?'*", w):
                labels.append(w)
            i += 1
        out.append(sorted(set(labels)))
    return out


EMPTY_DOC = {"title": "", "publication": None, "abstract": [], "claims": [], "citations": [], "npl": [],
             "classifications": {"cpc": [], "ipc": [], "uspc": []}, "related": [], "priority": [],
             "assignees": [], "inventors": [], "sheets": 0, "figure_count": 0, "figures": [], "fig_sheet": {},
             "numerals": {}, "paragraphs": []}


class Reader:
    def __init__(self, service: lookup.Service) -> None:
        self.service = service
        self.data_dir = service.data_dir

    # -- sources ------------------------------------------------------------ #

    def _record(self, app_no: str) -> dict:
        client = self.service._client()
        if client is None:
            raise lookup.NotFound("USPTO_API_KEY is not set: the reader needs the USPTO full text")
        conn = self.service._conn()
        try:
            rec = self.service._cached(conn, f"app:{app_no}", lambda: client.application_raw(app_no))
        finally:
            conn.close()
        if not rec:
            raise lookup.NotFound(f"application {app_no} not found")
        return rec

    def _xml(self, rec: dict, prefer: str) -> tuple[bytes, str]:
        grant = (rec.get("grantDocumentMetaData") or {}).get("fileLocationURI")
        pgpub = (rec.get("pgpubDocumentMetaData") or {}).get("fileLocationURI")
        url, kind = ((grant, "pat") if grant and (prefer == "pat" or not pgpub) else (pgpub, "pub"))
        if not url:
            return b"", "pat" if (rec.get("applicationMetaData") or {}).get("patentNumber") else "pub"
        path = self.data_dir / "xml" / (url.rsplit("/", 1)[-1])
        if not path.exists():
            data = self.service._client().download(url)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return path.read_bytes(), kind

    def _sheets(self, kind: str, number: str, sheets: int) -> dict:
        """PDF pages of the drawing sheets, plus OCR labels when available (R7, R8)."""
        cache = self.data_dir / "sheets" / f"{number}.json"
        if cache.exists():
            return json.loads(cache.read_text())
        info: dict[str, Any] = {"pages": [], "labels": None}
        if sheets:
            try:
                pdf = self.service.patent_pdf(kind, number)
            except (lookup.NotFound, OSError):
                pdf = None
            if pdf:
                info["pages"] = drawings.sheet_pages(drawings.page_ink(pdf), sheets)
                if info["pages"] and shutil.which("tesseract"):
                    with tempfile.TemporaryDirectory() as tmp:
                        imgs = [self._render(pdf, p, 1600, Path(tmp)) for p in info["pages"]]
                        info["labels"] = ocr_sheet_labels(imgs)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(info))
        return info

    def _render(self, pdf: bytes, page: int, width: int, out_dir: Path) -> Path:
        src = out_dir / "in.pdf"
        if not src.exists():
            src.write_bytes(pdf)
        stem = out_dir / f"p{page}-{width}"
        subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-png", "-scale-to", str(width),
                        "-singlefile", str(src), str(stem)], check=True, capture_output=True, timeout=120)
        return stem.with_suffix(".png")

    def page_image(self, kind: str, number: str, page: int, width: int = 1000) -> bytes:
        n = lookup.normalize(kind, number)
        n = lookup.pub_digits(n) if kind == "pub" else n
        width = max(120, min(int(width), 2400))
        path = self.data_dir / "pages" / f"{n}-p{int(page)}-{width}.png"
        if not path.exists():
            if not shutil.which("pdftoppm"):
                raise lookup.NotFound("pdftoppm (poppler-utils) is needed for drawing images")
            pdf = self.service.patent_pdf(kind, n)
            with tempfile.TemporaryDirectory() as tmp:
                img = self._render(pdf, int(page), width, Path(tmp))
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(img, path)
        return path.read_bytes()

    # -- assembly ------------------------------------------------------------ #

    def read(self, kind: str, number: str) -> dict:
        app_no = self.service.resolve(kind, number)
        rec = self._record(app_no)
        b = lookup.biblio_from_record(rec)
        xml, text_kind = self._xml(rec, "pub" if kind == "pub" else "pat")
        doc = parse_xml(xml) if xml else EMPTY_DOC
        if text_kind == "pat" and b.get("patent_number"):
            pdf_kind, pdf_n = "pat", b["patent_number"]
        elif b.get("earliest_publication_number"):
            pdf_kind, pdf_n = "pub", lookup.pub_digits(lookup.normalize("pub", b["earliest_publication_number"]))
        else:
            raise lookup.NotFound(f"application {app_no} has not been published")
        sheets = self._sheets(pdf_kind, pdf_n, doc["sheets"])
        pdf_pages = self._page_count(pdf_kind, pdf_n)
        pages = sheets["pages"]
        # label -> sheet numbers (1-based), from OCR when available, else from the text analysis.
        labels: dict[str, list[int]] = defaultdict(list)
        source = "text"
        if sheets.get("labels"):
            source = "ocr"
            for i, found in enumerate(sheets["labels"], 1):
                for label in found:
                    labels[label.upper()].append(i)
        else:
            for fig, sheet in doc["fig_sheet"].items():
                labels[f"FIG. {fig}"].append(sheet)
            for num, info in doc["numerals"].items():
                seen = []
                for fig in info["figs"]:
                    s = doc["fig_sheet"].get(fig)
                    if s and s not in seen:
                        seen.append(s)
                if seen:
                    labels[num.upper()] = seen
        cont = rec.get("childContinuityBag") or []
        parents = rec.get("parentContinuityBag") or []
        return {
            "number": {"type": pdf_kind, "n": pdf_n, "kind": (doc["publication"] or {}).get("kind")},
            "title": doc["title"] or b.get("title"),
            "biblio": {
                "publication_number": f"US{pdf_n}{(doc['publication'] or {}).get('kind') or ''}",
                "publication_type": "Grant" if pdf_kind == "pat" else "Application publication",
                "application_number": b.get("application_number"),
                "publication_date": (doc["publication"] or {}).get("date") or (b.get("issue_date") if pdf_kind == "pat"
                                                                              else b.get("earliest_publication_date")),
                "filing_date": b.get("filing_date"),
                "priority_date": min([p["date"] for p in doc["priority"] if p.get("date")] + [b.get("filing_date") or "9999"]),
                "status": b.get("status"),
                "inventors": doc["inventors"] or [i["name"] for i in b.get("inventors") or []],
                "assignees": doc["assignees"] or [a for a in b.get("applicants") or [] if a],
                "examiner": b.get("examiner"), "art_unit": b.get("art_unit"),
                "related": [r for r in doc["related"] if r.get("number")] +
                           [{"country": "US", "number": c.get("childPatentNumber") or c.get("childApplicationNumberText"),
                             "kind": c.get("claimParentageTypeCodeDescriptionText"),
                             "link": {"type": "pat", "n": c["childPatentNumber"]} if c.get("childPatentNumber") else
                             {"type": "app", "n": c.get("childApplicationNumberText")}} for c in cont] +
                           [{"country": "US", "number": p.get("parentPatentNumber") or p.get("parentApplicationNumberText"),
                             "kind": p.get("claimParentageTypeCodeDescriptionText"),
                             "link": {"type": "pat", "n": p["parentPatentNumber"]} if p.get("parentPatentNumber") else
                             {"type": "app", "n": p.get("parentApplicationNumberText")}} for p in parents],
                "priority": doc["priority"],
            },
            "abstract": doc["abstract"],
            "claims": doc["claims"],
            "description": doc["paragraphs"],
            "citations": doc["citations"], "npl": doc["npl"],
            "classifications": doc["classifications"],
            "legal_events": b.get("transactions") or [],
            "drawings": {"sheets": doc["sheets"], "pages": pages, "labels": labels, "source": source,
                         "image": f"/api/patent/page?type={pdf_kind}&n={pdf_n}", "pdf_pages": pdf_pages},
            "full_text": bool(xml),
        }

    def _page_count(self, kind: str, number: str) -> int:
        try:
            pdf = self.service.patent_pdf(kind, number)
        except (lookup.NotFound, OSError):
            return 0
        return len(re.findall(rb"/Type\s*/Page[^s]", pdf))

    def search(self, query: str, page: int = 1, per_page: int = 8) -> dict:
        """Patent search for the reader (R11): ODP query, eight results per page, at most eight pages."""
        client = self.service._client()
        if client is None:
            raise lookup.NotFound("USPTO_API_KEY is not set: search needs the USPTO API")
        page = max(1, min(int(page), 8))
        q = query.strip()
        if not re.search(r"\w+\.\w+:", q):  # plain words: search titles and abstracts-like fields
            words = " AND ".join(w for w in re.findall(r'"[^"]+"|\S+', q))
            q = f"applicationMetaData.inventionTitle:({words}) OR applicationMetaData.firstApplicantName:({words})"
        data = client._get({"q": q, "offset": (page - 1) * per_page, "limit": per_page,
                            "sort": "applicationMetaData.filingDate desc"})
        results = []
        for rec in data.get("patentFileWrapperDataBag") or []:
            b = lookup.biblio_from_record(rec)
            pn = b.get("patent_number")
            pub = b.get("earliest_publication_number")
            link = ({"type": "pat", "n": pn} if pn else
                    {"type": "pub", "n": lookup.pub_digits(lookup.normalize("pub", pub))} if pub else None)
            results.append({"title": b.get("title"), "application_number": b.get("application_number"),
                            "patent_number": pn, "publication_number": pub, "filing_date": b.get("filing_date"),
                            "status": b.get("status"), "applicant": (b.get("applicants") or [None])[0],
                            "link": link})
        total = int(data.get("count") or 0)
        return {"query": query, "page": page, "per_page": per_page, "total": total,
                "pages": min(8, -(-total // per_page)), "results": results}

    def citation(self, kind: str, number: str, fmt: str) -> tuple[str, str, str]:
        """Citation export (R4): BibTeX, RIS or EndNote."""
        d = self.read(kind, number)
        b, n = d["biblio"], d["number"]
        year = (b.get("publication_date") or "")[:4]
        authors = b.get("inventors") or []
        label = f"US{n['n']}"
        if fmt == "bibtex":
            body = "@misc{%s,\n  title = {%s},\n  author = {%s},\n  howpublished = {U.S. %s %s},\n  year = {%s},\n" \
                   "  note = {Application %s, filed %s; assignee: %s}\n}\n" % (
                       label, d["title"], " and ".join(authors), "Patent" if n["type"] == "pat" else "Patent Application Publication",
                       n["n"], year, b.get("application_number"), b.get("filing_date"), "; ".join(b.get("assignees") or []))
            return body, "application/x-bibtex", f"{label}.bib"
        lines = (["TY  - PAT", f"TI  - {d['title']}"] + [f"AU  - {a}" for a in authors] +
                 [f"PY  - {year}", f"DA  - {b.get('publication_date') or ''}", f"M1  - {label}",
                  f"PB  - {'; '.join(b.get('assignees') or [])}", "ER  - "])
        if fmt == "enw":
            lines = (["%0 Patent", f"%T {d['title']}"] + [f"%A {a}" for a in authors] +
                     [f"%D {year}", f"%@ {label}", f"%I {'; '.join(b.get('assignees') or [])}"])
            return "\n".join(lines) + "\n", "application/x-endnote-refer", f"{label}.enw"
        return "\n".join(lines) + "\n", "application/x-research-info-systems", f"{label}.ris"
