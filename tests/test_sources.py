import io
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from bumper import docindex, epo, fulltext, lookup, search, textextract

RECORD = {
    "applicationNumberText": "16123456",
    "applicationMetaData": {
        "inventionTitle": "Sensor fusion", "filingDate": "2019-03-01", "applicationTypeLabelName": "Utility",
        "applicationStatusDescriptionText": "Patented Case", "applicationStatusDate": "2021-06-01",
        "examinerNameText": "SMITH, ANA", "groupArtUnitNumber": "3667", "customerNumber": 40001,
        "docketNumber": "ABC-1", "uspcSymbolText": "701/1", "entityStatusData": {"businessEntityStatusCategory": "SMALL"},
        "firstInventorToFileIndicator": "Y", "earliestPublicationNumber": "US20200123456A1",
        "earliestPublicationDate": "2020-04-16", "patentNumber": "11000000", "grantDate": "2021-05-11",
        "inventorBag": [{"inventorNameText": "Pat Example",
                         "correspondenceAddressBag": [{"cityName": "Austin", "geographicRegionCode": "TX", "countryCode": "US"}]}],
    },
    "correspondenceAddressBag": [{"nameLineOneText": "Example IP Group LLP"}],
    "eventDataBag": [{"eventCode": "CTNF", "eventDescriptionText": "Non-Final Rejection", "eventDate": "2020-01-01"}],
}
DOCS = [
    {"documentIdentifier": "K1", "documentCode": "CTNF", "documentCodeDescriptionText": "Non-Final Rejection",
     "officialDate": "2020-01-01T00:00:00", "directionCategory": "OUTGOING",
     "downloadOptionBag": [{"mimeTypeIdentifier": "XML", "downloadUrl": "u/xml"},
                           {"mimeTypeIdentifier": "PDF", "downloadUrl": "u/pdf", "pageTotalQuantity": 9}]},
    {"documentIdentifier": "K2", "documentCode": "A...", "documentCodeDescriptionText": "Response",
     "officialDate": "2020-04-01T00:00:00", "directionCategory": "INCOMING",
     "downloadOptionBag": [{"mimeTypeIdentifier": "MS_WORD", "downloadUrl": "u/docx"}]},
    {"documentIdentifier": "K3", "documentCode": "IDS", "officialDate": "2020-04-02", "directionCategory": "INCOMING",
     "downloadOptionBag": []},
    {"documentIdentifier": "K4", "documentCode": "NOA", "officialDate": "2020-08-01", "directionCategory": "OUTGOING",
     "downloadOptionBag": []},
]


class FakeClient:
    base_url = "https://api.uspto.gov/api/v1/patent/applications/search"

    def application_raw(self, app_no):
        return RECORD

    def documents(self, app_no):
        return DOCS

    def download(self, url):
        if url == "u/xml":
            return b"<oa><p>Claims 1-3 are rejected as obvious over Halvorsen.</p></oa>"
        if url == "u/docx":
            return textextract.to_docx("Response", "REMARKS\nHalvorsen fails to teach it.\n/Jordan Example/\nReg. No. 61,234")
        return b"%PDF-1.4 fake"


class TextTests(unittest.TestCase):
    def test_docx_roundtrip(self):
        data = textextract.to_docx("Title <&>", "line one\nline two")
        self.assertEqual(textextract.docx_text(data), "Title <&>\nline one\nline two")

    def test_tar_archive(self):
        import tarfile
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            body = b"<doc><p>RESPONSE TO AMENDMENT</p><p>Claims 1-6 are rejected.</p></doc>"
            info = tarfile.TarInfo("16000001/ABC/Final Rejection.xml")
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
        text = textextract.extract(buf.getvalue(), "XML")
        self.assertIn("Claims 1-6 are rejected.", text)
        self.assertNotIn("Final Rejection.xml", text)

    def test_xml(self):
        self.assertIn("rejected", textextract.extract(b"<a><b>rejected</b></a>", "XML"))


class LookupTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(lookup.normalize("pat", "US 10,000,000 B2"), "10000000")
        self.assertEqual(lookup.normalize("pat", "RE049,123"), "RE49123")
        self.assertEqual(lookup.normalize("pub", "US 2020/0123456 A1"), "20200123456")
        self.assertEqual(lookup.normalize("pub", "2020/123456"), "20200123456")
        self.assertEqual(lookup.normalize("app", "16/123,456"), "16123456")

    def test_biblio(self):
        b = lookup.biblio_from_record(RECORD)
        self.assertEqual(b["examiner"], "SMITH, ANA")
        self.assertTrue(b["aia"])
        self.assertEqual(b["inventors"][0]["location"], "Austin, TX, US")
        self.assertEqual(b["entity_status"], "SMALL")
        self.assertEqual(b["transactions"][0]["code"], "CTNF")

    def test_documents(self):
        docs = lookup.documents_from_bag(DOCS)
        self.assertEqual(docs[0]["doc_id"], "K4")  # newest first
        self.assertEqual(next(d for d in docs if d["doc_id"] == "K1")["pages"], 9)


