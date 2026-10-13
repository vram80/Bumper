"""Synthetic data so the app can be run and tested without a USPTO API key.

Every record produced here is fake. Examiner names are generated, not real.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from .db import Application, Event

SURNAMES = ["ADLER", "BRENNAN", "CASTILLO", "DUBOIS", "EKWUEME", "FONSECA", "GARRISON", "HOLLAND",
            "IVANOVA", "JANSSEN", "KOWALSKI", "LINDQVIST", "MORENO", "NAKAMURA", "OKAFOR", "PETERSEN",
            "QUINTERO", "RASMUSSEN", "SANTORO", "TANAKA", "UNDERWOOD", "VARGAS", "WEBER", "YILMAZ"]
GIVEN = ["ALEX", "BLAIR", "CASEY", "DANA", "ELLIS", "FRANCIS", "JORDAN", "MORGAN", "QUINN", "RILEY"]
ART_UNITS = ["2121", "2122", "3661", "3667", "3668"]
TITLES = ["Vehicle trajectory planning", "Sensor fusion apparatus", "Battery management method",
          "Neural network accelerator", "Wireless charging circuit", "Autonomous parking system"]

# Code and description pairs mirroring the shape of real file-wrapper events.
EV = {
    "nonfinal": ("CTNF", "Non-Final Rejection"),
    "final": ("CTFR", "Final Rejection"),
    "restriction": ("CTRS", "Requirement for Restriction/Election"),
    "allow": ("MN/=.", "Mail Notice of Allowance"),
    "rce": ("RCEX", "Request for Continued Examination (RCE)"),
    "afr": ("A.NE", "Amendment after Final Rejection"),
    "afcp": ("RAFC", "PILOT- Request for After Final Consideration Program"),
    "noa": ("N/AP", "Notice of Appeal Filed"),
    "brief": ("AP.B", "Appeal Brief Filed"),
    "answer": ("APEA", "Examiner's Answer to Appeal Brief"),
    "affirmed": ("APDA", "BPAI Decision - Examiner Affirmed"),
    "reversed": ("APDR", "BPAI Decision - Examiner Reversed"),
    "ex_iv": ("EXIN", "Interview Summary Record"),
    "app_iv": ("EXIA", "Interview Summary- Applicant Initiated"),
    "abn": ("ABN2", "Abandonment for Failure to Respond to Office Action"),
}


def _simulate(rng: random.Random, app_no: str, examiner: str, art_unit: str, filed: date,
              strictness: float, speed: float, today: date) -> Application:
    events: list[Event] = []
    t = filed + timedelta(days=int(rng.gauss(30 * speed * 16, 60)))

    def add(key: str, when: date) -> None:
        code, desc = EV[key]
        events.append(Event(when, code, desc))

    status, status_date, patent = "Docketed New Case - Ready for Examination", filed, None
    if rng.random() < 0.15 and t < today:
        add("restriction", t)
        t += timedelta(days=rng.randint(90, 160))
    round_ = 0
    while t < today:
        round_ += 1
        if rng.random() > strictness * (0.85 ** (round_ - 1)):
            if rng.random() < 0.3:
                add("ex_iv", t - timedelta(days=rng.randint(3, 20)))
            add("allow", t)
            status, status_date = "Patented Case", t + timedelta(days=rng.randint(90, 200))
            patent = f"DEMO{rng.randint(1_000_000, 9_999_999)}"  # deliberately not a real patent number
            break
        add("nonfinal" if round_ % 2 else "final", t)
        if rng.random() < 0.2:
            add("app_iv", t + timedelta(days=rng.randint(20, 60)))
        t += timedelta(days=rng.randint(80, 180))
        if t >= today:
            status = "Non Final Action Mailed" if round_ % 2 else "Final Rejection Mailed"
            status_date = t
            break
        if round_ % 2 == 0:  # after a final rejection
            r = rng.random()
            if r < 0.15:
                add("afcp" if rng.random() < 0.5 else "afr", t)
                t += timedelta(days=rng.randint(30, 90))
                continue
            if r < 0.22:
                add("noa", t)
                add("brief", t + timedelta(days=60))
                t += timedelta(days=rng.randint(120, 200))
                if rng.random() < 0.7:
                    add("answer", t)
                    t += timedelta(days=rng.randint(300, 600))
                    if t < today:
                        add("affirmed" if rng.random() < strictness else "reversed", t)
                continue
            if r < 0.6:
                add("rce", t)
                t += timedelta(days=rng.randint(60, 150))
                continue
        if rng.random() < 0.12 * round_:
            add("abn", t)
            status, status_date = "Abandoned -- Failure to Respond to an Office Action", t
            break
    return Application(app_no, examiner, art_unit, filed, filed, None, status, status_date,
                       patent, status_date if patent else None, rng.choice(TITLES), sorted(events, key=lambda e: e.date))


def generate(n_examiners: int = 40, apps_per_examiner: int = 60, seed: int = 7,
             today: date | None = None) -> list[Application]:
    rng = random.Random(seed)
    today = today or date.today()
    names = set()
    while len(names) < n_examiners:
        names.add(f"{rng.choice(SURNAMES)}, {rng.choice(GIVEN)} {rng.choice('ABCDEFGHJKLMNPRSTW')}")
    apps = []
    serial = 16_000_000
    for name in sorted(names):
        art_unit = rng.choice(ART_UNITS)
        strictness = rng.uniform(0.35, 0.9)
        speed = rng.uniform(0.7, 1.5)
        for _ in range(rng.randint(apps_per_examiner // 3, apps_per_examiner)):
            serial += rng.randint(1, 900)
            filed = today - timedelta(days=rng.randint(200, 365 * 8))
            apps.append(_simulate(rng, str(serial), name, art_unit, filed, strictness, speed, today))
    return apps


# --------------------------------------------------------------------------- #
# Synthetic file-wrapper documents for the search demo
# --------------------------------------------------------------------------- #

REFS = ["Halvorsen", "Mbeki", "Ostrowski", "Delacroix", "Fairweather", "Nguyen-Park", "Achterberg", "Silvestri"]
GROUNDS = {
    "101": ("Claims {claims} are rejected under 35 U.S.C. 101 because the claimed invention is directed to a "
            "judicial exception (an abstract idea) without significantly more. Under Step 2A, Prong One, the claims "
            "recite mental processes such as collecting and comparing {topic} data. Under Prong Two, the additional "
            "elements, a generic processor and memory, do not integrate the exception into a practical application."),
    "102": ("Claims {claims} are rejected under 35 U.S.C. 102(a)(1) as being anticipated by {ref1} (US {num1}). "
            "{ref1} discloses a {topic} system comprising each element of the claim, see paragraphs [00{p1}]-[00{p2}]."),
    "103": ("Claims {claims} are rejected under 35 U.S.C. 103 as being unpatentable over {ref1} (US {num1}) in view "
            "of {ref2} (US {num2}). {ref1} teaches the {topic} apparatus but does not expressly teach the claimed "
            "threshold comparison. {ref2} teaches that limitation. It would have been obvious to one of ordinary "
            "skill in the art before the effective filing date to combine the teachings to improve reliability."),
    "112": ("Claims {claims} are rejected under 35 U.S.C. 112(b) as being indefinite. The term \"substantially\" "
            "in claim {c1} is a relative term which renders the claim indefinite; the specification does not "
            "provide a standard for ascertaining the requisite degree."),
}
ARGUMENTS = [
    "Applicant respectfully submits that {ref1} fails to disclose the claimed {topic} limitation, as amended.",
    "The Office has not established a prima facie case of obviousness because there is no reason to combine "
    "{ref1} with {ref2}; doing so would render {ref1} unsatisfactory for its intended purpose.",
    "Under the 2019 Revised Patent Subject Matter Eligibility Guidance, the claims integrate any alleged abstract "
    "idea into a practical application by improving the functioning of the {topic} system itself.",
    "Claim {c1} has been amended to remove the term \"substantially\", rendering the indefiniteness rejection moot.",
]


def _claims(rng: random.Random) -> tuple[str, int]:
    first = rng.randint(1, 12)
    return f"{first}-{first + rng.randint(2, 9)}", first


def _office_action(rng: random.Random, topic: str, final: bool) -> str:
    claims, c1 = _claims(rng)
    fill = dict(claims=claims, c1=c1, topic=topic, ref1=rng.choice(REFS), ref2=rng.choice(REFS),
                num1=f"{rng.randint(7, 11)},{rng.randint(100, 999)},{rng.randint(100, 999)}",
                num2=f"20{rng.randint(10, 22)}/0{rng.randint(100000, 999999)}",
                p1=rng.randint(10, 60), p2=rng.randint(61, 99))
    grounds = rng.sample(sorted(GROUNDS), rng.randint(1, 3))
    body = "\n\n".join(GROUNDS[g].format(**fill) for g in grounds)
    tail = ("THIS ACTION IS MADE FINAL. Applicant is reminded of the extension of time policy as set forth in "
            "37 CFR 1.136(a)." if final else "Any inquiry concerning this communication should be directed to "
            "the examiner.")
    return f"DETAILED ACTION\n\nClaim Rejections\n\n{body}\n\n{tail}"


def _response(rng: random.Random, topic: str, attorney: str, reg: int) -> str:
    claims, c1 = _claims(rng)
    fill = dict(claims=claims, c1=c1, topic=topic, ref1=rng.choice(REFS), ref2=rng.choice(REFS))
    args = "\n\n".join(a.format(**fill) for a in rng.sample(ARGUMENTS, rng.randint(1, 3)))
    return (f"AMENDMENTS TO THE CLAIMS\n\nClaim {c1} (Currently Amended).\n\nREMARKS\n\n{args}\n\n"
            f"Respectfully submitted,\n/{attorney}/\n{attorney}, Reg. No. {reg}")


def generate_documents(apps: list[Application], seed: int = 7, per_app: float = 0.5) -> tuple[list[dict], list[tuple]]:
    """Documents (as ``search.documents`` rows) and full file histories for a share of ``apps``."""
    rng = random.Random(seed)
    firms = [("Example IP Group LLP", "40001"), ("Sample & Partners", "40002"), ("Placeholder Law PC", "40003")]
    attorneys = [("Jordan Q. Example", 61234), ("Riley T. Sample", 70511), ("Casey M. Placeholder", 58890)]
    out_codes = {"CTNF": "CTNF", "CTFR": "CTFR", "CTRS": "CTRS", "MN/=.": "NOA", "APEA": "APEA"}
    in_codes = {"RCEX": "RCEX", "A.NE": "A.NE", "RAFC": "A.NE", "AP.B": "AP.B", "N/AP": "N/AP"}
    docs, history = [], []
    for app in apps:
        if rng.random() > per_app:
            continue
        firm, customer = rng.choice(firms)
        attorney, reg = rng.choice(attorneys)
        topic = (app.title or "control").split()[0].lower()
        seq = 0
        for ev in app.events:
            seq += 1
            doc_id = f"DEMO{app.app_no}{seq:03d}"
            code = out_codes.get(ev.code) or in_codes.get(ev.code)
            if code is None:
                continue
            outgoing = ev.code in out_codes
            history.append((app.app_no, doc_id, code, ev.date.isoformat(), "OUTGOING" if outgoing else "INCOMING"))
            if outgoing and code in ("CTNF", "CTFR"):
                text = _office_action(rng, topic, code == "CTFR")
            elif code == "NOA":
                text = "NOTICE OF ALLOWABILITY\n\nReasons for Allowance: the prior art of record does not teach the " \
                       f"claimed {topic} configuration in combination with the remaining limitations."
            elif code == "CTRS":
                text = "Restriction to one of the following inventions is required under 35 U.S.C. 121."
            elif not outgoing and code in ("A.NE", "AP.B"):
                text = _response(rng, topic, attorney, reg)
            else:
                continue
            docs.append({
                "doc_id": doc_id, "kb": "ex_parte", "app_no": app.app_no, "doc_code": code,
                "doc_desc": doccode_label(code), "direction": "OUTGOING" if outgoing else "INCOMING",
                "mail_date": ev.date.isoformat(), "examiner": app.examiner, "art_unit": app.art_unit,
                "customer_number": customer, "correspondent": firm,
                "filer": None if outgoing else attorney, "filer_reg": None if outgoing else str(reg),
                "pages": rng.randint(3, 30), "text": text,
            })
            # Synthetic responses to each office action keep the history realistic.
            if code in ("CTNF",) and rng.random() < 0.8:
                seq += 1
                rid = f"DEMO{app.app_no}{seq:03d}"
                history.append((app.app_no, rid, "A...", ev.date.isoformat()[:8] + "28", "INCOMING"))
                docs.append({
                    "doc_id": rid, "kb": "ex_parte", "app_no": app.app_no, "doc_code": "A...",
                    "doc_desc": doccode_label("A..."), "direction": "INCOMING",
                    "mail_date": ev.date.isoformat()[:8] + "28", "examiner": app.examiner,
                    "art_unit": app.art_unit, "customer_number": customer, "correspondent": firm,
                    "filer": attorney, "filer_reg": str(reg), "pages": rng.randint(8, 25),
                    "text": _response(rng, topic, attorney, reg),
                })
    return docs, history


def doccode_label(code: str) -> str:
    from .doccodes import label

    return label(code)
