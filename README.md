# NJ Campaign Money Map

An interactive map of New Jersey party and candidate fundraising and spending, built from public filings with the
[New Jersey Election Law Enforcement Commission (ELEC)](https://www.elec.nj.gov).

**Live site:** https://samsobolov.github.io/nj-campaign-money-map/

- Toggle **Democratic / Republican** and **Counties / Legislative Districts** at the top.
- Counties are shaded by the county party committee's **cash on hand**; districts by their candidates' combined cash.
- Click a county to see its party committee's **contributions** (top contributors, averages, by person, by firm, every
  itemized gift) and **expenditures** (spending by bucket, vendors, every payment). The **Show** menu in the panel
  switches to a countywide candidate. In Middlesex it also lists municipal candidates and municipal party committees,
  town by town.
- Click a legislative district to see its Senate and Assembly candidates.

## Coverage

Pulled from ELEC on 2026-11-16. Reports for 2026 onward are loaded (`SINCE` in `fetch_elec.py`).

| Group | Candidates and committees | With itemized reports | Reports loaded |
|---|---|---|---|
| County party committees, 2026 | 42 | 41 | 122 |
| Legislative candidates and their joint committees, 2027 (ELEC lists none from the two parties for 2026) | 162 | 130 | 365 |
| Countywide candidates and their joint committees, 2026 and 2027 | 276 | 157 | 519 |
| Middlesex municipal candidates and their joint committees, 2026 and 2027 | 133 | 57 | 203 |
| Middlesex municipal party committees, 2026 | 49 | 19 | 53 |

- A candidate's primary and general election records are merged into one entry.
- Committees with no itemized report are still listed, with the reason: most filed a sworn statement (Form A-1, A-2
  or A-3) that they will stay under ELEC's reporting threshold.
- Only Democratic and Republican committees are shown; 12 candidate committees of other parties are left out.
- School board, fire district and May municipal elections are not loaded.
- ELEC lists no 2026 R-3 for Warren Dem or for Cape May GOP Q1, and no municipal party committees for 2027 yet.

## Spreadsheet export

