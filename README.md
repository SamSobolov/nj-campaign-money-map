# NJ Campaign Money Map

An interactive map of New Jersey political party fundraising and spending, built from public filings with the
[New Jersey Election Law Enforcement Commission (ELEC)](https://www.elec.nj.gov).

**Live site:** https://samsobolov.github.io/nj-campaign-money-map/

- Toggle **Democratic / Republican** and **Counties / Legislative Districts** at the top.
- Counties are shaded by **cash on hand** from each committee's latest filing.
- Click a county to see its committee's **contributions** (top contributors, averages, by person, by firm, every
  itemized gift) and **expenditures** (spending by bucket, vendors, every payment).

## Coverage

| Layer | Source | Period | Status |
|---|---|---|---|
| County party committees | ELEC Form R-3 quarterly reports | 2026 Q1–Q2 | Loaded (79 reports) |
| Legislative districts | Candidate and joint committee reports | 2027 primary cycle | Not loaded yet |

No filings were in the data for Hudson GOP, Warren Dem, or Cape May GOP Q1.

## Spreadsheet export

The **Open in Google Sheets** button opens a read-only
[Google Sheet](https://docs.google.com/spreadsheets/d/1doaetJna02isYOS9R2g6OcV0NNnOjLRuRhWxGgUE-eQ/edit?usp=sharing)
with a Summary tab, one tab per committee per quarter (cover-page totals, every contribution, every expenditure),
a Bucket Key and Notes. `python3 export_xlsx.py` rebuilds the workbook
([`docs/nj_campaign_money_export.xlsx`](docs/nj_campaign_money_export.xlsx)); the sheet URL lives in
`data/sheet_url.txt`.

## How the data is built

```
reports/county/*.pdf  ──parse_r3.py──▶  data/county.json  ──build_data.py──▶  data/site_data.json  ──assemble.py──▶  docs/index.html
```

```bash
pip install pdfplumber pyshp
python3 parse_r3.py reports/county data/county.json   # parse every R-3 PDF
python3 check_r3.py                                   # reconcile parsed schedules against each report's cover totals
python3 build_data.py                                 # site data model + spending buckets
python3 assemble.py                                   # write docs/index.html
```

- **Parsing.** `parse_r3.py` reads Schedule 1 (monetary contributions) and Schedule 2 (in-kind) as contributions, and
  Schedules 8, 10 and 11 as expenditures, using each word's position on the page to separate columns. Sub-payee
  breakdowns are skipped so nothing is counted twice. Voided checks are kept as negative amounts, as filed.
- **Amendments.** When a quarter has an original and an amended report, the latest amendment is used.
- **Reconciliation.** 77 of 79 reports match their cover-page totals to the cent. The two Monmouth Democratic reports
  differ by a few hundred dollars because the filer's own candidate allocations don't sum to the checks written; the
  check amounts are shown as filed.
- **Cash on hand** is the report's closing balance; per-account balances come from the Depository Summary.
- **Total raised** includes unitemized contributions ($200 or less) from Table I. Averages and contributor counts use
  itemized contributions only.

## Things to know

- **Contributor types are inferred.** ELEC's R-3 does not label contributors, so Individual / Business / Union-PAC /
  Political committee is inferred from the employer and occupation fields and the name.
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
| `parse_r3.py`, `check_r3.py`, `build_data.py`, `assemble.py` | Data pipeline |
| `data/site_data.json` | Data the site embeds |
| `data/bucket_mapping.csv` | Every ELEC purpose and the bucket it was assigned |
| `reports/county/` | Source ELEC R-3 PDFs, named by ELEC filing number |
| `geo/build_geo.py`, `geo.json` | Map shapes from Census 2023 cartographic boundary files |
| `SPEC.md` | Product spec |
