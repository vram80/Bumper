"""Full-text search over file-wrapper documents (SQLite FTS5).

Query syntax
------------
  word            optional term (documents matching more terms rank higher)
  +word           required term
  -word / NOT w   excluded term
  a OR b, a AND b explicit operators
  "a b c"         phrase
  "a b"~5         the words within 5 tokens of each other, any order
  word*           prefix match
  word~ / word~1  fuzzy match (edit distance 2, or the number given)
  ( ... )         grouping
  field:value     field filter: examiner, artunit, customer, code, app, kb,
                  filer, next_out, prev_out, next_in, prev_in, year

With ``mode="all"`` bare terms are treated as required.
"""

from __future__ import annotations

import html
import re
import sqlite3
from dataclasses import dataclass, field

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id          TEXT PRIMARY KEY,
    kb              TEXT NOT NULL DEFAULT 'ex_parte',
    app_no          TEXT,
    doc_code        TEXT,
    doc_desc        TEXT,
    direction       TEXT,
    mail_date       TEXT,
    examiner        TEXT,
    art_unit        TEXT,
    customer_number TEXT,
    correspondent   TEXT,
    filer           TEXT,
    filer_reg       TEXT,
    prev_out        TEXT,
    next_out        TEXT,
    prev_in         TEXT,
    next_in         TEXT,
    pages           INTEGER,
    pdf_url         TEXT,
    pdf_path        TEXT,
    text            TEXT
);
CREATE INDEX IF NOT EXISTS ix_doc_app ON documents(app_no);
CREATE INDEX IF NOT EXISTS ix_doc_kb ON documents(kb);

-- Complete document list per application (indexed or not), used to trace
-- the actions before and after each indexed document.
CREATE TABLE IF NOT EXISTS file_docs (
    app_no    TEXT NOT NULL,
    doc_id    TEXT NOT NULL,
    doc_code  TEXT,
    mail_date TEXT,
    direction TEXT,
    PRIMARY KEY (app_no, doc_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    text, doc_desc, content='documents', content_rowid='rowid', tokenize='porter unicode61'
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_vocab USING fts5vocab(docs_fts, row);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO docs_fts(rowid, text, doc_desc) VALUES (new.rowid, new.text, new.doc_desc);
END;
CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, text, doc_desc) VALUES ('delete', old.rowid, old.text, old.doc_desc);
END;
CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, text, doc_desc) VALUES ('delete', old.rowid, old.text, old.doc_desc);
    INSERT INTO docs_fts(rowid, text, doc_desc) VALUES (new.rowid, new.text, new.doc_desc);
