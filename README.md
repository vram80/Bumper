# Bumper

Patent prosecution research tools built on public USPTO data (with the EPO's
Open Patent Services for patent families and backup PDFs):

* **Search** (`/search`, the home page): full-text search over office actions,
  responses, appeal papers and PTAB documents, with facet filters, highlighted
  excerpts, previous and next action tracing, and Text, Details, PDF and Word views.
* **Lookup** (`/lookup`): enter a patent, publication or application number
  to see bibliographic data, inventors, transaction history, file-history
  documents (PDF), assignments, patent family, and the patent or
  publication PDF and text.
* **Examiners** (`/examiner`) and **Art Units** (`/artunit`): allowance
  rates, actions per allowance, pendency, appeal and after-final outcomes,
  interview effects, and percentile ranks.

`docs/SITE_ANALYSIS.md` describes the reference site and how each feature and
metric maps to this code. Requires Python 3.10+ with no third-party packages.
`pdftotext` (poppler-utils) is used for PDF text, `pdfunite` for EPO page
assembly, and `tesseract` for OCR if it is installed.

## Quick start (synthetic data, no keys)

```bash
python -m bumper demo        # fake examiners, applications and documents
python -m bumper serve       # http://127.0.0.1:8000/
```

## Real data

| Variable | Used for | Get it |
| --- | --- | --- |
| `USPTO_API_KEY` | Applications, documents, assignments, PTAB | <https://data.uspto.gov/myodp> (free) |
| `EPO_OPS_KEY`, `EPO_OPS_SECRET` | Patent family, backup PDFs | <https://developers.epo.org> (free tier) |

```bash
# Examiner statistics
python -m bumper fetch --examiner "ALMATRAHI, FARIS S" --with-peers
python -m bumper report "ALMATRAHI, FARIS S"

# Document search index
python -m bumper docs fetch --app 16123456                # one application
python -m bumper docs fetch --sample 500 --art-unit 3667  # random sample from the database
python -m bumper docs ptab IPR2023-00001                  # PTAB trial documents
python -m bumper docs files ~/firm-files --kb firm        # private collection of local PDF/DOCX/TXT

# Patent and publication full text (weekly ipg*/ipa* files from the ODP bulk datasets)
python -m bumper fulltext load ~/downloads/ipg260106.zip

python -m bumper serve
```

Without `USPTO_API_KEY`, Lookup shows whatever is stored locally, and patent
and publication PDFs still come from the USPTO's public PDF service. Downloaded
PDFs are cached under `--data-dir` (default `./data`).

## Search syntax

`+required`, `-excluded`, `a OR b`, `"exact phrase"`, `"near words"~10`,
`prefix*`, `fuzzy~`, `( grouping )`, and filters such as `examiner:`, `artunit:`,
`customer:`, `code:`, `app:`, `filer:`, `prev_out:`, `next_out:`, `prev_in:`,
`next_in:` and `year:`. Separate several values with `|`. For example,
`code:A.NE next_out:NOA` finds after-final responses that were followed by an allowance.

## Layout

| Path | Contents |
| --- | --- |
| `bumper/uspto.py` | ODP API client (applications, documents, assignments, downloads) and public patent PDFs |
| `bumper/epo.py` | EPO OPS client (INPADOC family, page images joined into a PDF) |
| `bumper/lookup.py` | Lookup: number normalisation, bibliographic data, documents, assignments, family, PDFs, text |
| `bumper/search.py` | FTS5 index, query parser, facets, snippets, action tracing |
| `bumper/docindex.py` | Index builders: USPTO file wrappers, local files, PTAB |
| `bumper/fulltext.py` | USPTO weekly full-text XML loader |
| `bumper/textextract.py` | XML, Word and PDF (and OCR) text extraction; .docx export |
| `bumper/doccodes.py` | USPTO document codes and filter groups |
| `bumper/events.py`, `bumper/metrics.py` | Examiner statistics |
| `bumper/db.py` | SQLite storage |
| `bumper/web.py`, `bumper/static/` | HTTP server, JSON API, front end |
| `bumper/demo.py` | Synthetic data |

## Tests

```bash
python -m unittest discover -s tests -t .
```
