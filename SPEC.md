# NJ ELEC Finance Map — Spec (interview 2026-10-05)

## Data
- Source: Google Sheet, read live on page load. Phase 2: scrape ELEC directly.
- Period: current year; legislators this cycle (2027 primary).
- Refunds, returns and loans are shown exactly as filed.
- Cash on hand comes from the ELEC report linked in the sheet.
- Spending buckets: a code column on each expense plus a `Key` tab that maps code → bucket.

### Proposed sheet tabs (draft, to confirm)
| Tab | Columns |
|---|---|
| Entities | Entity ID, Entity Name, Type (Candidate / Joint / County Cmte), Party, LD, County, Candidate Name(s) (for joint committees), Report Link, Cash on Hand, As-of Date |
| Contributions | Entity ID, Contributor Name, Contributor Type, Amount, Date, Employer, Occupation, Address, Report Period |
| Expenditures | Entity ID, Vendor, Vendor Address, Amount, Date, Purpose, Bucket Code, Report Period |
| Key | Bucket Code, Bucket Name |

## Layout
- Clickable NJ map with a toggle between the LD layer and the County layer.
- The map is shaded by total raised for the party that is toggled on.
- Clicking a district or county opens a detail panel over the map.
- A permanent Dem/GOP toggle sits at the top. Flipping it keeps the same LD or county open.
- Places with no filings are grayed out and show a "No filings yet" message.
- Style: clean, neutral and data-forward, with Dem blue and GOP red accents.

## Legislative Districts
- Includes candidate election funds and joint candidate committees.
- The switcher lists individual candidates only. There is no combined view.
- Joint committee money is split evenly across its members.

## Counties
- Includes the county party committee only.
- All of the committee's state ELEC accounts are combined. The sheet lists those accounts.
- An optional breakdown shows each account separately.

## Detail panel: Contributions / Expenditures toggle
**Contributions**
- Cash on hand.
- Top contributors: top 10, expandable to show more.
- Average donation, shown two ways: all contributions, and individuals only.
- Number of contributors and number of contributions.
- By person: names are merged only within one scope.
  - A scope is either one LD for one party, or one county.
  - Names are never merged across LDs, across counties, or between an LD and its county.
- By firm: one table with three money columns.
  - Direct $ is what the firm gave itself.
  - Employee $ comes from the Employer field on individual donors.
  - Total $ adds the two together.
- Itemized table columns: Name, Amount, Date, Employer, Occupation, Type.

**Expenditures**
- Pie chart by bucket. Hovering shows $ and %; slices are not clickable.
- Vendor rollup with normalized vendor names:
  - Total paid and number of payments.
  - Bucket.
  - Share of total spend (%).
  - Expandable to list each payment.
- Itemized table columns: Vendor, Amount, Date, Purpose, Bucket, Vendor Address.

**Filters**
- Year and Q1–Q4 filters apply to the itemized tables only.

## Out of scope for now
- Party-vs-party or candidate-vs-candidate comparisons.
- Team notes.
- Donor geography analysis.
- Restricted per-user views.
