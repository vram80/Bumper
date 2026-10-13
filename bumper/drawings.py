"""Link reference numerals and figure mentions in a patent's text to its drawing sheets.

Three steps, all from public USPTO data:

1. ``analyze`` reads the patent's full-text XML: the description paragraphs,
   the figures each paragraph refers to (``<figref>`` tags or "FIG. 3" text),
   and the reference numerals used in each paragraph. A numeral is assigned to
   the figures discussed where it appears.
2. Figures are assigned to drawing sheets in the order the "Brief Description
   of the Drawings" lists them, spread over the sheet count from the XML.
3. ``sheet_pages`` finds the drawing sheets in the scanned PDF: they follow the
   front page(s) and carry far less ink than text pages.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree

FIG_LABEL = re.compile(r"\bFIG(?:URE)?S?\.?\s*((?:\d+[A-Z]?(?:\s*(?:-|to|through|,|and|&)\s*)?)+)", re.I)
SINGLE_LABEL = re.compile(r"\d+[A-Z]?")
# A numeral: 1-4 digits with an optional letter or prime, after a word, not a
# unit, year or claim/figure/paragraph number.
NUMERAL = re.compile(r"(?<![\w.,/-])(\d{1,4}[a-z]?'*)(?![\w%°])")
NOT_BEFORE = re.compile(r"(?:FIGS?\.?|FIGURES?|claims?|paragraphs?|para\.|step|steps|about|approximately|of|to|"
                        r"and|or|than|at|least|most|first|second|No\.?|Nos\.?|Ser\.?|Pat\.?|U\.S\.C\.?|CFR|§|"
                        r"\(|\[|equation|Eq\.?|Table|col\.?|line|lines|page)\s*$", re.I)
UNIT_AFTER = re.compile(r"^\s*(?:%|°|mm|cm|nm|µm|um|m|km|kg|g|mg|ml|mL|l|L|s|ms|sec|seconds?|minutes?|hours?|"
                        r"days?|years?|Hz|kHz|MHz|GHz|V|mV|A|mA|W|kW|bits?|bytes?|MB|GB|KB|times|percent|degrees?|"
                        r"rpm|psi|Pa|kPa|N)\b")


def _text(el: ElementTree.Element) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def _labels(spec: str) -> list[str]:
    """'1-3' -> ['1', '2', '3']; '4A and 4B' -> ['4A', '4B']."""
    out: list[str] = []
    for part in re.split(r"\s*(?:,|and|&)\s*", spec.strip()):
        m = re.fullmatch(r"(\d+)\s*(?:-|to|through)\s*(\d+)", part)
        if m and int(m.group(2)) - int(m.group(1)) < 50:
            out += [str(i) for i in range(int(m.group(1)), int(m.group(2)) + 1)]
        else:
            out += SINGLE_LABEL.findall(part.upper())
    return out


def _figs_in(el: ElementTree.Element, text: str) -> list[str]:
    figs = [f for ref in el.iter("figref") for f in _labels(re.sub(r"(?i)^FIG(?:URE)?S?\.?\s*", "", _text(ref)))]
    if not figs:
        figs = [f for m in FIG_LABEL.finditer(text) for f in _labels(m.group(1))]
    return list(dict.fromkeys(figs))


def numerals_in(text: str) -> list[str]:
    found = []
    for m in NUMERAL.finditer(text):
        before, after = text[:m.start()], text[m.end():]
        if not re.search(r"[A-Za-z]\)?\s*$", before):  # must follow a word ("housing 102")
            continue
        if NOT_BEFORE.search(before[-25:]) or UNIT_AFTER.match(after):
            continue
        value = m.group(1)
        if re.fullmatch(r"(19|20)\d\d", value):
            continue
        found.append(value)
    return found


BOLD_NUMERAL = re.compile(r"\d{1,4}[A-Za-z]?'*")


def _parts(el: ElementTree.Element) -> list[dict]:
    """A paragraph as text, numeral and figure-reference parts.

    The USPTO XML marks reference numerals in bold (``<b>128</b>``) and figure
    mentions with ``<figref>``. A bold number right after "FIG." is a figure.
    """
    parts: list[dict] = []

    def add_text(t: str | None) -> None:
        if t:
            if parts and parts[-1]["t"] == "text":
                parts[-1]["v"] += t
            else:
                parts.append({"t": "text", "v": t})

    def walk(node: ElementTree.Element) -> None:
        for child in node:
            raw = _text(child)
            if child.tag == "figref":
                parts.append({"t": "fig", "v": raw, "figs": _labels(re.sub(r"(?i)^FIG(?:URE)?S?\.?\s*", "", raw))})
            elif child.tag == "b" and BOLD_NUMERAL.fullmatch(raw):
                before = "".join(p["v"] for p in parts[-2:])
                if re.search(r"(?i)FIG(?:URE)?S?\.?\s*$", before):
                    parts.append({"t": "fig", "v": raw, "figs": [raw.upper()]})
                else:
                    parts.append({"t": "num", "v": raw})
            elif child.tag in ("b", "i", "u", "sup", "sub", "smallcaps", "o"):
                if child.tag in ("sup", "sub"):
                    add_text(raw)
                else:
                    walk_inline(child)
            else:
                add_text(raw)
            add_text(child.tail)

    def walk_inline(node: ElementTree.Element) -> None:
        add_text(node.text)
        walk(node)

    add_text(el.text)
    walk(el)
    for part in parts:
        if part["t"] == "text":
            part["v"] = re.sub(r"\s+", " ", part["v"])
    return parts


def analyze(xml: bytes) -> dict:
    """Paragraphs as parts, figure order, numeral-to-figure and figure-to-sheet maps."""
    root = ElementTree.fromstring(re.sub(rb"<!DOCTYPE[^>]*>", b"", xml))
    sheets = int(root.findtext(".//number-of-drawing-sheets") or 0)
    n_figures = int(root.findtext(".//number-of-figures") or 0)
    description = root.find(".//description")
    paragraphs: list[dict] = []
    order: list[str] = []          # figure labels in brief-description order
    in_brief = False
    current: list[str] = []        # figures under discussion, carried forward
    numeral_figs: dict[str, Counter] = defaultdict(Counter)
    numeral_count: Counter = Counter()
    if description is not None:
        for el in description.iter():
            if el.tag == "heading":
                head = _text(el)
                in_brief = bool(re.search(r"(?i)description of (the )?(several views of the )?drawings?|"
                                          r"brief description of (the )?figures?", head))
                paragraphs.append({"kind": "heading", "text": head})
                continue
            if el.tag != "p":
                continue
            parts = _parts(el)
            text = "".join(p["v"] for p in parts)
            figs = list(dict.fromkeys(f for p in parts if p["t"] == "fig" for f in p["figs"])) or _figs_in(el, text)
            nums = [p["v"] for p in parts if p["t"] == "num"]
            if not nums and not in_brief:
                # Older XML without bold numerals: fall back to pattern matching.
                nums = numerals_in(text)
            if in_brief:
                order += [f for f in figs if f not in order]
            elif figs:
                current = figs
            if not in_brief:
                for n in nums:
                    numeral_count[n] += 1
                    for f in (figs or current):
                        numeral_figs[n][f] += 1
            paragraphs.append({"kind": "p", "id": el.get("id"), "num": el.get("num"), "parts": parts, "figs": figs})
    if not order:  # no brief description section: order of first mention
        for p in paragraphs:
            order += [f for f in p.get("figs", []) if f not in order]
    fig_sheet = assign_sheets(order, sheets)
    numerals = {}
    for n, figs in numeral_figs.items():
        ranked = [f for f, _ in figs.most_common() if f in fig_sheet] or [f for f, _ in figs.most_common()]
        if ranked:
            numerals[n] = {"figs": ranked[:4], "count": numeral_count[n]}
    return {"sheets": sheets, "figure_count": n_figures, "figures": order, "fig_sheet": fig_sheet,
            "numerals": numerals, "paragraphs": paragraphs}


def assign_sheets(order: list[str], sheets: int) -> dict[str, int]:
    """Spread figures over sheets in order; figures sharing a number share a sheet when possible."""
    if not order or sheets <= 0:
        return {}
    if len(order) <= sheets:
        return {f: i + 1 for i, f in enumerate(order)}
    # Group lettered variants (4A, 4B) so they land together, then spread groups.
    groups: list[list[str]] = []
    for f in order:
        base = re.match(r"\d+", f).group(0)
        if groups and re.match(r"\d+", groups[-1][0]).group(0) == base:
            groups[-1].append(f)
        else:
            groups.append([f])
    out: dict[str, int] = {}
    if len(groups) <= sheets:
        for i, g in enumerate(groups):
            for f in g:
                out[f] = i + 1
        return out
    for i, f in enumerate(order):
        out[f] = min(sheets, 1 + i * sheets // len(order))
    return out


def page_ink(pdf: bytes, dpi: int = 18) -> list[float]:
    """Fraction of dark pixels on each page (low-resolution render)."""
    if not shutil.which("pdftoppm"):
        return []
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp, "in.pdf")
        src.write_bytes(pdf)
        subprocess.run(["pdftoppm", "-r", str(dpi), "-gray", str(src), f"{tmp}/p"],
                       check=True, capture_output=True, timeout=300)
        out = []
        for img in sorted(Path(tmp).glob("p-*.pgm")):
            data = img.read_bytes()
            # PGM: "P5\n<w> <h>\n<max>\n" then one byte per pixel.
            header = re.match(rb"P5\s+(\d+)\s+(\d+)\s+(\d+)\s", data)
            pixels = data[header.end():] if header else b""
            out.append(sum(1 for b in pixels if b < 128) / max(1, len(pixels)))
        return out


def sheet_pages(ink: list[float], sheets: int) -> list[int]:
    """1-based PDF page numbers of drawing sheets 1..sheets.

    The sheets are the run of ``sheets`` consecutive pages, starting after the
    front page(s), with the least ink; text pages are far denser.
    """
    if not ink or sheets <= 0 or sheets >= len(ink):
        return []
    best, best_start = None, 1
    for start in range(1, min(5, len(ink) - sheets) + 1):
        score = sum(ink[start:start + sheets])
        if best is None or score < best:
            best, best_start = score, start
    return [best_start + i + 1 for i in range(sheets)]
