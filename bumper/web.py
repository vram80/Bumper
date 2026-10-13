"""HTTP server: HTML shell pages plus a JSON API the front end renders from."""

from __future__ import annotations

import json
import mimetypes
import os
import threading
from collections import defaultdict
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db, metrics

STATIC = Path(__file__).parent / "static"


class Store:
    """Loads applications once and caches per-examiner reports for ranking."""

    def __init__(self, db_path: str, as_of: date | None = None) -> None:
        self.db_path = db_path
        self.as_of = as_of
        self._lock = threading.Lock()
        self._stamp: float | None = None
        self._apps: dict[str, list[db.Application]] = {}
        self._reports: dict[str, metrics.Report] = {}
        self._home_unit: dict[str, str] = {}

    def _refresh(self) -> None:
        stamp = os.path.getmtime(self.db_path) if os.path.exists(self.db_path) else 0.0
        if stamp == self._stamp:
            return
        conn = db.connect(self.db_path)
        try:
            grouped: dict[str, list[db.Application]] = defaultdict(list)
            for app in db.all_applications(conn):
                if app.examiner:
                    grouped[app.examiner].append(app)
        finally:
            conn.close()
        self._apps = dict(grouped)
        self._reports = {name: metrics.examiner_report(name, apps, self.as_of) for name, apps in grouped.items()}
        self._home_unit = {}
        for name, apps in grouped.items():
            units = [a.art_unit for a in apps if a.art_unit]
            if units:
                self._home_unit[name] = max(set(units), key=units.count)
        self._stamp = stamp

    def examiner(self, name: str) -> dict | None:
        with self._lock:
            self._refresh()
            name = name.strip().upper()
            report = self._reports.get(name)
            if report is None:
                return None
            apps = self._apps[name]
            unit = self._home_unit.get(name)
            unit_peers = [r for n, r in self._reports.items() if self._home_unit.get(n) == unit]
            return {
                "report": report.to_dict(),
                "art_unit": unit,
                "art_units": sorted({a.art_unit for a in apps if a.art_unit}),
                "rank": {
                    "all": metrics.rank(report, list(self._reports.values())),
                    "art_unit": metrics.rank(report, unit_peers),
                },
                "peer_counts": {"all": len(self._reports), "art_unit": len(unit_peers)},
                "charts": {
                    "allowance_by_year": metrics.allowance_by_year(apps, self.as_of),
                    "art_unit_allowance_by_year": metrics.allowance_by_year(
                        [a for n in self._apps if self._home_unit.get(n) == unit for a in self._apps[n]],
                        self.as_of),
                    "dispositions": metrics.disposition_counts(apps),
                    "actions": metrics.action_points(apps),
                },
                "applications": metrics.application_rows(apps),
            }

    def art_unit(self, unit: str) -> dict | None:
        with self._lock:
            self._refresh()
            unit = unit.strip()
            names = sorted(n for n, u in self._home_unit.items() if u == unit)
            if not names:
                return None
            apps = [a for n in names for a in self._apps[n]]
            combined = metrics.examiner_report(f"Art Unit {unit}", apps, self.as_of)
            return {
                "art_unit": unit,
                "report": combined.to_dict(),
                "examiners": [
                    {"name": n, **{k: self._reports[n].basic[k] for k in (
                        "disposed", "allowance_rate", "actions_per_allowance", "months_to_first_action")}}
                    for n in names
                ],
                "charts": {"allowance_by_year": metrics.allowance_by_year(apps, self.as_of)},
            }

    def suggest_examiners(self, term: str, limit: int = 15) -> list[str]:
        with self._lock:
            self._refresh()
            t = term.strip().upper()
            return sorted(n for n in self._apps if n.startswith(t))[:limit] if len(t) >= 2 else []

    def suggest_art_units(self, term: str, limit: int = 15) -> list[str]:
        with self._lock:
            self._refresh()
            t = term.strip()
            return sorted({u for u in self._home_unit.values() if u.startswith(t)})[:limit] if t else []


def _json_default(o):
    if isinstance(o, date):
        return o.isoformat()
    raise TypeError(type(o).__name__)


def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Bumper/0.1"

        def log_message(self, fmt, *args):  # quieter default logging
            if os.environ.get("BUMPER_QUIET"):
                return
            super().log_message(fmt, *args)

        def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status: int = 200) -> None:
            body = json.dumps(payload, default=_json_default).encode()
            self._send(status, body, "application/json; charset=utf-8")

        def _page(self, name: str) -> None:
            self._send(200, (STATIC / name).read_bytes(), "text/html; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            path = url.path.rstrip("/").lower() or "/"

            if path == "/":
                return self._send(302, b"", "text/plain", {"Location": "/examiner"})
            if path == "/examiner":
                return self._page("examiner.html")
            if path == "/artunit":
                return self._page("artunit.html")
            if path == "/api/examiner":
                data = store.examiner(q.get("id", ""))
                return self._json(data) if data else self._json({"error": "examiner not found"}, 404)
            if path == "/api/artunit":
                data = store.art_unit(q.get("id", ""))
                return self._json(data) if data else self._json({"error": "art unit not found"}, 404)
            if path == "/api/examiner/suggest":
                return self._json(store.suggest_examiners(q.get("term", "")))
            if path == "/api/artunit/suggest":
                return self._json(store.suggest_art_units(q.get("term", "")))
            if url.path.startswith("/static/"):
                target = (STATIC / url.path[len("/static/"):]).resolve()
                if STATIC.resolve() in target.parents and target.is_file():
                    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                    return self._send(200, target.read_bytes(), ctype)
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

    return Handler


def serve(db_path: str, host: str = "127.0.0.1", port: int = 8000, as_of: date | None = None) -> None:
    store = Store(db_path, as_of)
    httpd = ThreadingHTTPServer((host, port), make_handler(store))
    print(f"Serving on http://{host}:{port}/examiner  (db: {db_path})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
