import sqlite3
import unittest

from bumper import search


def make_db():
    conn = sqlite3.connect(":memory:")
    search.ensure_schema(conn)
    docs = [
        ("D1", "CTNF", "2023-01-10", "OUTGOING", "SMITH, ANA", "3667",
         "Claims 1-5 are rejected under 35 U.S.C. 101 as directed to an abstract idea without significantly more."),
        ("D2", "A...", "2023-04-01", "INCOMING", "SMITH, ANA", "3667",
         "Applicant submits the claims integrate the abstract idea into a practical application under the guidance."),
        ("D3", "CTFR", "2023-07-01", "OUTGOING", "SMITH, ANA", "3667",
         "Claims 1-5 are rejected under 35 U.S.C. 103 as obvious over Halvorsen in view of Mbeki."),
        ("D4", "A.NE", "2023-09-01", "INCOMING", "SMITH, ANA", "3667",
         "The combination of Halvorsen and Mbeki would render Halvorsen inoperable."),
        ("D5", "NOA", "2023-11-01", "OUTGOING", "LEE, BO", "2121",
         "Reasons for allowance: the prior art does not teach the enablement of the claimed sensor."),
    ]
    for doc_id, code, date, direction, examiner, au, text in docs:
        search.upsert_document(conn, {"doc_id": doc_id, "app_no": "16000001", "doc_code": code, "doc_desc": code,
                                      "direction": direction, "mail_date": date, "examiner": examiner,
                                      "art_unit": au, "text": text})
        conn.execute("INSERT INTO file_docs VALUES (?,?,?,?,?)", ("16000001", doc_id, code, date, direction))
    search.trace_actions(conn, "16000001", {"CTNF", "CTFR", "NOA", "A...", "A.NE"})
    return conn


def ids(result):
    return sorted(r["doc_id"] for r in result["results"])


class ParseTests(unittest.TestCase):
    def test_operators(self):
        self.assertEqual(search.parse("+a +b").fts, '"a" AND "b"')
        self.assertEqual(search.parse("a b").fts, '("a" OR "b")')
        self.assertEqual(search.parse("a b", mode="all").fts, '"a" AND "b"')
        self.assertEqual(search.parse('"x y"~4 -z').fts, 'NEAR("x" "y", 4) NOT "z"')
        self.assertEqual(search.parse("(a OR b) AND c").fts, '("a" OR "b") AND "c"')
        self.assertEqual(search.parse("obv*").fts, '"obv"*')

    def test_fields(self):
        p = search.parse("x examiner:SMITH artunit:3667|2121")
        self.assertEqual(p.filters, [("examiner", "SMITH"), ("art_unit", "3667|2121")])

    def test_errors(self):
        with self.assertRaises(search.QueryError):
            search.parse("(a b")
        with self.assertRaises(search.QueryError):
            search.parse("a)")


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def test_basic_and_phrase(self):
        self.assertEqual(ids(search.search(self.conn, "+abstract +idea")), ["D1", "D2"])
        self.assertEqual(ids(search.search(self.conn, '"practical application"')), ["D2"])
        self.assertEqual(ids(search.search(self.conn, "abstract -applicant")), ["D1"])

    def test_near_prefix_fuzzy(self):
        self.assertEqual(ids(search.search(self.conn, '"halvorsen inoperable"~6')), ["D4"])
        self.assertEqual(ids(search.search(self.conn, "obvi*")), ["D3"])
        self.assertEqual(ids(search.search(self.conn, "enablment~")), ["D5"])

    def test_filters_and_facets(self):
        r = search.search(self.conn, "", {"art_unit": ["2121"]})
        self.assertEqual(ids(r), ["D5"])
        r = search.search(self.conn, "claims")
        self.assertIn(["3667", 3], r["facets"]["art_unit"])

    def test_snippet_is_escaped_and_marked(self):
        r = search.search(self.conn, "halvorsen")
        self.assertIn("<mark>", r["results"][0]["snippet"])

    def test_trace(self):
        d2 = search.get_document(self.conn, "D2")
        self.assertEqual((d2["prev_out"], d2["next_out"]), ("CTNF", "CTFR"))
        r = search.search(self.conn, "code:A.NE next_out:NOA")
        self.assertEqual(ids(r), ["D4"])

    def test_sort_recent(self):
        r = search.search(self.conn, "claims", sort="recent")
        dates = [x["mail_date"] for x in r["results"]]
        self.assertEqual(dates, sorted(dates, reverse=True))


if __name__ == "__main__":
    unittest.main()