class IndexTests(unittest.TestCase):
    def test_index_application(self):
        conn = sqlite3.connect(":memory:")
        with tempfile.TemporaryDirectory() as tmp:
            n = docindex.index_application(FakeClient(), conn, "16123456", Path(tmp))
        self.assertEqual(n, 3)  # CTNF, A..., NOA; IDS is not substantive
        k2 = search.get_document(conn, "K2")
        self.assertEqual(k2["filer"], "Jordan Example")
        self.assertEqual(k2["filer_reg"], "61234")
        self.assertEqual((k2["prev_out"], k2["next_out"]), ("CTNF", "NOA"))
        self.assertEqual(search.search(conn, "halvorsen")["total"], 2)

    def test_index_files(self):
        conn = sqlite3.connect(":memory:")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp, "oa.txt")
            p.write_text("Application No. 16123456\nTHIS ACTION IS MADE FINAL.")
            self.assertEqual(docindex.index_files(conn, [p], "firm"), 1)
        doc = search.search(conn, "final", {"kb": ["firm"]})["results"][0]
        self.assertEqual((doc["doc_code"], doc["app_no"]), ("CTFR", "16123456"))


GRANT = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE us-patent-grant SYSTEM "us-patent-grant-v47.dtd" [ ]>
<us-patent-grant><us-bibliographic-data-grant>
<publication-reference><document-id><country>US</country><doc-number>11000000</doc-number><kind>B2</kind><date>20210511</date></document-id></publication-reference>
<application-reference><document-id><country>US</country><doc-number>16123456</doc-number></document-id></application-reference>
<invention-title>Sensor fusion</invention-title></us-bibliographic-data-grant>
<abstract><p>A sensor fusion method.</p></abstract>
<description><p>Background text.</p><p>Detailed text.</p></description>
<claims><claim><claim-text>1. A method comprising fusing.</claim-text></claim></claims>
</us-patent-grant>
"""


class FullTextTests(unittest.TestCase):
    def test_load_zip(self):
        conn = sqlite3.connect(":memory:")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "ipg210511.zip")
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("ipg210511.xml", GRANT + GRANT.replace(b"11000000", b"11000001"))
            self.assertEqual(fulltext.load(conn, path), 2)
        doc = fulltext.get(conn, "US 11,000,000 B2")
        self.assertEqual(doc["app_no"], "16123456")
        self.assertIn("fusing", doc["claims"])
        self.assertIn("Detailed text.", doc["description"])


FAMILY = b"""<ops:world-patent-data xmlns:ops="http://ops.epo.org" xmlns="http://www.epo.org/exchange">
<ops:patent-family><ops:family-member family-id="123">
<application-reference><document-id document-id-type="docdb"><country>US</country><doc-number>201916123456</doc-number><kind>A</kind></document-id></application-reference>
<publication-reference><document-id document-id-type="docdb"><country>US</country><doc-number>11000000</doc-number><kind>B2</kind><date>20210511</date></document-id></publication-reference>
</ops:family-member><ops:family-member family-id="123">
<publication-reference><document-id document-id-type="docdb"><country>EP</country><doc-number>3900000</doc-number><kind>A1</kind><date>20211027</date></document-id></publication-reference>
</ops:family-member></ops:patent-family></ops:world-patent-data>"""
INQUIRY = b"""<ops:world-patent-data xmlns:ops="http://ops.epo.org"><ops:document-inquiry>
<ops:inquiry-result><ops:document-instance desc="Drawing" link="US/11000000/B2/Drawing" number-of-pages="3"/>
<ops:document-instance desc="FullDocument" link="US/11000000/B2/FullDocument" number-of-pages="17"/></ops:inquiry-result>
</ops:document-inquiry></ops:world-patent-data>"""


class EpoTests(unittest.TestCase):
    def test_family(self):
        members = epo.parse_family(FAMILY)
        self.assertEqual([m["publication"]["country"] for m in members], ["US", "EP"])
        self.assertEqual(members[1]["publication"]["doc-number"], "3900000")

    def test_inquiry(self):
        self.assertEqual(epo.parse_image_inquiry(INQUIRY), {"link": "US/11000000/B2/FullDocument", "pages": 17})

    def test_epodoc(self):
        self.assertEqual(epo.epodoc("10,000,000"), "US10000000")
        self.assertEqual(epo.epodoc("EP3900000"), "EP3900000")

    def test_missing_credentials(self):
        env = {k: os.environ.pop(k) for k in ("EPO_OPS_KEY", "EPO_OPS_SECRET") if k in os.environ}
        try:
            with self.assertRaises(epo.OpsError):
                epo.Client()
        finally:
            os.environ.update(env)


if __name__ == "__main__":
    unittest.main()


class PagingTests(unittest.TestCase):
    def test_oversized_page_is_split(self):
        from bumper import uspto

        records = [{"applicationNumberText": str(16000000 + i), "applicationMetaData": {}} for i in range(130)]
        calls = []

        class Fake(uspto.Client):
            def __init__(self):
                pass

            def _get(self, params, url=None):
                calls.append(params["limit"])
                if params["limit"] > 40:
                    raise uspto.ApiError("413 Payload Too Large", 413)
                start = params["offset"]
                return {"count": len(records), "patentFileWrapperDataBag": records[start:start + params["limit"]]}

        got = [a.app_no for a in Fake().search("q")]
        self.assertEqual(len(got), 130)
        self.assertEqual(len(set(got)), 130)
        self.assertIn(25, calls)