The **Open in Google Sheets** button opens a read-only
[Google Sheet](https://docs.google.com/spreadsheets/d/1doaetJna02isYOS9R2g6OcV0NNnOjLRuRhWxGgUE-eQ/edit?usp=sharing)
with a Summary tab, one tab per county party committee per quarter (cover-page totals, every contribution, every
expenditure), a Bucket Key and Notes. Candidates and municipal committees are not in the workbook.
`python export_xlsx.py` rebuilds the workbook
([`docs/nj_campaign_money_export.xlsx`](docs/nj_campaign_money_export.xlsx)); the sheet URL lives in
`data/sheet_url.txt`.

## How the data is built

```
ELEC search site ──fetch_elec.py──▶ data/raw/<group>.json + reports/<folder>/*.pdf
                 ──parse_r3.py────▶ data/parsed/<group>.json
                 ──check_r3.py────▶ data/reconciliation.csv
                 ──build_data.py──▶ data/site_data.json ──assemble.py──▶ docs/index.html
```

```bash
pip install pdfplumber pyshp openpyxl
python fetch_elec.py      # list committees and filings, pull ELEC's database rows, download any missing report PDFs
python parse_r3.py        # parse the latest amendment of each report
python check_r3.py        # reconcile against each cover page and against ELEC's database (-v lists every mismatch)
python build_data.py      # site data model + spending buckets
python assemble.py        # write docs/index.html
python export_xlsx.py     # rebuild the workbook (copy it to docs/ as well)
```

To refresh after a filing deadline, run the six commands in order. Nothing is downloaded by hand. A full fetch makes
several thousand requests at under two a second and takes a little over an hour; `python fetch_elec.py county_party`
(or any other group name, listed at the top of the script) refreshes one group. The first parse of every PDF takes a
few minutes; after that only new filings are parsed.

- **Fetching.** `fetch_elec.py` uses the JSON endpoints behind ELEC's own search pages
  ([njelecefilesearch.com](https://www.njelecefilesearch.com)). It finds committees by ELEC's office and location
  codes, reads each one's filing list, and downloads the report PDFs it does not already have. The endpoints are not
  a documented API, so the script checks the shape of every response and stops if ELEC changes something.
- **Amendments.** ELEC's filing list decides which report counts: the highest amendment number for each period.
  Superseded PDFs stay on disk but are not used.
- **Forms.** Party committees file Form R-3. Candidates and joint candidates committees file Form R-1, either
  quarterly or, in an election year, as 29-day pre-election, 11-day pre-election and 20-day post-election reports.
  The two forms share one layout, so one parser reads both.
- **Parsing.** `parse_r3.py` reads Schedule 1 (monetary contributions) and Schedule 2 (in-kind) as contributions, and
  Schedules 8, 9, 10 and 11 as expenditures, using each word's position on the page to separate columns. Sub-payee
  breakdowns are skipped so nothing is counted twice. Voided checks are kept as negative amounts, as filed.
- **Why the PDFs and not ELEC's database.** The PDF is the filing. ELEC's database is a second copy that lags behind
  amendments (on 2026-11-16 it held none of Hudson Dem's $501,000 in itemized contributions and none of Atlantic
  Dem's Q3), lists refunds paid back to a committee and in-kind items among the expenses without marking them, drops
  voided checks, and carries no balances, bank accounts or schedule numbers. It is used as a cross-check instead.
- **Reconciliation, cover page.** 1,250 of 1,262 reports match their own cover-page totals to the cent:

  | Group | Reports matching their cover page |
  |---|---|
  | County party committees | 118 of 122 |
  | Legislative | 365 of 365 |
  | Countywide | 515 of 519 |
  | Middlesex municipal candidates | 199 of 203 |
  | Middlesex municipal party committees | 53 of 53 |

  Eleven of the twelve misses are on Schedule 11 (spending on behalf of candidates), where the filer's own candidate
  allocations don't sum to the checks written; the other is Burlington GOP Q3, which lists $1,483.72 more on
  Schedule 1 than its cover line. Amounts are shown as filed.
- **Reconciliation, ELEC database.** Itemized contributions match ELEC's database to the cent for 427 of 477
  committees (county parties 36 of 41, legislative 116 of 130, countywide 178 of 204, Middlesex municipal candidates
  80 of 83, Middlesex municipal parties 17 of 19). Expenses match for fewer (365 of 477), mostly because the
  database lists the sub-payees of a credit card payment or reimbursement where the parser keeps the single payment.
  Every comparison is in [`data/reconciliation.csv`](data/reconciliation.csv).
- **Cash on hand** is the closing balance of the latest report; per-account balances come from the Depository Summary.
  When the latest report is a pre- or post-election report, the site names the report instead of giving a date.
- **Total raised** includes unitemized contributions ($200 or less) from Table I. Averages and contributor counts use
  itemized contributions only.

## Things to know

- **Contributor types.** The PDF does not print the contributor type, but ELEC's database has the one the filer
  selected. 20,677 of 21,485 contributions take that type, grouped as Individual / Business / Union-PAC / Political
  committee. The rest (no database row, or the filer left it blank) are inferred from the employer and occupation
  fields and the name.
- **Joint candidates committees** are split evenly across the candidates ELEC links to them, and each candidate's
  view includes that share. A joint committee with no linked candidate is listed by itself.
- **Primary-to-general transfers are not spending.** 56 candidates moved their primary balance into their
  general-election account ($2.2 million in all). That entry is left out of the expenditures; the amount is noted on
  the candidate.
- **Credit card payments and reimbursements** appear as one payment to the card company or person. The vendors behind
  them are on the filer's sub-payee list, which is not loaded yet. For legislative candidates these lines are 5% of
  spending.
- **Spending buckets are provisional.** Each expense is bucketed from ELEC's purpose text. Review the mapping in
  [`data/bucket_mapping.csv`](data/bucket_mapping.csv) and the rules in `build_data.py`. Expenses the filer left
  blank fall into "Other / Unspecified".
- **Name merging** combines spelling variants of the same donor or vendor only within one county and party.
- **Home addresses.** The published site data omits street addresses for individual donors and individual payees.
  The original ELEC PDFs in `reports/` are public records and include them.

## Repository layout

| Path | What it is |
|---|---|
| `docs/index.html` | The built site (served by GitHub Pages) |
| `src.html` | Site source: markup, styles and app code with `__GEO__` / `__DATA__` placeholders |
| `fetch_elec.py`, `parse_r3.py`, `check_r3.py`, `build_data.py`, `assemble.py` | Data pipeline |
| `data/site_data.json` | Data the site embeds |
| `data/reconciliation.csv` | Every check, per report and per committee |
| `data/raw/`, `data/parsed/` | Raw pulls from ELEC and parsed reports, not committed (donor home addresses) |
| `data/bucket_mapping.csv` | Every ELEC purpose and the bucket it was assigned |
| `reports/county/` | County party R-3 PDFs, named by ELEC filing number |
| `reports/legislative/`, `reports/countywide/`, `reports/middlesex/` | Candidate and municipal PDFs, not committed (`fetch_elec.py` re-downloads them) |
| `geo/build_geo.py`, `geo.json` | Map shapes from Census 2023 cartographic boundary files |
| `SPEC.md` | Product spec |
