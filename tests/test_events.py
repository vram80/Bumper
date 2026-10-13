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


class LiveCodeTests(unittest.TestCase):
    """Codes and descriptions as they appear in live ODP transaction data."""

    def test_mail_twins_are_not_double_counted(self):
        self.assertIs(classify("MCTNF", "Mail Non-Final Rejection"), Kind.OTHER)
        self.assertIs(classify("MCTFR", "Mail Final Rejection (PTOL - 326)"), Kind.OTHER)
        self.assertIs(classify("MAPEA", "Mail Examiner's Answer"), Kind.OTHER)
        self.assertIs(classify("MN/=.", "Mail Notice of Allowance"), Kind.ALLOWANCE)
        self.assertIs(classify("N/=.", "Notice of Allowance Data Verification Completed"), Kind.OTHER)

    def test_lookalikes(self):
        self.assertIs(classify("A.NA", "Amendment after Notice of Allowance (Rule 312)"), Kind.OTHER)
        self.assertIs(classify("CNOA", "Corrected Notice of Allowability"), Kind.OTHER)
        self.assertIs(classify("ELC.", "Response to Election / Restriction Filed"), Kind.OTHER)
        self.assertIs(classify("ABN9", "Disposal for a RCE / CPA / R129"), Kind.OTHER)

    def test_codes(self):
        self.assertIs(classify("RAFC", "PILOT- Request for After Final Consideration Program"), Kind.AFCP)
        self.assertIs(classify("AP.C", "Request for Pre-Appeal Conference Filed"), Kind.PRE_APPEAL_REQUEST)
        self.assertIs(classify("EXIA", "Interview Summary- Applicant Initiated"), Kind.INTERVIEW_APPLICANT)
        self.assertIs(classify("APE2", "2nd or Subsequent Examiner's Answer to Appeal Brief"), Kind.EXAMINER_ANSWER)


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
