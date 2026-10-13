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
    "afcp": ("AFCP", "After Final Consideration Pilot Program Request"),
    "noa": ("N/AP", "Notice of Appeal Filed"),
    "brief": ("AP.B", "Appeal Brief Filed"),
    "answer": ("MEXAN", "Mail Examiner's Answer"),
    "affirmed": ("APDA", "BPAI Decision - Examiner Affirmed"),
    "reversed": ("APDR", "BPAI Decision - Examiner Reversed"),
    "ex_iv": ("EXIN", "Examiner Interview Summary Record (PTOL - 413)"),
    "app_iv": ("ITRQ", "Applicant Initiated Interview Request"),
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
            patent = str(10_000_000 + rng.randint(0, 2_999_999))
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
