"""Examiner statistics computed from applications and their event histories."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from statistics import mean
from typing import Callable, Iterable

from .db import Application
from .events import (BOARD_DECISIONS, COUNTED_ACTIONS, FIRST_ACTIONS, Disposition, Kind,
                     classify, disposition)

WINDOW_YEARS = 3
DAYS_PER_MONTH = 365.25 / 12


def months_between(a: date, b: date) -> float:
    return (b - a).days / DAYS_PER_MONTH


def _ratio(num: float, den: float) -> float | None:
    return num / den if den else None


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


@dataclass
class Case:
    """An application with its events classified and its disposition resolved."""

    app: Application
    disposition: Disposition
    disposed_on: date | None
    events: list[tuple[date, Kind]]

    def kinds(self, kinds: frozenset[Kind] | set[Kind]) -> list[tuple[date, Kind]]:
        return [(d, k) for d, k in self.events if k in kinds]

    def first(self, kinds: frozenset[Kind] | set[Kind]) -> date | None:
        return next((d for d, k in self.events if k in kinds), None)

    @property
    def start(self) -> date | None:
        return self.app.effective_date or self.app.filing_date


def build_case(app: Application) -> Case:
    events = sorted((e.date, classify(e.code, e.description)) for e in app.events if e.date)
    disp = disposition(app.status_text, app.patent_number)
    disposed_on: date | None = None
    if disp is Disposition.ALLOWED:
        allowance = next((d for d, k in events if k is Kind.ALLOWANCE), None)
        disposed_on = allowance or app.grant_date or app.status_date
    elif disp in (Disposition.ABANDONED, Disposition.PREEXAM_ABANDONED):
        disposed_on = app.status_date
    return Case(app, disp, disposed_on, events)


# --------------------------------------------------------------------------- #
# Outcome tracing: what happened next after a given event.
# --------------------------------------------------------------------------- #

def _next_outcome(case: Case, after: date, outcomes: dict[Kind, str],
                  stop: frozenset[Kind] = frozenset()) -> str | None:
    """Label of the first event after ``after`` whose kind is in ``outcomes``.

    Returns None if a ``stop`` event intervenes first or nothing follows.
    """
    for d, k in case.events:
        if d <= after:
            continue
        if k in stop:
            return None
        if k in outcomes:
            return outcomes[k]
    return None


AFTER_FINAL_OUTCOMES = {
    Kind.RCE: "rce",
    Kind.APPEAL_BRIEF: "appeal_brief",
    Kind.ALLOWANCE: "allowance",
    Kind.NONFINAL: "reopen",
    Kind.FINAL: "reopen",
}
PRE_APPEAL_OUTCOMES = {
    Kind.PRE_APPEAL_PROCEED: "proceed_to_board",
    Kind.PRE_APPEAL_REOPEN: "reopen_or_allow",
    Kind.NONFINAL: "reopen_or_allow",
    Kind.FINAL: "reopen_or_allow",
    Kind.ALLOWANCE: "reopen_or_allow",
}
APPEAL_BRIEF_OUTCOMES = {
    Kind.APPEAL_BRIEF_DEFECTIVE: "defective",
    Kind.NONFINAL: "reopen",
    Kind.FINAL: "reopen",
    Kind.EXAMINER_ANSWER: "answer_or_decision",
    Kind.BOARD_AFFIRMED: "answer_or_decision",
    Kind.BOARD_AFFIRMED_IN_PART: "answer_or_decision",
    Kind.BOARD_REVERSED: "answer_or_decision",
    Kind.ALLOWANCE: "allowance",
}


def _distribution(labels: Iterable[str | None], keys: Iterable[str]) -> dict:
    counts = Counter(label for label in labels if label)
    total = sum(counts.values())
    return {
        "total": total,
        "counts": {k: counts.get(k, 0) for k in keys},
        "rates": {k: _ratio(counts.get(k, 0), total) for k in keys},
    }


# --------------------------------------------------------------------------- #
# Per-examiner report
# --------------------------------------------------------------------------- #

@dataclass
class Report:
    examiner: str
    as_of: str
    window_start: str
    basic: dict = field(default_factory=dict)
    appeals: dict = field(default_factory=dict)
    after_final: dict = field(default_factory=dict)
    afcp: dict = field(default_factory=dict)
    pre_appeal: dict = field(default_factory=dict)
    appeal_brief: dict = field(default_factory=dict)
    examiner_interviews: dict = field(default_factory=dict)
    applicant_interviews: dict = field(default_factory=dict)
    experience: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _interview_stats(disposed: list[Case], cases: list[Case], kind: Kind, since: date) -> dict:
    with_iv = [c for c in disposed if c.kinds({kind})]
    allowed = sum(c.disposition is Disposition.ALLOWED for c in with_iv)
    interviews = [d for c in cases for d, k in c.events if k is kind and d >= since]
    iv_cases = [c for c in cases if any(k is kind and d >= since for d, k in c.events)]
    actions = sum(len(c.kinds(COUNTED_ACTIONS)) for c in iv_cases)
    return {
        "interviews": len(interviews),
        "allowance_rate_with": _ratio(allowed, len(with_iv)),
        "disposed_with": len(with_iv),
        "actions_per_interview": _ratio(actions, len(interviews)),
    }


def examiner_report(examiner: str, apps: list[Application], as_of: date | None = None) -> Report:
    as_of = as_of or date.today()
    since = as_of.replace(year=as_of.year - WINDOW_YEARS) if not (as_of.month == 2 and as_of.day == 29) \
        else as_of - timedelta(days=365 * WINDOW_YEARS)
    cases = [build_case(a) for a in apps]
    disposed = [c for c in cases
                if c.disposition in (Disposition.ALLOWED, Disposition.ABANDONED)
                and c.disposed_on and since <= c.disposed_on <= as_of]
    allowed = [c for c in disposed if c.disposition is Disposition.ALLOWED]
    abandoned = [c for c in disposed if c.disposition is Disposition.ABANDONED]

    def in_window(kind_set: frozenset[Kind] | set[Kind]) -> list[tuple[Case, date]]:
        return [(c, d) for c in cases for d, k in c.events if k in kind_set and since <= d <= as_of]

    r = Report(examiner=examiner, as_of=as_of.isoformat(), window_start=since.isoformat())

    first_action = [months_between(c.start, fa) for c in disposed
                    if c.start and (fa := c.first(FIRST_ACTIONS))]
    first_allow = [months_between(c.start, fa) for c in allowed
                   if c.start and (fa := c.first({Kind.ALLOWANCE}))]
    r.basic = {
        "allowed": len(allowed),
        "abandoned": len(abandoned),
        "disposed": len(disposed),
        "allowance_rate": _ratio(len(allowed), len(disposed)),
        "actions_per_allowance": _ratio(sum(len(c.kinds(COUNTED_ACTIONS)) for c in allowed), len(allowed)),
        "actions_per_abandonment": _ratio(sum(len(c.kinds(COUNTED_ACTIONS)) for c in abandoned), len(abandoned)),
        "months_to_first_action": _avg(first_action),
        "months_to_first_allowance": _avg(first_allow),
    }

    decisions = [k for c in cases for d, k in c.events if k in BOARD_DECISIONS and since <= d <= as_of]
    r.appeals = {
        "decisions": len(decisions),
        "affirmed": decisions.count(Kind.BOARD_AFFIRMED),
        "affirmed_in_part": decisions.count(Kind.BOARD_AFFIRMED_IN_PART),
        "reversed": decisions.count(Kind.BOARD_REVERSED),
        "affirmance_rate": _ratio(decisions.count(Kind.BOARD_AFFIRMED), len(decisions)),
    }

    af_keys = ["rce", "appeal_brief", "allowance", "reopen"]
    r.after_final = _distribution(
        (_next_outcome(c, d, AFTER_FINAL_OUTCOMES) for c, d in in_window({Kind.AFTER_FINAL_RESPONSE, Kind.AFCP})),
        af_keys)
    r.afcp = _distribution((_next_outcome(c, d, AFTER_FINAL_OUTCOMES) for c, d in in_window({Kind.AFCP})), af_keys)
    r.pre_appeal = _distribution(
        (_next_outcome(c, d, PRE_APPEAL_OUTCOMES, stop=frozenset({Kind.RCE}))
         for c, d in in_window({Kind.PRE_APPEAL_REQUEST})),
        ["proceed_to_board", "reopen_or_allow"])
    r.appeal_brief = _distribution(
        (_next_outcome(c, d, APPEAL_BRIEF_OUTCOMES, stop=frozenset({Kind.RCE, Kind.APPEAL_BRIEF}))
         for c, d in in_window({Kind.APPEAL_BRIEF})),
        ["reopen", "answer_or_decision", "allowance", "defective"])

    r.examiner_interviews = _interview_stats(disposed, cases, Kind.INTERVIEW_EXAMINER, since)
    r.applicant_interviews = _interview_stats(disposed, cases, Kind.INTERVIEW_APPLICANT, since)

    totals = Counter(k for c in cases for _, k in c.events)
    r.experience = {
        "nonfinal_rejections": totals[Kind.NONFINAL],
        "final_rejections": totals[Kind.FINAL],
        "restrictions": totals[Kind.RESTRICTION],
        "examiner_answers": totals[Kind.EXAMINER_ANSWER],
        "ex_parte_quayle": totals[Kind.QUAYLE],
        "applications": len(cases),
        "first_action_date": min((d for c in cases for d, k in c.events if k in COUNTED_ACTIONS), default=None),
    }
    if r.experience["first_action_date"]:
        r.experience["first_action_date"] = r.experience["first_action_date"].isoformat()
    return r


# --------------------------------------------------------------------------- #
# Ranking against peers
# --------------------------------------------------------------------------- #

RANKED_METRICS: dict[str, Callable[[Report], float | None]] = {
    "allowance_rate": lambda r: r.basic["allowance_rate"],
    "actions_per_allowance": lambda r: r.basic["actions_per_allowance"],
    "actions_per_abandonment": lambda r: r.basic["actions_per_abandonment"],
    "months_to_first_action": lambda r: r.basic["months_to_first_action"],
    "months_to_first_allowance": lambda r: r.basic["months_to_first_allowance"],
    "affirmance_rate": lambda r: r.appeals["affirmance_rate"],
    "total_actions": lambda r: float(sum(v for k, v in r.experience.items()
                                         if k not in ("applications", "first_action_date"))),
}

# Minimum dispositions in the window for an examiner to count as a peer.
MIN_DISPOSALS = 5


def percentile(value: float, population: list[float]) -> float:
    """Mid-rank percentile of ``value`` within a sorted ``population`` (0..1)."""
    if not population:
        return 0.5
    lo = bisect_left(population, value)
    hi = bisect_right(population, value)
    return (lo + (hi - lo) / 2) / len(population)


def rank(report: Report, peers: list[Report]) -> dict[str, float | None]:
    eligible = [p for p in peers if p.basic["disposed"] >= MIN_DISPOSALS] or peers
    out: dict[str, float | None] = {}
    for name, get in RANKED_METRICS.items():
        value = get(report)
        population = sorted(v for p in eligible if (v := get(p)) is not None)
        out[name] = percentile(value, population) if value is not None and population else None
    return out


# --------------------------------------------------------------------------- #
# Chart series
# --------------------------------------------------------------------------- #

def allowance_by_year(apps: list[Application], as_of: date | None = None) -> dict[int, dict]:
    as_of = as_of or date.today()
    buckets: dict[int, Counter] = defaultdict(Counter)
    for c in map(build_case, apps):
        if c.disposed_on and c.disposed_on <= as_of and c.disposition in (Disposition.ALLOWED, Disposition.ABANDONED):
            buckets[c.disposed_on.year][c.disposition.value] += 1
    return {
        y: {"allowed": b["allowed"], "abandoned": b["abandoned"],
            "rate": _ratio(b["allowed"], b["allowed"] + b["abandoned"])}
        for y, b in sorted(buckets.items())
    }


def disposition_counts(apps: list[Application]) -> dict[str, int]:
    counts = Counter(build_case(a).disposition.value for a in apps)
    return {d.value: counts.get(d.value, 0) for d in Disposition}


def action_points(apps: list[Application]) -> list[dict]:
    """Each counted action as (date, months since filing, kind) for a scatter plot."""
    points = []
    for c in map(build_case, apps):
        for d, k in c.kinds(COUNTED_ACTIONS | {Kind.ALLOWANCE}):
            points.append({
                "app_no": c.app.app_no, "date": d.isoformat(), "kind": k.value,
                "months": round(months_between(c.start, d), 1) if c.start else None,
            })
    return points


def application_rows(apps: list[Application]) -> list[dict]:
    rows = []
    for c in sorted(map(build_case, apps), key=lambda c: c.app.filing_date or date.min, reverse=True):
        rows.append({
            "app_no": c.app.app_no,
            "title": c.app.title,
            "art_unit": c.app.art_unit,
            "filed": c.app.filing_date.isoformat() if c.app.filing_date else None,
            "status": c.app.status_text,
            "disposition": c.disposition.value,
            "actions": len(c.kinds(COUNTED_ACTIONS)),
            "patent_number": c.app.patent_number,
        })
    return rows
