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

# Transaction codes observed in live ODP data. Each office action is recorded
# twice: the action itself (e.g. CTNF) and its mailing (MCTNF). Only the action
# code is counted; see ``classify``.
CODES: dict[str, Kind] = {
    "CTNF": Kind.NONFINAL,
    "CTFR": Kind.FINAL,
    "CTRS": Kind.RESTRICTION,
    "CTEQ": Kind.QUAYLE,
    "APEA": Kind.EXAMINER_ANSWER,
    "APE2": Kind.EXAMINER_ANSWER,     # 2nd or subsequent examiner's answer
    "MN/=.": Kind.ALLOWANCE,
    "RCEX": Kind.RCE,
    "A.NE": Kind.AFTER_FINAL_RESPONSE,
    "RAFC": Kind.AFCP,
    "AFCP": Kind.AFCP,
    "N/AP": Kind.NOTICE_OF_APPEAL,
    "AP.C": Kind.PRE_APPEAL_REQUEST,
    "AP.B": Kind.APPEAL_BRIEF,
    "APBI": Kind.APPEAL_BRIEF,        # defective/incomplete brief filed
    "APCA": Kind.PRE_APPEAL_REOPEN,   # pre-appeal decision: rejection withdrawn
    "APBD": Kind.APPEAL_BRIEF_DEFECTIVE,
    "APDA": Kind.BOARD_AFFIRMED,
    "APDP": Kind.BOARD_AFFIRMED_IN_PART,
    "APDR": Kind.BOARD_REVERSED,
    "EXIN": Kind.INTERVIEW_EXAMINER,
    "EXIA": Kind.INTERVIEW_APPLICANT,
    "EXAT": Kind.INTERVIEW_APPLICANT,
    "MABN2": Kind.ABANDONMENT,
    "ABN10": Kind.ABANDONMENT,
}
# Events whose descriptions resemble a counted action but are not one.
IGNORED = frozenset({
    "N/=.",    # allowance data verification (twin of MN/=.)
    "CNOA",    # corrected notice of allowability
    "A.NA",    # amendment after notice of allowance
    "REAS",    # response to reasons for allowance
    "BRCE",    # RCE workflow step
    "ABN9",    # disposal for RCE/CPA (not an abandonment)
    "AFNE",    # AFCP amendment too extensive
    "M865E",   # electronic interview request
    "ELC.",    # applicant's election in reply to a restriction
    "APBR",    # appeal brief review complete
    "AP/A",    # amendment/argument after notice of appeal
    "CPA-AMD", # RCE amendment informal or non-responsive
    "NRAB",    # notice of rescinded abandonment
})

# Ordered: the first matching pattern wins, so specific phrases precede general ones.
DESCRIPTIONS: list[tuple[re.Pattern[str], Kind]] = [(re.compile(p, re.I), k) for p, k in [
    (r"\bnon-?final rejection", Kind.NONFINAL),
    (r"\bfinal rejection", Kind.FINAL),
    (r"\brestriction|election requirement", Kind.RESTRICTION),
    (r"ex parte quayle", Kind.QUAYLE),
    (r"examiner'?s answer", Kind.EXAMINER_ANSWER),
    (r"^(mail )?notice of allowance$", Kind.ALLOWANCE),
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
    code = (code or "").strip().upper()
    kind = CODES.get(code)
    if kind is not None:
        return kind
    if code in IGNORED:
        return Kind.OTHER
    # Mailing twin of a known action (MCTNF, MCTFR, MAPEA, MEXIN, ...): skip so
    # each action is counted once.
    if code.startswith("M") and (code[1:] in CODES or code[1:] in IGNORED or code[1:] in ("APDR", "APDA", "APDP")):
        return Kind.OTHER
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
