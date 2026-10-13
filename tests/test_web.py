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

from bumper import db, demo
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
        conn.close()
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

if __name__ == "__main__":
    unittest.main()
