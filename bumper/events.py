"""Classify USPTO file-wrapper transaction events and application statuses.

The USPTO publishes each application's transaction history as a list of
``(eventCode, eventDescriptionText, eventDate)`` records. Codes are not formally
documented and vary over time, so classification matches on the code first and
falls back to the description text. Both tables live here so they can be tuned
against live data in one place.
"""

from __future__ import annotations

import re
from enum import Enum


class Kind(str, Enum):
    NONFINAL = "nonfinal"
    FINAL = "final"
    RESTRICTION = "restriction"
    QUAYLE = "quayle"
    EXAMINER_ANSWER = "examiner_answer"
    ALLOWANCE = "allowance"
    RCE = "rce"
    AFTER_FINAL_RESPONSE = "after_final_response"
    AFCP = "afcp"
    NOTICE_OF_APPEAL = "notice_of_appeal"
    PRE_APPEAL_REQUEST = "pre_appeal_request"
    PRE_APPEAL_PROCEED = "pre_appeal_proceed"
    PRE_APPEAL_REOPEN = "pre_appeal_reopen"
    APPEAL_BRIEF = "appeal_brief"
    APPEAL_BRIEF_DEFECTIVE = "appeal_brief_defective"
    BOARD_AFFIRMED = "board_affirmed"
    BOARD_AFFIRMED_IN_PART = "board_affirmed_in_part"
    BOARD_REVERSED = "board_reversed"
    INTERVIEW_EXAMINER = "interview_examiner"
    INTERVIEW_APPLICANT = "interview_applicant"
    ABANDONMENT = "abandonment"
    OTHER = "other"


# Office actions counted in "actions per allowance / abandonment".
COUNTED_ACTIONS = frozenset({
    Kind.NONFINAL, Kind.FINAL, Kind.RESTRICTION, Kind.QUAYLE, Kind.EXAMINER_ANSWER,
})
# Actions that end the wait for a first substantive response.
FIRST_ACTIONS = frozenset({Kind.NONFINAL, Kind.FINAL, Kind.ALLOWANCE})
BOARD_DECISIONS = frozenset({Kind.BOARD_AFFIRMED, Kind.BOARD_AFFIRMED_IN_PART, Kind.BOARD_REVERSED})

CODES: dict[str, Kind] = {
    "CTNF": Kind.NONFINAL,
    "CTFR": Kind.FINAL,
    "CTRS": Kind.RESTRICTION,
    "CTEQ": Kind.QUAYLE,
    "MN/=.": Kind.ALLOWANCE,
    "RCEX": Kind.RCE,
    "QRCE": Kind.RCE,
    "A.NE": Kind.AFTER_FINAL_RESPONSE,
    "AFCP": Kind.AFCP,
    "N/AP": Kind.NOTICE_OF_APPEAL,
    "AP.B": Kind.APPEAL_BRIEF,
    "APDA": Kind.BOARD_AFFIRMED,
    "APDP": Kind.BOARD_AFFIRMED_IN_PART,
    "APDR": Kind.BOARD_REVERSED,
    "EXIN": Kind.INTERVIEW_EXAMINER,
}

# Ordered: the first matching pattern wins, so specific phrases precede general ones.
DESCRIPTIONS: list[tuple[re.Pattern[str], Kind]] = [(re.compile(p, re.I), k) for p, k in [
    (r"\bnon-?final rejection", Kind.NONFINAL),
    (r"\bfinal rejection", Kind.FINAL),
    (r"\brestriction|election requirement", Kind.RESTRICTION),
    (r"ex parte quayle", Kind.QUAYLE),
    (r"examiner'?s answer", Kind.EXAMINER_ANSWER),
    (r"notice of allowance|allowability", Kind.ALLOWANCE),
    (r"request for continued examination|\bRCE\b", Kind.RCE),
    (r"after final consideration pilot|\bAFCP\b", Kind.AFCP),
    (r"(amendment|response) after final", Kind.AFTER_FINAL_RESPONSE),
    (r"pre-?appeal.*(proceed|forward) to (the )?board", Kind.PRE_APPEAL_PROCEED),
    (r"pre-?appeal.*(reopen|allow|withdraw)", Kind.PRE_APPEAL_REOPEN),
    (r"pre-?appeal (brief )?(conference )?request", Kind.PRE_APPEAL_REQUEST),
    (r"notice of appeal", Kind.NOTICE_OF_APPEAL),
    (r"defective appeal brief|non-?compliant appeal brief", Kind.APPEAL_BRIEF_DEFECTIVE),
    (r"appeal brief", Kind.APPEAL_BRIEF),
    (r"(bpai|board|ptab).*affirmed[- ]in[- ]part", Kind.BOARD_AFFIRMED_IN_PART),
    (r"(bpai|board|ptab).*reversed", Kind.BOARD_REVERSED),
    (r"(bpai|board|ptab).*affirmed", Kind.BOARD_AFFIRMED),
    (r"examiner interview summary|examiner.initiated interview", Kind.INTERVIEW_EXAMINER),
    (r"applicant.initiated interview|interview request", Kind.INTERVIEW_APPLICANT),
    (r"abandonment", Kind.ABANDONMENT),
]]


def classify(code: str, description: str) -> Kind:
    kind = CODES.get((code or "").strip().upper())
    if kind is not None:
        return kind
    for pattern, k in DESCRIPTIONS:
        if pattern.search(description or ""):
            return k
    return Kind.OTHER


class Disposition(str, Enum):
    PENDING = "pending"
    ALLOWED = "allowed"
    ABANDONED = "abandoned"
    # Abandoned before examination; excluded from allowance-rate math.
    PREEXAM_ABANDONED = "preexam_abandoned"


def disposition(status_text: str | None, patent_number: str | None = None) -> Disposition:
    """Map an application status to a disposition.

    Abandonment for failure to pay the issue fee counts as an allowance: the
    examiner allowed the case, and the abandonment says nothing about the merits.
    """
    s = (status_text or "").lower()
    if patent_number or "patented" in s or "notice of allowance" in s:
        return Disposition.ALLOWED
    if "abandon" in s:
        if "issue fee" in s:
            return Disposition.ALLOWED
        if "pre-exam" in s or "preexam" in s or "incomplete application" in s:
            return Disposition.PREEXAM_ABANDONED
        return Disposition.ABANDONED
    return Disposition.PENDING
