"""Turn downloaded documents into plain text, and plain text into .docx.

Order of preference for a USPTO document: the XML or Word rendition the USPTO
publishes for many newer office actions, then the PDF text layer (pdftotext),
then OCR (pdftoppm + tesseract) when those tools are installed. Scanned PDFs
without a text layer yield an empty string if OCR is unavailable.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape


def has_ocr() -> bool:
    return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))


def _clean(text: str) -> str:
    text = text.replace("\r", "").replace("\x0c", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def xml_text(data: bytes) -> str:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return _clean(re.sub(rb"<[^>]+>", b" ", data).decode("utf-8", "replace"))
    lines = []
    for el in root.iter():
        if el.text and el.text.strip():
            lines.append(el.text.strip())
        if el.tail and el.tail.strip():
            lines.append(el.tail.strip())
    return _clean("\n".join(lines))


def docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml")
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ElementTree.fromstring(xml)
    paragraphs = ["".join(t.text or "" for t in p.iter(f"{ns}t")) for p in root.iter(f"{ns}p")]
    return _clean("\n".join(paragraphs))


def pdf_text(data: bytes, ocr: bool = True, max_ocr_pages: int = 60) -> str:
    if not shutil.which("pdftotext"):
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp, "in.pdf")
        pdf.write_bytes(data)
        out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, timeout=300)
        text = _clean(out.stdout.decode("utf-8", "replace"))
        if len(text) >= 200 or not (ocr and has_ocr()):
            return text
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-l", str(max_ocr_pages), str(pdf), f"{tmp}/p"],
                       capture_output=True, timeout=900)
        pages = []
        for img in sorted(Path(tmp).glob("p-*.pgm")):
            r = subprocess.run(["tesseract", str(img), "-", "--psm", "1"], capture_output=True, timeout=300)
            pages.append(r.stdout.decode("utf-8", "replace"))
        return _clean("\n\n".join(pages))


def extract(data: bytes, mime: str | None = None, name: str = "") -> str:
    kind = (mime or "").upper()
    lower = name.lower()
    if "XML" in kind or lower.endswith(".xml"):
        return xml_text(data)
    if "WORD" in kind or "DOCX" in kind or lower.endswith(".docx"):
        return docx_text(data)
    if "PDF" in kind or lower.endswith(".pdf") or data[:5] == b"%PDF-":
        return pdf_text(data)
    return _clean(data.decode("utf-8", "replace"))


def to_docx(title: str, text: str) -> bytes:
    """Build a minimal Word document: a heading followed by one paragraph per line."""

    def para(t: str, style: str | None = None) -> str:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{escape(t)}</w:t></w:r></w:p>'

    body = para(title, "Heading1") + "".join(para(line) for line in text.split("\n"))
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    files = {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '</Types>',
        "_rels/.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        "word/_rels/document.xml.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/></Relationships>',
        "word/styles.xml":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {w}>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/>'
            '<w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/><w:sz w:val="24"/></w:rPr></w:style>'
            '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
            '<w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style></w:styles>',
        "word/document.xml":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {w}><w:body>{body}'
            '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
            '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
            '</w:body></w:document>',
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()
