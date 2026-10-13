import unittest
from datetime import date

from bumper.db import Application, Event
from bumper.metrics import examiner_report, percentile, rank

AS_OF = date(2026, 10, 1)


def app(no, status, events, filed=date(2022, 1, 1), patent=None, status_date=None):
    return Application(no, "DOE, JANE", "3667", filed, filed, None, status, status_date,
                       patent, None, "t", [Event(d, c, desc) for d, c, desc in events])


ALLOWED = app("1", "Patented Case", [
    (date(2023, 7, 1), "CTNF", "Non-Final Rejection"),
    (date(2024, 1, 1), "CTFR", "Final Rejection"),
    (date(2024, 3, 1), "AFCP", "AFCP request"),
    (date(2024, 4, 1), "MN/=.", "Notice of Allowance"),
], patent="11111111", status_date=date(2024, 8, 1))
ABANDONED = app("2", "Abandoned -- Failure to Respond to an Office Action", [
    (date(2023, 1, 1), "CTRS", "Restriction"),
    (date(2023, 7, 1), "CTNF", "Non-Final Rejection"),
    (date(2024, 2, 1), "CTFR", "Final Rejection"),
    (date(2024, 6, 1), "AP.B", "Appeal Brief Filed"),
    (date(2024, 9, 1), "", "Mail Examiner's Answer"),
    (date(2025, 6, 1), "APDA", "Board affirmed"),
], status_date=date(2025, 9, 1))
PREEXAM = app("3", "Abandoned -- Incomplete Application (Pre-examination)", [], status_date=date(2024, 1, 1))
OLD = app("4", "Patented Case", [(date(2015, 1, 1), "MN/=.", "Notice of Allowance")],
          filed=date(2013, 1, 1), patent="9", status_date=date(2015, 5, 1))


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.r = examiner_report("DOE, JANE", [ALLOWED, ABANDONED, PREEXAM, OLD], AS_OF)

    def test_basic(self):
        b = self.r.basic
        self.assertEqual((b["allowed"], b["abandoned"], b["disposed"]), (1, 1, 2))
        self.assertAlmostEqual(b["allowance_rate"], 0.5)
        self.assertEqual(b["actions_per_allowance"], 2.0)
        self.assertEqual(b["actions_per_abandonment"], 4.0)  # restriction, NF, F, answer
        self.assertAlmostEqual(b["months_to_first_action"], 18.0, delta=0.1)
        self.assertAlmostEqual(b["months_to_first_allowance"], 27.0, delta=0.1)

    def test_outcomes(self):
        self.assertEqual(self.r.afcp["counts"]["allowance"], 1)
        self.assertEqual(self.r.after_final["total"], 1)
        self.assertEqual(self.r.appeal_brief["counts"]["answer_or_decision"], 1)
        self.assertEqual(self.r.appeals["decisions"], 1)
        self.assertEqual(self.r.appeals["affirmance_rate"], 1.0)

    def test_experience_counts_all_years(self):
        self.assertEqual(self.r.experience["nonfinal_rejections"], 2)
        self.assertEqual(self.r.experience["applications"], 4)


class RankTests(unittest.TestCase):
    def test_percentile_midrank(self):
        self.assertEqual(percentile(5, [1, 2, 3, 4]), 1.0)
        self.assertEqual(percentile(0, [1, 2, 3, 4]), 0.0)
        self.assertEqual(percentile(2, [1, 2, 3]), 0.5)

    def test_rank_self_only(self):
        r = examiner_report("DOE, JANE", [ALLOWED, ABANDONED], AS_OF)
        self.assertEqual(rank(r, [r])["allowance_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
