"""EPO Open Patent Services (OPS): patent families and a backup source of PDFs.

Register for free at https://developers.epo.org and set ``EPO_OPS_KEY`` and
``EPO_OPS_SECRET``. The free tier has a weekly data allowance.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

OPS = "https://ops.epo.org/3.2"


class OpsError(RuntimeError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [c for c in el.iter() if _local(c.tag) == name]


def _child_text(el: ElementTree.Element, name: str) -> str | None:
    for c in el.iter():
        if _local(c.tag) == name and c.text:
            return c.text.strip()
    return None


def _doc_id(ref: ElementTree.Element | None) -> dict | None:
    if ref is None:
        return None
    for d in _children(ref, "document-id"):
        if d.get("document-id-type") in ("docdb", None):
            return {k: _child_text(d, k) for k in ("country", "doc-number", "kind", "date")}
    return None


def parse_family(xml: bytes) -> list[dict]:
    """Members of an INPADOC family response: publication, application, priorities."""
    root = ElementTree.fromstring(xml)
    members = []
    for m in _children(root, "family-member"):
        pubs = [_doc_id(p) for p in m if _local(p.tag) == "publication-reference"]
        app = next((_doc_id(a) for a in m if _local(a.tag) == "application-reference"), None)
        prios = [_doc_id(p) for p in m if _local(p.tag) == "priority-claim"]
        for pub in pubs or [None]:
            members.append({"publication": pub, "application": app, "priorities": [p for p in prios if p],
                            "family_id": m.get("family-id")})
    return members


def parse_image_inquiry(xml: bytes) -> dict | None:
    """The full-document image link and page count from an images inquiry."""
    root = ElementTree.fromstring(xml)
    for inst in _children(root, "document-instance"):
        if inst.get("desc") == "FullDocument":
            return {"link": inst.get("link"), "pages": int(inst.get("number-of-pages") or 0)}
    return None


def epodoc(number: str, country: str = "US") -> str:
    """Patent '10,000,000' -> 'US10000000'; publication '2020/0123456' -> 'US20200123456'."""
    digits = "".join(ch for ch in number if ch.isalnum()).upper()
    return digits if digits[:2].isalpha() else f"{country}{digits}"


class Client:
    def __init__(self, key: str | None = None, secret: str | None = None) -> None:
        self.key = key or os.environ.get("EPO_OPS_KEY")
        self.secret = secret or os.environ.get("EPO_OPS_SECRET")
        if not (self.key and self.secret):
            raise OpsError("EPO_OPS_KEY / EPO_OPS_SECRET are not set (register at https://developers.epo.org)")
        self._token: str | None = None
        self._expires = 0.0

    def _auth(self) -> str:
        if self._token and time.time() < self._expires - 60:
            return self._token
        basic = base64.b64encode(f"{self.key}:{self.secret}".encode()).decode()
        req = urllib.request.Request(
            f"{OPS}/auth/accesstoken", data=b"grant_type=client_credentials",
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        self._token = data["access_token"]
        self._expires = time.time() + int(data.get("expires_in", 1200))
        return self._token

    def _get(self, path: str, accept: str = "application/xml") -> bytes:
        req = urllib.request.Request(f"{OPS}/rest-services/{path}",
                                     headers={"Authorization": f"Bearer {self._auth()}", "Accept": accept})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise OpsError(f"OPS {e.code}: {e.read()[:200]!r}") from e

    def family(self, number: str) -> list[dict]:
        return parse_family(self._get(f"family/publication/epodoc/{urllib.parse.quote(epodoc(number))}"))

    def pdf(self, number: str, max_pages: int = 400) -> bytes:
        """Full document PDF, fetched page by page and joined with pdfunite."""
        info = parse_image_inquiry(self._get(f"published-data/publication/epodoc/{epodoc(number)}/images"))
        if not info or not info["pages"]:
            raise OpsError(f"no images for {number}")
        if not shutil.which("pdfunite"):
            raise OpsError("pdfunite (poppler-utils) is required to join OPS pages")
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for page in range(1, min(info["pages"], max_pages) + 1):
                data = self._get(f"published-data/images/{info['link']}.pdf?Range={page}", "application/pdf")
                path = Path(tmp, f"{page:04d}.pdf")
                path.write_bytes(data)
                files.append(str(path))
            out = Path(tmp, "all.pdf")
            subprocess.run(["pdfunite", *files, str(out)], check=True, capture_output=True)
            return out.read_bytes()