END;
"""

FIELDS = {
    "examiner": "examiner", "artunit": "art_unit", "art_unit": "art_unit", "customer": "customer_number",
    "code": "doc_code", "type": "doc_code", "app": "app_no", "kb": "kb", "filer": "filer",
    "next_out": "next_out", "prev_out": "prev_out", "next_in": "next_in", "prev_in": "prev_in",
    "correspondent": "correspondent", "year": "year",
}
FACETS = ["kb", "doc_code", "art_unit", "examiner", "customer_number", "next_out", "prev_out", "next_in", "prev_in"]

DOC_COLUMNS = ["doc_id", "kb", "app_no", "doc_code", "doc_desc", "direction", "mail_date", "examiner", "art_unit",
               "customer_number", "correspondent", "filer", "filer_reg", "prev_out", "next_out", "prev_in",
               "next_in", "pages", "pdf_url", "pdf_path", "text"]


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def upsert_document(conn: sqlite3.Connection, doc: dict) -> None:
    cols = [c for c in DOC_COLUMNS if c in doc]
    conn.execute(f"DELETE FROM documents WHERE doc_id = ?", (doc["doc_id"],))
    conn.execute(f"INSERT INTO documents ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                 [doc[c] for c in cols])


# --------------------------------------------------------------------------- #
# Query parsing
# --------------------------------------------------------------------------- #

class QueryError(ValueError):
    pass


TOKEN = re.compile(r'''
    (?P<lparen>\() | (?P<rparen>\)) |
    (?P<mod>[+-])(?=[^\s]) |
    (?P<field>[A-Za-z_]+):(?P<fvalue>"[^"]*"|[^\s()]+) |
    "(?P<phrase>[^"]*)"(?:~(?P<near>\d+))? |
    (?P<word>[^\s()"]+)
''', re.X)


@dataclass
class Parsed:
    fts: str | None
    filters: list[tuple[str, str]] = field(default_factory=list)
    exclude_only: str | None = None  # FTS expression for a query that only excludes


def _levenshtein(a: str, b: str, cap: int) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


class _Parser:
    def __init__(self, query: str, conn: sqlite3.Connection | None, mode: str) -> None:
        self.tokens = [m for m in TOKEN.finditer(query)]
        self.pos = 0
        self.conn = conn
        self.mode = mode
        self.filters: list[tuple[str, str]] = []

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def fuzzy(self, word: str, dist: int) -> str:
        word = word.lower()
        options = {word}
        if self.conn is not None:
            rows = self.conn.execute(
                "SELECT term FROM docs_vocab WHERE term >= ? AND term < ? AND length(term) BETWEEN ? AND ?",
                (word[0], chr(ord(word[0]) + 1), len(word) - dist - 3, len(word) + dist))
            options |= {t for (t,) in rows if _levenshtein(word, t, dist) <= dist
                        or _levenshtein(word[:len(t)], t, dist) <= dist and len(t) >= len(word) - 3}
        return "(" + " OR ".join(_quote(o) for o in sorted(options)[:50]) + ")"

    def atom(self, m) -> str | None:
        if m.group("phrase") is not None:
            words = _words(m.group("phrase"))
            if not words:
                return None
            if m.group("near"):
                return f"NEAR({' '.join(_quote(w) for w in words)}, {int(m.group('near'))})"
            return _quote(" ".join(words))
        if m.group("field"):
            name = m.group("field").lower()
            if name not in FIELDS:
                # Not a known field: treat "a:b" as two words.
                return " AND ".join(_quote(w) for w in _words(m.group(0))) or None
            self.filters.append((FIELDS[name], m.group("fvalue").strip('"')))
            return None
        word = m.group("word")
        fz = re.fullmatch(r"(.+?)~(\d?)", word)
        if fz:
            return self.fuzzy(fz.group(1), int(fz.group(2) or 2))
        if word.endswith("*"):
            base = _words(word[:-1])
            return (_quote(base[0]) + "*") if base else None
        parts = _words(word)
        if not parts:
            return None
        return _quote(" ".join(parts)) if len(parts) > 1 else _quote(parts[0])

    def group(self, depth: int = 0) -> str | None:
        required: list[str] = []
        optional: list[str] = []
        excluded: list[str] = []
        pending_op: str | None = None
        last: tuple[list[str], str] | None = None
        while (m := self.peek()) is not None:
            if m.group("rparen"):
                if depth == 0:
                    raise QueryError("unbalanced ')'")
                self.pos += 1
                break
            self.pos += 1
            word = m.group("word")
            if word in ("AND", "OR", "NOT", "&&", "||", "!"):
                pending_op = {"&&": "AND", "||": "OR", "!": "NOT"}.get(word, word)
                continue
            mod = None
            if m.group("mod"):
                mod = m.group("mod")
                m = self.peek()
                if m is None:
                    break
                self.pos += 1
            expr = self.group(depth + 1) if m.group("lparen") else self.atom(m)
            if expr is None:
                continue
            if mod == "-" or pending_op == "NOT":
                excluded.append(expr)
            elif mod == "+" or pending_op == "AND" or self.mode == "all" and pending_op != "OR":
                if pending_op == "AND" and last and last[0] is optional:
                    optional.remove(last[1])
                    required.append(last[1])
                required.append(expr)
                last = (required, expr)
            else:
                if pending_op == "OR" and last and last[0] is required:
                    # "a OR b" where a was required by mode=all: make both alternatives.
                    required.remove(last[1])
                    expr = f"({last[1]} OR {expr})"
                    required.append(expr)
                    last = (required, expr)
                else:
                    optional.append(expr)
                    last = (optional, expr)
            pending_op = None
        else:
            if depth > 0:
                raise QueryError("unbalanced '('")

        core = " AND ".join(required) if required else (
            "(" + " OR ".join(optional) + ")" if len(optional) > 1 else (optional[0] if optional else None))
        if core is None:
            if excluded and depth > 0:
                raise QueryError("a group cannot contain only excluded terms")
            self.excluded_only = excluded
            return None
        return core + "".join(f" NOT {e}" for e in excluded)


def parse(query: str, conn: sqlite3.Connection | None = None, mode: str = "any") -> Parsed:
    p = _Parser(query or "", conn, mode)
    p.excluded_only = []
    fts = p.group()
    exclude_only = " OR ".join(p.excluded_only) if fts is None and p.excluded_only else None
    return Parsed(fts, p.filters, exclude_only)


# --------------------------------------------------------------------------- #
# Searching
# --------------------------------------------------------------------------- #

def _where(parsed: Parsed, filters: dict[str, list[str]]) -> tuple[str, list]:
    clauses, params = [], []
    if parsed.fts:
        clauses.append("d.rowid IN (SELECT rowid FROM docs_fts WHERE docs_fts MATCH ?)")
        params.append(parsed.fts)
    if parsed.exclude_only:
        clauses.append("d.rowid NOT IN (SELECT rowid FROM docs_fts WHERE docs_fts MATCH ?)")
        params.append(parsed.exclude_only)
    combined: dict[str, list[str]] = {}
    for col, value in parsed.filters:
        combined.setdefault(col, []).extend(value.split("|"))
    for col, values in filters.items():
        if col in FIELDS.values() and values:
            combined.setdefault(col, []).extend(v for raw in values for v in raw.split("|") if v)
    for col, values in combined.items():
        if col == "year":
            clauses.append("(" + " OR ".join("substr(d.mail_date, 1, 4) = ?" for _ in values) + ")")
            params.extend(values)
        elif col in ("examiner", "correspondent", "filer"):
            clauses.append("(" + " OR ".join(f"d.{col} LIKE ?" for _ in values) + ")")
            params.extend(f"%{v}%" for v in values)
        else:
            clauses.append(f"d.{col} IN ({','.join('?' * len(values))})")
            params.extend(values)
    return (" AND ".join(clauses) or "1 = 1"), params


def _snippet_html(raw: str) -> str:
    return html.escape(raw).replace("\x02", "<mark>").replace("\x03", "</mark>")


def search(conn: sqlite3.Connection, query: str = "", filters: dict[str, list[str]] | None = None,
           sort: str = "relevance", page: int = 1, per_page: int = 20, mode: str = "any") -> dict:
    parsed = parse(query, conn, mode)
    where, params = _where(parsed, filters or {})
    total = conn.execute(f"SELECT COUNT(*) FROM documents d WHERE {where}", params).fetchone()[0]

    meta_cols = ", ".join(f"d.{c}" for c in DOC_COLUMNS if c not in ("text", "pdf_path"))
    if parsed.fts:
        sql = (f"SELECT {meta_cols}, snippet(docs_fts, 0, char(2), char(3), ' … ', 40) AS snip, "
               f"bm25(docs_fts, 1.0, 2.0) AS score "
               f"FROM docs_fts JOIN documents d ON d.rowid = docs_fts.rowid "
               f"WHERE docs_fts MATCH ? AND {where} ")
        args = [parsed.fts, *params]
        order = "score" if sort == "relevance" else "d.mail_date DESC"
    else:
        sql = f"SELECT {meta_cols}, substr(d.text, 1, 300) AS snip, 0 AS score FROM documents d WHERE {where} "
        args = params
        order = "d.mail_date DESC"
    page = max(1, page)
    cur = conn.execute(f"{sql} ORDER BY {order} LIMIT ? OFFSET ?", [*args, per_page, (page - 1) * per_page])
    names = [c[0] for c in cur.description]
    results = []
    for r in cur:
        item = dict(zip(names, r))
        snip = item.pop("snip") or ""
        item["snippet"] = _snippet_html(snip) if parsed.fts else html.escape(snip)
        results.append(item)

    facets = {}
    for col in FACETS:
        facet_rows = conn.execute(
            f"SELECT d.{col}, COUNT(*) FROM documents d WHERE {where} AND d.{col} IS NOT NULL AND d.{col} != '' "
            f"GROUP BY d.{col} ORDER BY COUNT(*) DESC LIMIT 15", params)
        facets[col] = [[v, n] for v, n in facet_rows]
    return {"total": total, "page": page, "per_page": per_page, "query": parsed.fts,
            "filters": parsed.filters, "results": results, "facets": facets}


def get_document(conn: sqlite3.Connection, doc_id: str) -> dict | None:
    row = conn.execute(f"SELECT {','.join(DOC_COLUMNS)} FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    return dict(zip(DOC_COLUMNS, row)) if row else None


# --------------------------------------------------------------------------- #
# Action tracing
# --------------------------------------------------------------------------- #

def trace_actions(conn: sqlite3.Connection, app_no: str, substantive: set[str]) -> None:
    """Fill prev/next outgoing/incoming action codes for indexed docs of an application."""
    history = conn.execute(
        "SELECT doc_id, doc_code, mail_date, direction FROM file_docs WHERE app_no = ? ORDER BY mail_date, doc_id",
        (app_no,)).fetchall()
    events = [(d, c, dt, dirn) for d, c, dt, dirn in history if c in substantive]
    for doc_id, mail_date in conn.execute("SELECT doc_id, mail_date FROM documents WHERE app_no = ?", (app_no,)).fetchall():
        before = [e for e in events if (e[2], e[0]) < (mail_date, doc_id) and e[0] != doc_id]
        after = [e for e in events if (e[2], e[0]) > (mail_date, doc_id) and e[0] != doc_id]

        def pick(seq, direction, last):
            items = [e[1] for e in seq if e[3] == direction]
            return (items[-1] if last else items[0]) if items else None

        conn.execute(
            "UPDATE documents SET prev_out = ?, next_out = ?, prev_in = ?, next_in = ? WHERE doc_id = ?",
            (pick(before, "OUTGOING", True), pick(after, "OUTGOING", False),
             pick(before, "INCOMING", True), pick(after, "INCOMING", False), doc_id))
