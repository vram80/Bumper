import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer

from bumper import db, demo, docindex, search
from bumper.web import Store, make_handler

os.environ["BUMPER_QUIET"] = "1"
TODAY = date(2026, 10, 1)


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "t.db")
        apps = demo.generate(12, 40, seed=1, today=TODAY)
        conn = db.connect(path)
        db.upsert(conn, apps)
        search.ensure_schema(conn)
        docs, history = demo.generate_documents(apps, 1)
        conn.executemany("INSERT OR REPLACE INTO file_docs VALUES (?,?,?,?,?)", history)
        for doc in docs:
            search.upsert_document(conn, doc)
        for app_no in {d["app_no"] for d in docs}:
            search.trace_actions(conn, app_no, docindex.SUBSTANTIVE)
        conn.commit()
        conn.close()
        cls.sample_doc = docs[0]
        os.environ.pop("USPTO_API_KEY", None)
        os.environ.pop("EPO_OPS_KEY", None)
        cls.first_name = sorted({a.examiner for a in apps})[0]
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Store(path, TODAY)))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.status, r.read()

    def test_examiner_flow(self):
        status, body = self.get("/api/examiner/suggest?term=" + urllib.parse.quote(self.first_name[:4]))
        self.assertEqual(status, 200)
        self.assertIn(self.first_name, json.loads(body))
        status, body = self.get("/api/examiner?id=" + urllib.parse.quote(self.first_name))
        data = json.loads(body)
        self.assertEqual(data["report"]["examiner"], self.first_name)
        self.assertIn("allowance_rate", data["rank"]["all"])
        self.assertTrue(data["applications"])

    def test_art_unit(self):
        units = json.loads(self.get("/api/artunit/suggest?term=")[1])
        self.assertEqual(units, [])
        unit = json.loads(self.get("/api/examiner?id=" + urllib.parse.quote(self.first_name))[1])["art_unit"]
        data = json.loads(self.get("/api/artunit?id=" + unit)[1])
        self.assertIn(self.first_name, [e["name"] for e in data["examiners"]])

    def test_pages_and_errors(self):
        status, html = self.get("/examiner?id=X")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>", html)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/examiner?id=NOBODY")
        self.assertEqual(ctx.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/static/../web.py")
        self.assertEqual(ctx.exception.code, 404)

    def test_search_api(self):
        data = json.loads(self.get("/api/search?q=" + urllib.parse.quote('+rejected "35 U.S.C"'))[1])
        self.assertGreater(data["total"], 0)
        self.assertIn("<mark>", data["results"][0]["snippet"])
        self.assertIn("doc_code", data["facets"])
        filtered = json.loads(self.get("/api/search?q=rejected&code=CTFR")[1])
        self.assertTrue(all(r["doc_code"] == "CTFR" for r in filtered["results"]))
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/search?q=" + urllib.parse.quote("(unbalanced"))
        self.assertEqual(ctx.exception.code, 400)

    def test_document_endpoints(self):
        doc_id = urllib.parse.quote(self.sample_doc["doc_id"])
        doc = json.loads(self.get("/api/doc?id=" + doc_id)[1])
        self.assertEqual(doc["text"], self.sample_doc["text"])
        status, body = self.get("/api/doc/docx?id=" + doc_id)
        self.assertEqual(body[:2], b"PK")
        codes = json.loads(self.get("/api/codes")[1])
        self.assertIn("CTNF", codes["codes"])

    def test_lookup_local_fallback(self):
        app_no = self.sample_doc["app_no"]
        data = json.loads(self.get("/api/lookup?type=app&q=" + app_no)[1])
        self.assertEqual(data["source"], "local")
        self.assertEqual(data["biblio"]["application_number"], app_no)
        self.assertTrue(data["documents"])
        self.assertTrue(data["warnings"])
        for page in ("/search", "/lookup"):
            self.assertEqual(self.get(page)[0], 200)


if __name__ == "__main__":
    unittest.main()
