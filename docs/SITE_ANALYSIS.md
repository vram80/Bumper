# Analysis of the BigPatentData examiner page

Target: `https://app.bigpatentdata.com/Examiner?id=ALMATRAHI%2C+FARIS+S`
Inspected: 2026-10-13, as an anonymous (logged-out) visitor, from public HTML and JavaScript only.

This document records how the site is built and what it computes, so that an
independent implementation can be written from public USPTO data. None of the
site's code, styling, text, images or paywalled data is reused in this
repository.

## 1. Technology stack

| Layer | Observation |
| --- | --- |
| Server | ASP.NET Core MVC (Razor views; `asp-fallback` script/stylesheet tag-helper pattern; `/Account/Login?returnurl=` routes) |
| CDN / edge | Cloudflare (`/cdn-cgi/` email-obfuscation script) |
| Front end | Bootstrap 3.3.7, jQuery 2.2.0, jQuery UI 1.12.1 (autocomplete), Font Awesome 5.0.13, Moment.js 2.22.2, Chart.js 2.7.3 |
| Bundles | `/css/site.min.css`, `/js/site.min.js` (about 18 KB), `/js/ifw.min.js` (about 28 KB), all cache-busted with `?v=<hash>` |
| Telemetry | Google Tag Manager, Azure Application Insights |
| Rendering | Server-side. The statistics are in the initial HTML; the browser only adds autocomplete, tabs, modals and charts. |

## 2. Routes and endpoints

Page routes found in the navigation and scripts:

| Route | Purpose |
| --- | --- |
| `GET /Examiner?id=<LAST, FIRST M>` | Examiner statistics page |
| `GET /artunit` | Art-unit statistics |
| `GET /pairptab` | File-history and PTAB document search |
| `GET /patpubapp` | Patent and publication PDFs and bibliographic data |

XHR endpoints referenced from the JavaScript bundles:

| Endpoint | Purpose |
| --- | --- |
| `GET /examiner/examinersuggest?term=` | Autocomplete; returns a JSON array of names, e.g. `["ALMATRAHI, FARIS S","ALMATRAHI, RAMZI S"]` |
| `GET /artunit/artunitsuggest?term=` | Art-unit autocomplete |
| `POST /examiner/createShareLink` | Paid feature: share a full report |
| `/PairPtab/Lookup`, `/PairPtab/SearchIfwFiles`, `/PairPtab/GetIndexInfo`, `/PairPtab/GetLinkToBlob` | Image file wrapper search and download (documents stored in blob storage) |
| `/PatPubApp/GetPtoPdf/<no>?type=pat\|pub`, `/PatPubApp/GetPatOrPubText/...`, `/PatPubApp/pairfetch`, `/PatPubApp/assignmentfetch` | Patent and publication PDF, text, PAIR and assignment proxies |

Examiner IDs are the USPTO's examiner name string (`LASTNAME, FIRSTNAME M`),
the same value that appears in the `examinerNameText` field of USPTO
file-wrapper data.

## 3. Page layout

1. A search box with autocomplete against `examinersuggest`.
2. Two tabs that show the same statistics ranked against different peer groups:
   **All** examiners, and the examiner's **art unit** (here, 3667). The absolute
   values are identical in both tabs; only the percentile column changes.
3. Statistics panels:
   * **Basic stats (last 3 years)**: allowance rate, actions per allowance,
     actions per abandonment, months to first action, months to first allowance.
     Each panel shows an absolute value and a percentile rank (50% = median examiner).
   * **Paid panels**: appeal stats, after-final response outcomes, AFCP 2.0
     outcomes, pre-appeal request outcomes, appeal brief outcomes,
     examiner-initiated interviews, applicant-initiated interviews, experience.
4. Charts: allowance rates over three years (two canvases), an actions
   scatter plot, and an applications list.
5. A help modal that defines each metric.

### Observed values (anonymous view)

| Metric | Value | Rank (All) | Rank (AU 3667) |
| --- | --- | --- | --- |
| Allowance rate | 14% (1 / 7) | 4% | 3% |
| Actions per allowance | 5.0 | 98% | 100% |
| Actions per abandonment | 2.2 | 41% | 72% |
| Months to 1st action | 18 | 53% | 15% |
| Months to 1st allowance | 38 | 85% | 93% |

The ranks are plain percentiles of the raw value: a low allowance rate gives a
low rank, and many actions per allowance give a high rank. Colour carries the
"harder or easier" meaning, not the direction of the number.

## 4. Free and paid tiers

Paid panels are rendered on the server without their data. The HTML contains
only an upgrade link, and a script opens an "Account Upgrade Required" modal
when the page loads. Chart data is not present for anonymous users either.
The gate is enforced on the server, so the premium numbers cannot be read from
the page. This implementation computes them independently from public data.

## 5. Metric definitions (summarised)

These are the methods the site describes in its help modal, restated in our
own terms. Bumper implements each one in `bumper/metrics.py`.

* **Window**: applications disposed of in the last three years.
* **Allowance rate**: allowed ÷ (allowed + abandoned). Pre-examination
  abandonments are dropped; an abandonment for an unpaid issue fee counts as an
  allowance.
* **Actions per allowance / abandonment**: count of non-final rejections,
  final rejections, restrictions, Ex parte Quayle actions and examiner's answers,
  divided by allowed (or abandoned) applications.
* **Months to first action**: filing or 371(c) date to the first non-final,
  final or allowance.
* **Months to first allowance**: filing or 371(c) date to the first allowance.
  The first allowance is used so that delays outside the examiner's control,
  such as late issue fees or post-allowance RCEs, are left out.
* **PTAB affirmance rate**: full affirmances ÷ board decisions. Affirmed-in-part
  does not count as an affirmance.
* **After-final outcomes**: for each after-final response, whether the next
  decisive event was an RCE, an appeal brief, an allowance, or a new action
  (prosecution reopened). **AFCP 2.0 outcomes** are the same measure limited
  to AFCP requests.
* **Pre-appeal outcomes**: share of requests answered "proceed to board" as
  opposed to reopened or allowed.
* **Appeal brief outcomes**: share of briefs followed by reopened prosecution,
  an examiner's answer or board decision, an allowance, or a defective-brief
  notice.
* **Interviews (examiner- or applicant-initiated)**: number of interviews;
  allowance rate among disposed applications that had one; actions per interview.
* **Experience**: lifetime counts of each action type.

## 6. Data source

All of these figures come from public USPTO file-wrapper data: application
metadata (examiner, art unit, filing and 371 dates, status) and the
transaction history (event code, description, date). That data is available
through:

* the USPTO Open Data Portal API, `https://api.uspto.gov/api/v1/patent/applications/search`
  (free API key, `X-API-KEY` header);
* the ODP "Patent File Wrapper" bulk JSON datasets;
* the USPTO Patent Examination Research Dataset (PatEx), an economics-office
  research extract.

## 7. Open questions

* Whether the time metrics are means or medians. The site does not say; Bumper
  uses means.
* The minimum number of dispositions for an examiner to count in peer ranking.
  Bumper uses 5 (`MIN_DISPOSALS`).
* How the "art unit" peer group is chosen when an examiner has worked in more
  than one unit. Bumper uses the unit holding most of the examiner's applications.
* The exact transaction-code mapping. Bumper's mapping in `bumper/events.py`
  matches on code first and falls back to description text. It should be checked
  against live ODP data once an API key is configured.
