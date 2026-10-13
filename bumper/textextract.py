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
import tarfile
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


# USPTO office-action XML (ST.96-based): paragraphs and list items are blocks;
# page headers and form-paragraph bookkeeping are not part of the reading text.
XML_BLOCKS = {"P", "LI", "Heading", "p", "li", "heading", "claim-text", "Title"}
XML_SKIP = {"BoundaryDataBag", "DocumentMetadata", "FormParagraphNumber", "FormParagraphCategory",
            "ExaminationProgramCode", "RelatedFormParagraph"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def xml_text(data: bytes) -> str:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return _clean(re.sub(rb"<[^>]+>", b" ", data).decode("utf-8", "replace"))
    if not any(_local(el.tag) in XML_BLOCKS for el in root.iter()):
        # Unknown schema: one line per text-bearing element.
        lines = [t.strip() for el in root.iter() for t in (el.text, el.tail) if t and t.strip()]
        return _clean("\n".join(lines))

    blocks: list[str] = []

    def inline(el: ElementTree.Element) -> str:
        parts = [el.text or ""]
        for child in el:
            if _local(child.tag) not in XML_SKIP:
                parts.append(inline(child) if _local(child.tag) not in XML_BLOCKS else "")
            parts.append(child.tail or "")
        return "".join(parts)

    def walk(el: ElementTree.Element) -> None:
        name = _local(el.tag)
        if name in XML_SKIP:
            return
        if name in XML_BLOCKS:
            # Nested blocks (a list inside a paragraph) become their own lines.
            text = re.sub(r"\s+", " ", inline(el)).strip()
            if text:
                blocks.append(text)
            for child in el:
                if _local(child.tag) not in XML_BLOCKS:
                    for nested in child.iter():
                        if _local(nested.tag) in XML_BLOCKS and nested is not child:
                            walk(nested)
                else:
                    walk(child)
            return
        for child in el:
            walk(child)

    walk(root)
    return _clean("\n\n".join(blocks))


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


def tar_text(data: bytes) -> str:
    """Text of the XML/DOCX members of a tar archive (the ODP "XML" download)."""
    parts = []
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            fh = tar.extractfile(member)
            if fh is None:
                continue
            name = member.name.lower()
            if name.endswith(".xml"):
                parts.append(xml_text(fh.read()))
            elif name.endswith(".docx"):
                parts.append(docx_text(fh.read()))
    return _clean("\n\n".join(p for p in parts if p))


def extract(data: bytes, mime: str | None = None, name: str = "") -> str:
    kind = (mime or "").upper()
    lower = name.lower()
    if data[257:262] == b"ustar":
        return tar_text(data)
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
