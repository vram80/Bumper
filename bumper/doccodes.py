"""USPTO file-wrapper document codes used for filtering and action tracing.

Codes are the USPTO's own document identifiers as they appear in Patent Center
and the Open Data Portal ``documentCode`` field. Labels and groupings are ours.
"""

from __future__ import annotations

OUTGOING = "OUTGOING"
INCOMING = "INCOMING"

# code -> (label, direction, substantive?)
CODES: dict[str, tuple[str, str, bool]] = {
    # Office actions and notices
    "CTNF": ("Non-final rejection", OUTGOING, True),
    "CTFR": ("Final rejection", OUTGOING, True),
    "CTRS": ("Restriction / election requirement", OUTGOING, True),
    "CTEQ": ("Ex parte Quayle action", OUTGOING, True),
    "CTAV": ("Advisory action", OUTGOING, True),
    "NOA": ("Notice of allowance", OUTGOING, True),
    "EXIN": ("Examiner interview summary", OUTGOING, False),
    "EX.A": ("Examiner's amendment", OUTGOING, False),
    "APEA": ("Examiner's answer", OUTGOING, True),
    "AP.PRE.DEC": ("Pre-appeal conference decision", OUTGOING, True),
    "APDA": ("Board decision: affirmed", OUTGOING, True),
    "APDR": ("Board decision: reversed", OUTGOING, True),
    "APDP": ("Board decision: affirmed in part", OUTGOING, True),
    "APBD": ("Notice of defective appeal brief", OUTGOING, False),
    "ABN": ("Notice of abandonment", OUTGOING, False),
    "CTMS": ("Miscellaneous action", OUTGOING, False),
    "OA.FAI": ("First action interview office action", OUTGOING, True),
    "OA.FAI.PRELM": ("Pre-interview communication", OUTGOING, False),
    "PETDEC": ("Petition decision", OUTGOING, False),
    "C105D": ("Rule 105 requirement", OUTGOING, False),
    "COCOUT": ("Certificate of correction", OUTGOING, False),
    # Applicant filings
    "A...": ("Response to non-final rejection", INCOMING, True),
    "A.NE": ("Response after final rejection", INCOMING, True),
    "A.QU": ("Response to Ex parte Quayle", INCOMING, True),
    "A.NA": ("Amendment after allowance", INCOMING, False),
    "A.PE": ("Preliminary amendment", INCOMING, False),
    "SA..": ("Supplemental response", INCOMING, True),
    "AMSB": ("Amendment filed with RCE", INCOMING, True),
    "RCEX": ("Request for continued examination", INCOMING, True),
    "ELC.": ("Election in response to restriction", INCOMING, True),
    "N/AP": ("Notice of appeal", INCOMING, True),
    "AP.PRE.REQ": ("Pre-appeal conference request", INCOMING, True),
    "AP.B": ("Appeal brief", INCOMING, True),
    "APRB": ("Reply brief", INCOMING, True),
    "INTRVIEW.APP": ("Applicant interview summary", INCOMING, False),
    "AF-D.130A": ("Rule 130(a) declaration", INCOMING, False),
    "AF-D.132": ("Rule 132 declaration", INCOMING, False),
    "IDS": ("Information disclosure statement", INCOMING, False),
    "PET.OP": ("Petition", INCOMING, False),
    "CLM": ("Claims", INCOMING, False),
    "SPEC": ("Specification", INCOMING, False),
    "ABST": ("Abstract", INCOMING, False),
    "DRW": ("Drawings", INCOMING, False),
}

# Filter groups offered in the search UI: label -> codes.
GROUPS: dict[str, list[str]] = {
    "All substantive actions and responses": [c for c, (_, _, s) in CODES.items() if s],
    "Office actions on the merits": ["CTNF", "CTFR", "CTEQ", "NOA"],
    "Applicant responses": ["A...", "A.NE", "A.QU", "SA..", "AMSB"],
    "Appeal papers": ["N/AP", "AP.PRE.REQ", "AP.PRE.DEC", "AP.B", "APEA", "APRB", "APDA", "APDR", "APDP"],
    "Interviews": ["EXIN", "INTRVIEW.APP"],
    "Declarations": ["AF-D.130A", "AF-D.132"],
}


def label(code: str, fallback: str = "") -> str:
    return CODES.get(code, (fallback or code, "", False))[0]


def direction(code: str, fallback: str | None = None) -> str:
    if code in CODES:
        return CODES[code][1]
    return (fallback or "").upper()


def is_substantive(code: str) -> bool:
    return CODES.get(code, ("", "", False))[2]
