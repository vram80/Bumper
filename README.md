# Bumper

Patent examiner statistics computed from public USPTO file-wrapper data:
allowance rates, actions per allowance or abandonment, pendency, appeal and
after-final outcomes, interview effects, and percentile ranks against all
examiners and against the examiner's art unit.

`docs/SITE_ANALYSIS.md` describes the reference site this project was modeled
on and how each metric is defined.

Requires only Python 3.10+. There are no third-party dependencies.

## Quick start (synthetic data)

```bash
python -m bumper demo            # writes bumper.db with fake examiners
python -m bumper serve           # http://127.0.0.1:8000/examiner
```

## Real data

1. Get a free API key at <https://data.uspto.gov/myodp>.
2. Fetch an examiner, along with their home art unit so that ranks have peers:

```bash
export USPTO_API_KEY=...
python -m bumper fetch --examiner "ALMATRAHI, FARIS S" --with-peers
python -m bumper fetch --art-unit 3667          # or fetch whole art units
python -m bumper report "ALMATRAHI, FARIS S"
python -m bumper serve
```

You can also load the ODP Patent File Wrapper bulk JSON files:
`python -m bumper load path/to/json_dir`.

Percentile ranks cover only the examiners in your database. Load every art
unit you care about, or the full bulk dataset, before relying on the "all
examiners" rank.

## Layout

| Path | Contents |
| --- | --- |
| `bumper/uspto.py` | ODP API client and record parser (API and bulk files) |
| `bumper/events.py` | Transaction-event and status classification |
| `bumper/metrics.py` | Statistics, outcome tracing, percentile ranks, chart series |
| `bumper/db.py` | SQLite storage |
| `bumper/web.py` | HTTP server and JSON API |
| `bumper/static/` | Front end (HTML, CSS, JavaScript, Chart.js) |
| `bumper/demo.py` | Synthetic data generator |

### JSON API

| Endpoint | Returns |
| --- | --- |
| `GET /api/examiner?id=LAST, FIRST M` | Report, ranks (all / art unit), chart series, applications |
| `GET /api/artunit?id=3667` | Unit totals and per-examiner summary |
| `GET /api/examiner/suggest?term=` | Name autocomplete |
| `GET /api/artunit/suggest?term=` | Art-unit autocomplete |

## Tests

```bash
python -m unittest discover -s tests -t .
```
