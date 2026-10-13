"""Command line: ingest data, print reports, run the web server."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import db, demo, metrics, uspto

DEFAULT_DB = "bumper.db"


def _as_of(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def cmd_demo(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    n = db.upsert(conn, demo.generate(args.examiners, args.apps, args.seed))
    print(f"Wrote {n} synthetic applications to {args.db}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    client = uspto.Client()
    conn = db.connect(args.db)
    total = 0
    for name in args.examiner or []:
        total += db.upsert(conn, client.by_examiner(name, args.limit))
        print(f"examiner {name}: {total} applications so far")
    for unit in args.art_unit or []:
        total += db.upsert(conn, client.by_art_unit(unit, args.limit))
        print(f"art unit {unit}: {total} applications so far")
    if args.with_peers:
        # Pull each fetched examiner's home art unit so percentile ranks have peers.
        units = {u for name in args.examiner or [] for u, _ in db.examiner_art_units(conn, name.upper())[:1]}
        for unit in sorted(units - set(args.art_unit or [])):
            total += db.upsert(conn, client.by_art_unit(unit, args.limit))
            print(f"peer art unit {unit}: {total} applications so far")
    print(f"Stored {total} applications in {args.db}")
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    paths = [p for arg in args.paths for p in (sorted(Path(arg).glob("**/*.json")) if Path(arg).is_dir() else [Path(arg)])]
    n = db.upsert(conn, uspto.read_bulk(paths))
    print(f"Loaded {n} applications from {len(paths)} file(s) into {args.db}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .web import Store

    data = Store(args.db, _as_of(args.as_of)).examiner(args.examiner)
    if data is None:
        print(f"No applications for examiner {args.examiner!r} in {args.db}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, indent=2, default=str))
        return 0
    r, ranks = data["report"], data["rank"]
    b = r["basic"]

    def show(v, kind):
        if v is None:
            return "-"
        return f"{v:.0%}" if kind == "pct" else f"{v:.1f}"

    print(f"{r['examiner']}  (art unit {data['art_unit']}, window {r['window_start']}..{r['as_of']})")
    print(f"{'':28}{'value':>10}{'rank/all':>10}{'rank/AU':>10}")
    for label, key, kind in [
        ("Allowance rate", "allowance_rate", "pct"),
        ("Actions per allowance", "actions_per_allowance", "num"),
        ("Actions per abandonment", "actions_per_abandonment", "num"),
        ("Months to first action", "months_to_first_action", "num"),
        ("Months to first allowance", "months_to_first_allowance", "num"),
    ]:
        print(f"{label:28}{show(b[key], kind):>10}{show(ranks['all'][key], 'pct'):>10}"
              f"{show(ranks['art_unit'][key], 'pct'):>10}")
    print(f"Allowed {b['allowed']} / disposed {b['disposed']}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .web import serve

    serve(args.db, args.host, args.port, _as_of(args.as_of))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bumper", description=__doc__)
    p.add_argument("--db", default=DEFAULT_DB, help=f"SQLite database path (default {DEFAULT_DB})")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("demo", help="populate the database with synthetic data")
    s.add_argument("--examiners", type=int, default=40)
    s.add_argument("--apps", type=int, default=60, help="max applications per examiner")
    s.add_argument("--seed", type=int, default=7)
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("fetch", help="download applications from the USPTO Open Data Portal API")
    s.add_argument("--examiner", action="append", help='e.g. "SMITH, JANE A" (repeatable)')
    s.add_argument("--art-unit", action="append", help="e.g. 3667 (repeatable)")
    s.add_argument("--with-peers", action="store_true", help="also fetch each examiner's home art unit")
    s.add_argument("--limit", type=int, help="max applications per query")
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("load", help="load USPTO bulk file-wrapper JSON files or directories")
    s.add_argument("paths", nargs="+")
    s.set_defaults(func=cmd_load)

    s = sub.add_parser("report", help="print an examiner's statistics")
    s.add_argument("examiner")
    s.add_argument("--as-of", help="report date, YYYY-MM-DD (default today)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--as-of", help="report date, YYYY-MM-DD (default today)")
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except uspto.ApiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
