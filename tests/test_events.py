import unittest

from bumper.events import Disposition, Kind, classify, disposition


class ClassifyTests(unittest.TestCase):
    def test_codes(self):
        self.assertIs(classify("CTNF", ""), Kind.NONFINAL)
        self.assertIs(classify("ctfr", ""), Kind.FINAL)

    def test_description_fallback(self):
        self.assertIs(classify("XXXX", "Non-Final Rejection"), Kind.NONFINAL)
        self.assertIs(classify("", "Final Rejection"), Kind.FINAL)
        self.assertIs(classify("", "Mail Examiner's Answer"), Kind.EXAMINER_ANSWER)
        self.assertIs(classify("", "BPAI Decision - Examiner Affirmed in Part"), Kind.BOARD_AFFIRMED_IN_PART)
        self.assertIs(classify("", "Pre-Appeal Conference Decision - Proceed to Board"), Kind.PRE_APPEAL_PROCEED)
        self.assertIs(classify("", "Something unrelated"), Kind.OTHER)


class DispositionTests(unittest.TestCase):
    def test_issue_fee_abandonment_is_allowance(self):
        self.assertIs(disposition("Abandoned -- Failure to Pay Issue Fee"), Disposition.ALLOWED)

    def test_preexam_excluded(self):
        self.assertIs(disposition("Abandoned -- Incomplete Application (Pre-examination)"),
                      Disposition.PREEXAM_ABANDONED)

    def test_other(self):
        self.assertIs(disposition("Patented Case"), Disposition.ALLOWED)
        self.assertIs(disposition("Abandoned -- Failure to Respond to an Office Action"), Disposition.ABANDONED)
        self.assertIs(disposition("Non Final Action Mailed"), Disposition.PENDING)


if __name__ == "__main__":
    unittest.main()
