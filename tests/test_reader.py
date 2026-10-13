import unittest

from bumper import drawings, reader

XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE us-patent-grant SYSTEM "us-patent-grant-v45-2014-04-03.dtd" [ ]>
<us-patent-grant><us-bibliographic-data-grant>
<publication-reference><document-id><country>US</country><doc-number>10000001</doc-number><kind>B2</kind><date>20210126</date></document-id></publication-reference>
<classification-national><country>US</country><main-classification>382226</main-classification></classification-national>
<classifications-cpc><main-cpc><classification-cpc><section>G</section><class>06</class><subclass>K</subclass><main-group>9</main-group><subgroup>6256</subgroup></classification-cpc></main-cpc></classifications-cpc>
<invention-title>Widget with a sprocket</invention-title>
<us-references-cited>
<us-citation><patcit num="1"><document-id><country>US</country><doc-number>2007/0217688</doc-number><kind>A1</kind><name>Sabe</name><date>20070900</date></document-id></patcit><category>cited by examiner</category></us-citation>
<us-citation><patcit num="2"><document-id><country>JP</country><doc-number>2001-319226</doc-number><kind>A</kind></document-id></patcit><category>cited by applicant</category></us-citation>
<us-citation><nplcit num="3"><othercit>An office action.</othercit></nplcit><category>cited by applicant</category></us-citation>
</us-references-cited>
<number-of-claims>2</number-of-claims>
<figures><number-of-drawing-sheets>2</number-of-drawing-sheets><number-of-figures>3</number-of-figures></figures>
<priority-claims><priority-claim><country>JP</country><doc-number>2017-1</doc-number><date>20170927</date></priority-claim></priority-claims>
<us-parties><inventors><inventor><addressbook><last-name>Kanada</last-name><first-name>Shoji</first-name></addressbook></inventor></inventors></us-parties>
<assignees><assignee><addressbook><orgname>Example Corp</orgname></addressbook></assignee></assignees>
</us-bibliographic-data-grant>
<abstract><p>A widget <b>10</b> with a sprocket.</p></abstract>
<description>
<heading>BRIEF DESCRIPTION OF THE DRAWINGS</heading>
<p id="p-1" num="0001"><figref>FIG. 1</figref> shows the widget.</p>
<p id="p-2" num="0002"><figref>FIGS. 2A and 2B</figref> show the sprocket.</p>
<heading>DETAILED DESCRIPTION</heading>
<p id="p-3" num="0003">As shown in <figref>FIG. 1</figref>, the widget <b>10</b> has a frame <b>12</b>.</p>
<p id="p-4" num="0004">The sprocket <b>20</b> of the widget <b>10</b> appears in FIG. <b>2A</b>.</p>
</description>
<claims><claim id="CLM-00001" num="00001"><claim-text>1. A widget comprising:
<claim-text>a frame; and</claim-text><claim-text>a sprocket.</claim-text></claim-text></claim>
<claim id="CLM-00002" num="00002"><claim-text>2. The widget of <claim-ref idref="CLM-00001">claim 1</claim-ref>, wherein the frame is steel.</claim-text></claim></claims>
</us-patent-grant>
"""


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.doc = reader.parse_xml(XML)

    def test_biblio_fields(self):
        self.assertEqual(self.doc["title"], "Widget with a sprocket")
        self.assertEqual(self.doc["inventors"], ["Shoji Kanada"])
        self.assertEqual(self.doc["assignees"], ["Example Corp"])
        self.assertEqual(self.doc["priority"][0]["date"], "2017-09-27")

    def test_claims(self):
        c1, c2 = self.doc["claims"]
        self.assertTrue(c1["independent"])
        self.assertFalse(c2["independent"])
        text1 = "".join(p["v"] for p in c1["parts"])
        self.assertTrue(text1.startswith("1. A widget comprising:"))
        self.assertIn("\na frame; and", text1)
        self.assertEqual([p for p in c2["parts"] if p["t"] == "ref"][0]["to"], "CLM-00001")

    def test_citations_and_classes(self):
        us, jp = self.doc["citations"]
        self.assertEqual(us["link"], {"type": "pub", "n": "20070217688"})
        self.assertTrue(us["by_examiner"])
        self.assertIsNone(jp["link"])
        self.assertEqual(self.doc["npl"][0]["text"], "An office action.")
        self.assertEqual(self.doc["classifications"]["cpc"], ["G06K9/6256"])
        self.assertEqual(self.doc["classifications"]["uspc"], ["382/226"])

    def test_numerals_and_figures(self):
        self.assertEqual(self.doc["figures"], ["1", "2A", "2B"])
        self.assertEqual(self.doc["fig_sheet"], {"1": 1, "2A": 2, "2B": 2})
        self.assertEqual(self.doc["numerals"]["12"]["figs"], ["1"])
        self.assertIn("2A", self.doc["numerals"]["20"]["figs"])
        p4 = [p for p in self.doc["paragraphs"] if p.get("num") == "0004"][0]
        kinds = [(x["t"], x["v"]) for x in p4["parts"] if x["t"] != "text"]
        self.assertEqual(kinds, [("num", "20"), ("num", "10"), ("fig", "2A")])


class SheetTests(unittest.TestCase):
    def test_sheet_pages_skip_front_page_and_text(self):
        ink = [0.12, 0.03, 0.02, 0.04, 0.11, 0.12]   # front page, 3 drawing sheets, 2 text pages
        self.assertEqual(drawings.sheet_pages(ink, 3), [2, 3, 4])

    def test_assign_sheets_groups_lettered_figures(self):
        self.assertEqual(drawings.assign_sheets(["1", "2A", "2B", "3"], 3), {"1": 1, "2A": 2, "2B": 2, "3": 3})


if __name__ == "__main__":
    unittest.main()
