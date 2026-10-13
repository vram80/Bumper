"""SQLite storage for applications and their prosecution events."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    app_no            TEXT PRIMARY KEY,
    examiner          TEXT,
    art_unit          TEXT,
    filing_date       TEXT,
    effective_date    TEXT,      -- 371(c) date when present, else filing date
    status_code       TEXT,
    status_text       TEXT,
    status_date       TEXT,
    patent_number     TEXT,
    grant_date        TEXT,
    title             TEXT
);
CREATE INDEX IF NOT EXISTS ix_app_examiner ON applications(examiner);
CREATE INDEX IF NOT EXISTS ix_app_art_unit ON applications(art_unit);

CREATE TABLE IF NOT EXISTS events (
    app_no      TEXT NOT NULL,
    event_date  TEXT NOT NULL,
    code        TEXT,
    description TEXT,
    PRIMARY KEY (app_no, event_date, code, description)
);
CREATE INDEX IF NOT EXISTS ix_events_app ON events(app_no);
"""


@dataclass
class Event:
    date: date
    code: str
    description: str


@dataclass
class Application:
    app_no: str
    examiner: str | None
    art_unit: str | None
    filing_date: date | None
    effective_date: date | None
    status_code: str | None
    status_text: str | None
    status_date: date | None
    patent_number: str | None = None
    grant_date: date | None = None
    title: str | None = None
    events: list[Event] = field(default_factory=list)


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def _s(value: date | None) -> str | None:
    return value.isoformat() if value else None


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def upsert(conn: sqlite3.Connection, apps: Iterable[Application]) -> int:
    count = 0
    with transaction(conn):
        for a in apps:
            conn.execute(
                "INSERT OR REPLACE INTO applications VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (a.app_no, a.examiner, a.art_unit, _s(a.filing_date), _s(a.effective_date),
                 a.status_code, a.status_text, _s(a.status_date), a.patent_number,
                 _s(a.grant_date), a.title),
            )
            conn.execute("DELETE FROM events WHERE app_no = ?", (a.app_no,))
            conn.executemany(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?)",
                [(a.app_no, _s(e.date), e.code, e.description) for e in a.events],
            )
            count += 1
    return count


def _load(conn: sqlite3.Connection, where: str, params: tuple) -> list[Application]:
    """Load applications matching a WHERE clause over table alias ``a``, with events."""
    rows = conn.execute(f"SELECT * FROM applications a WHERE {where}", params).fetchall()
    apps = {
        r["app_no"]: Application(
            app_no=r["app_no"], examiner=r["examiner"], art_unit=r["art_unit"],
            filing_date=_d(r["filing_date"]), effective_date=_d(r["effective_date"]),
            status_code=r["status_code"], status_text=r["status_text"],
            status_date=_d(r["status_date"]), patent_number=r["patent_number"],
            grant_date=_d(r["grant_date"]), title=r["title"],
        )
        for r in rows
    }
    if apps:
        ev = conn.execute(
            f"SELECT e.* FROM events e JOIN applications a ON a.app_no = e.app_no "
            f"WHERE {where} ORDER BY e.event_date",
            params,
        )
        for r in ev:
            apps[r["app_no"]].events.append(Event(_d(r["event_date"]), r["code"] or "", r["description"] or ""))
    return list(apps.values())


def applications_for_examiner(conn: sqlite3.Connection, examiner: str) -> list[Application]:
    return _load(conn, "a.examiner = ?", (examiner,))


def applications_for_art_unit(conn: sqlite3.Connection, art_unit: str) -> list[Application]:
    return _load(conn, "a.art_unit = ?", (art_unit,))


def all_applications(conn: sqlite3.Connection) -> list[Application]:
    return _load(conn, "1 = 1", ())


def suggest_examiners(conn: sqlite3.Connection, prefix: str, limit: int = 15) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT examiner FROM applications WHERE examiner LIKE ? ORDER BY examiner LIMIT ?",
        (prefix.upper() + "%", limit),
    )
    return [r[0] for r in rows]


def suggest_art_units(conn: sqlite3.Connection, prefix: str, limit: int = 15) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT art_unit FROM applications WHERE art_unit LIKE ? ORDER BY art_unit LIMIT ?",
        (prefix + "%", limit),
    )
    return [r[0] for r in rows]


def examiner_art_units(conn: sqlite3.Connection, examiner: str) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT art_unit, COUNT(*) n FROM applications WHERE examiner = ? AND art_unit IS NOT NULL "
        "GROUP BY art_unit ORDER BY n DESC",
        (examiner,),
    )
    return [(r[0], r[1]) for r in rows]
