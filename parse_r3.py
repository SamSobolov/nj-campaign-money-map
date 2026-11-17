"""Parse ELEC quarterly report PDFs into JSON for the map site.

Usage: python parse_r3.py [scope ...]      (default: every scope fetch_elec.py has saved)

Handles Form R-3 (party committees) and Form R-1 (candidates and joint candidates committees). The
two forms share one layout: the same cover summary and the same numbered schedules.

Reads the filing lists that fetch_elec.py saved (data/raw/<scope>.json) and parses exactly the
filings ELEC lists as the latest amendment of each report. Writes data/parsed/<scope>.json
(gitignored: donor home addresses). Each parsed filing is cached in data/parsed/cache/, since a
filing never changes once it has a filing number.
"""
import json, os, re, sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
import pdfplumber

from fetch_elec import SCOPES, SINCE

DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
MONEY = re.compile(r"^\(?\$[\d,]+\.\d{2}\)?$")
# ELEC prints voids and reversals as ($1,234.56)
money = lambda s: (-1 if s.startswith("(") else 1) * float(s.strip("()").replace("$", "").replace(",", ""))
iso = lambda d: datetime.strptime(d, "%m/%d/%Y").strftime("%Y-%m-%d")


def page_lines(page):
    """Group words into visual lines: [(top, [(x0, text), ...]), ...]"""
    rows = {}
    for w in page.extract_words(keep_blank_chars=False):
        key = round(w["top"])
        # merge words within 2px vertically into the same line
        for k in (key - 1, key + 1, key - 2, key + 2):
            if k in rows:
                key = k
                break
        rows.setdefault(key, []).append((w["x0"], w["text"]))
    return [(t, sorted(ws)) for t, ws in sorted(rows.items())]


def txt(ws, lo=-1, hi=9999):
    return " ".join(t for x, t in ws if lo <= x < hi).strip()


BIZ = re.compile(r"\b(LLC|L\.L\.C|INC|CORP|CORPORATION|CO\b|COMPANY|P\.?C\.?|LLP|P\.?A\.?|PLLC|LTD|GROUP|ASSOC|ASSOCIATES|"
                 r"ENGINEERING|ENGINEERS|LAW|ATTYS|ATTORNEYS|CONSULTING|PARTNERS|ENTERPRISES|SERVICES|HOLDINGS|AGENCY|BANK|"
                 r"CONSTRUCTION|REALTY|MANAGEMENT|INSURANCE|ARCHITECTS|STRATEGIES|SOLUTIONS|INDUSTRIES|DEVELOPMENT|PLLC)\b")
UNION = re.compile(r"\b(LOCAL|UNION|COPE|PAC|BROTHERHOOD|FEDERATION|AFL|CIO|IBEW|AFSCME|LABORERS|CARPENTERS|TEAMSTERS|"
                   r"OPERATING ENGINEERS|PIPEFITTERS|PLUMBERS|ELECTRICAL WORKERS|IRONWORKERS|NJEA|CWA|PBA|FMBA|SEIU|UFCW|"
                   r"AFT|DISTRICT COUNCIL|BUILDING TRADES|EDUCATION ASSOCIATION|POLITICAL ACTION|ACTION FUND|SMART|UA )\b")
POLITICAL = re.compile(r"\b(DEMOCRATIC|REPUBLICAN|DEMOCRATS|REPUBLICANS|GOP|COMMITTEE|FOR SENATE|FOR ASSEMBLY|FOR CONGRESS|"
                       r"FOR FREEHOLDER|FOR COMMISSIONER|FOR MAYOR|FOR COUNCIL|ELECTION FUND|FRIENDS OF|CITIZENS FOR|"
                       r"VICTORY|ORGANIZATION|CLUB)\b")


def contributor_type(name, employer, occupation):
    up = name.upper()
    if "CONTRIBUTORS UNDER" in up or "MULTIPLE" == up.split(",")[-1].strip():
        return "Small-dollar group"
    if employer or occupation:
        return "Individual"
    if UNION.search(up):
        return "Union/PAC"
    if POLITICAL.search(up):
        return "Political committee"
    if BIZ.search(up):
        return "Business"
    # "LAST, FIRST" with no business words reads as a person
    if re.match(r"^[A-Z'\-\. ]+,\s*[A-Z]", up) and len(up.split()) <= 5:
        return "Individual"
    return "Business"


QEND = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
PERIOD_NAMES = {"Pre29": "29-day pre-election", "Pre11": "11-day pre-election", "Post20": "20-day post-election"}
# Rough distance from election day to the end of each election report's period. Used only to put a
# committee's reports in order; the site never shows a date derived from it.
PERIOD_OFFSET = {"Pre29": -32, "Pre11": -14, "Post20": 17}


def period_label(r):
    if r["quarter"]:
        return f"{r['year']} Q{r['quarter']}"
    return f"{PERIOD_NAMES[r['period']]} report, {r['electionType'].lower()} {r['year']}".replace("  ", " ")


def period_order(r):
    """Sortable ISO date for ordering a committee's reports."""
    if r["quarter"] or not r["electionDate"]:
        return f"{r['year']}-{QEND[r['quarter'] or 4]}"
    return (datetime.strptime(r["electionDate"], "%Y-%m-%d") + timedelta(days=PERIOD_OFFSET[r["period"]])).strftime("%Y-%m-%d")


def parse_report(path):
    with pdfplumber.open(path) as pdf:
        pages = [(p.extract_text() or "", page_lines(p)) for p in pdf.pages]
    full = "\n".join(t for t, _ in pages)
    form = re.search(r"FORM (R-[13])\b", full[:400])
    # report period as ELEC prints it: (2026-Q1), or for a candidate's election reports
    # (2026-Pre29), (2026-Pre11), (2026-Post20)
    per = re.search(r"\((\d{4})-(Q[1-4]|Pre29|Pre11|Post20)\)", full[:600])
    if not form or not per:
        return None
    year, period = per.groups()
    q = period[1] if period[0] == "Q" else 0
    election = re.search(r"ELECTION DATE ELECTION TYPE\s*\n(\d{2}/\d{2}/\d{4}) +([A-Z][^\n]*)", full[:1600])
    name = re.search(r"(?:COMMITTEE NAME OR APPROVED ACRONYM|CANDIDATE OR COMMITTEE NAME)\s*\n(.+)", full).group(1).strip()
    filed = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} [AP]M)", full[:800])
    amend = re.search(r"Amendment #(\d+)", full[:900])
    # a negative balance prints in parentheses
    num = lambda label: money(re.search(label + r"[^\$(]*(\(?\$[\d,]+\.\d{2}\)?)", full).group(1))
    rep = {
        "file": path.split("/")[-1], "form": form.group(1), "committee": name, "year": int(year), "quarter": int(q),
        "period": period, "electionDate": iso(election.group(1)) if election else "",
        "electionType": election.group(2).strip() if election else "",
        "filed": filed.group(1) if filed else "", "amendment": int(amend.group(1)) if amend else 0,
        "opening": num(r"OPENING BALANCE"), "receipts": num(r"RECEIPTS \(\+\)"),
        "expenditures": num(r"EXPENDITURES \(-\)"), "closing": num(r"CLOSING BALANCE"),
        "unitemized": num(r"1\. Monetary Contributions, \$\d+ or less"),
        "contributions": [], "expenses": [], "accounts": [],
    }

    def line(label, optional=False):
        # Table I / II, column A: the amount follows the label, sometimes after a wrapped line
        m = re.search(label + r"[\s\S]{0,160}?(\(?\$[\d,]+\.\d{2}\)?)", full)
        if not m and not optional:
            raise ValueError(f"cover page has no line matching {label!r}")
        return money(m.group(1)) if m else 0.0

    # cover-page totals that check_r3.py reconciles the schedules against
    rep["cover"] = {
        "itemized": line(r"2\. Monetary Contributions \(In Excess"),
        "inKindSmall": line(r"3\. In-kind contributions, \$\d+ or less"),
        "inKind": line(r"4\. In-kind contributions, more than"),
        "refundsIn": line(r"6\. Refunded Disbursements"),
        "operating": line(r"1\. Operating Disbursement"),
        "other": line(r"1a\. Other Expenditures", optional=True),      # Schedule 9, on Form R-1 only
        "toCandidates": line(r"2a\. NJ Gub") + line(r"2b\. NJ Leg") + line(r"2c\. All other"),
        "onBehalf": line(r"3a\. NJ Gub") + line(r"3b\. NJ Leg") + line(r"3c\. All other") + line(r"3d\. Indep"),
    }
    # per-account balances from the Depository Summary
    for m in re.finditer(r"Account Name Asset Type\s*\n([^\n]+)\n(?:.*\n){0,8}?.*?(\*{4}\d{4})\s*\n"
                         r"Opening Balance Deposits Disbursements Closing Balance\s*\n"
                         r"(\(?\$[\d,.]+\)?) (\(?\$[\d,.]+\)?) (\(?\$[\d,.]+\)?) (\(?\$[\d,.]+\)?)", full):
        rep["accounts"].append({"name": re.sub(r"\s+(Depository|Investment|Other)\b.*$", "", m.group(1)).strip(), "number": m.group(2),
                                "opening": money(m.group(3)), "deposits": money(m.group(4)),
                                "disbursements": money(m.group(5)), "closing": money(m.group(6))})
    sched, account = None, ""
    cur = None          # entry being built
    mode = None         # sub-state inside an entry
    skip = False        # inside a sub-payee list or allocation table

    def flush():
        nonlocal cur
        if cur:
            if cur.get("kind") == "c" and cur.get("amount") is not None:
                c = cur
                rep["contributions"].append({
                    "name": c["name"].strip(), "address": c.get("address", "").strip(),
                    "employer": c.get("employer", "").strip(), "employerAddress": c.get("employerAddress", "").strip(),
                    "occupation": c.get("occupation", "").strip(), "date": c["date"], "amount": c["amount"],
                    "inKind": c.get("inKind", False), "description": c.get("description", "").strip(),
                    "account": account,
                })
            elif cur.get("kind") == "e" and cur.get("amount") is not None:
                e = cur
                rep["expenses"].append({
                    "vendor": e["name"].strip(), "address": e.get("address", "").strip(), "date": e["date"],
                    "amount": e["amount"], "purpose": e.get("purpose", "").strip(" -"), "schedule": e["sched"],
                    "check": e.get("check", ""), "account": account,
                })
        cur = None

    for text, lines in pages:
        for top, ws in lines:
            line = txt(ws)
            m = re.match(r"^SCHEDULE (\d+)\b", line)
            if m:
                # the schedule header repeats on every page; only a new schedule ends the open entry
                if int(m.group(1)) != sched:
                    flush(); sched = int(m.group(1)); skip = False; mode = None
                continue
            if line.startswith("New Jersey Election Law Enforcement Commission") or line.startswith("FORM R-"):
                continue
            if line.startswith("Account:"):
                flush(); account = re.sub(r"^Account:\s*", "", line).strip(); continue
            if sched in (1, 2):
                if "Currency Contribution" in line or line.startswith("Contributor Name"):
                    if line.startswith("Contributor Name"):
                        flush(); cur = {"kind": "c", "name": "", "address": "", "inKind": sched == 2}; mode = "name"
                    continue
                if not cur:
                    continue
                if line.startswith("Employer Name"):
                    mode = "employer"; continue
                if line.startswith("Occupation"):
                    mode = "occupation"; rest = line[len("Occupation"):].strip()
                    if rest: cur["occupation"] = rest
                    continue
                if line.startswith("Date Received"):
                    mode = "date"; continue
                if line.startswith("GRAND TOTAL") or line.startswith("Comments"):
                    mode = None; continue
                if mode == "date":
                    dates = [t for x, t in ws if DATE.match(t)]
                    amts = [t for x, t in ws if MONEY.match(t)]
                    if dates and amts:
                        cur["date"] = iso(dates[0]); cur["amount"] = money(amts[0])
                        if sched == 2:
                            cur["description"] = txt(ws, 315)
                        mode = None
                    continue
                if mode == "name":
                    n, a = txt(ws, -1, 312), txt(ws, 312)
                    cur["name"] += (" " if cur["name"] and n else "") + n
                    cur["address"] += (" " if cur["address"] and a else "") + a
                elif mode == "employer":
                    n, a = txt(ws, -1, 312), txt(ws, 312)
                    cur["employer"] = (cur.get("employer", "") + " " + n).strip()
                    cur["employerAddress"] = (cur.get("employerAddress", "") + " " + a).strip()
                elif mode == "occupation":
                    cur["occupation"] = (cur.get("occupation", "") + " " + line).strip()
            elif sched in (8, 9, 11):      # Schedule 9 (other expenses, Form R-1 only) is laid out like Schedule 8
                if line.startswith("Sub Payee List") or line.startswith("ALLOCATION OF EXPENDITURES"):
                    skip = True; continue
                if line.startswith("Check No") or line.startswith("Check"):
                    if line.startswith("Check No") or (line.startswith("Check") and "Payee" in line):
                        flush(); skip = False; mode = "head"
                    continue
                if skip or line.startswith("Payee Name") or line.startswith("Date Disbursed") or "Disbursed" == line.strip():
                    continue
                if line.startswith("Total Disbursements") or line.startswith("Total "):
                    flush(); mode = None; continue
                dates = [(x, t) for x, t in ws if DATE.match(t)]
                amts = [(x, t) for x, t in ws if MONEY.match(t)]
                if mode == "head" and amts and (dates or money(amts[-1][1]) < 0):
                    # payee name sits between the check-number column and the balance/date columns
                    name_lo = 85
                    check = txt(ws, -1, name_lo)
                    name = txt([(x, t) for x, t in ws if not DATE.match(t) and not MONEY.match(t)], name_lo, 390)
                    cur = {"kind": "e", "sched": sched, "check": check, "name": name, "address": "",
                           "date": iso(dates[-1][1]) if dates else (rep["expenses"][-1]["date"] if rep["expenses"] else ""),
                           "amount": money(amts[-1][1])}
                    mode = "addr"; continue
                if cur and re.match(r"^Purpose:?\b", line):
                    p = txt(ws, -1, 340)
                    cur["purpose"] = re.sub(r"^Purpose:?\s*", "", p)
                    mode = "purpose"; continue
                if cur and mode == "addr":
                    cur["address"] = (cur["address"] + " " + txt(ws, 85, 420)).strip(); continue
                if cur and mode == "purpose" and not line.startswith("Comments"):
                    extra = txt(ws, 85, 340)
                    if extra and extra.isupper() and len(extra) < 40 and not DATE.match(extra.split()[0]):
                        cur["purpose"] = (cur["purpose"] + " " + extra).strip()
                    mode = None
            elif sched == 10:
                if line.startswith("Date") or line.startswith("Recipient") or line.startswith("Office:"):
                    continue
                if line.startswith("Comments") or line.startswith("Total"):
                    flush(); mode = None; continue
                first = ws[0][1] if ws else ""
                amts = [(x, t) for x, t in ws if MONEY.match(t)]
                if DATE.match(first) and amts:
                    flush()
                    cur = {"kind": "e", "sched": 10, "name": txt(ws, 85, 270), "address": "", "date": iso(first),
                           "amount": money(amts[0][1]), "purpose": "CONTRIBUTION TO CANDIDATE/COMMITTEE",
                           "check": txt(ws, 335, 420)}
                    mode = "name"; continue
                if cur:
                    part = txt(ws, 85, 270)
                    if not part:
                        continue
                    if mode == "name" and not re.match(r"^(\d|P\.?O\.?\s|PO\b|BOX\b)", part):
                        cur["name"] += " " + part
                    else:
                        mode = "addr"; cur["address"] = (cur["address"] + " " + part).strip()
    flush()
    return rep


def parse_to_cache(job):
    """Parse one filing and save it. Returns (doc, error or None). Runs in a worker process."""
    folder, doc = job
    try:
        r = parse_report(f"{folder}/{doc}.pdf")     # None for a PDF that is not a quarterly R-1/R-3
        if r:
            for c in r["contributions"]:
                c["type"] = contributor_type(c["name"], c["employer"], c["occupation"])
        json.dump(r, open(f"data/parsed/cache/{doc}.json", "w", encoding="utf-8"))
        return doc, None
    except Exception as err:      # name the filing and keep going; check_r3.py reports the gap
        return doc, repr(err)[:120]


def main(scopes):
    os.makedirs("data/parsed/cache", exist_ok=True)
    for scope in scopes:
        raw = json.load(open(f"data/raw/{scope}.json", encoding="utf-8"))
        todo = [(e, doc) for e in raw["entities"] for doc in e["reports"]]
        new = sorted({(raw["pdfs"], doc) for _, doc in todo if not os.path.exists(f"data/parsed/cache/{doc}.json")})
        errors = {}
        if new:     # PDF text extraction is slow, so spread new filings across the CPU cores
            with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1)) as pool:
                for i, (doc, err) in enumerate(pool.map(parse_to_cache, new, chunksize=4), 1):
                    if err:
                        errors[doc] = err
                    if i % 100 == 0:
                        print(f"  {scope}: {i}/{len(new)} new filings parsed", flush=True)
        final, skipped, failed = [], [], []
        for e, doc in todo:
            if doc in errors:
                failed.append((doc, e["name"], errors[doc]))
                continue
            r = json.load(open(f"data/parsed/cache/{doc}.json", encoding="utf-8"))
            if not r or r["year"] < SINCE:
                skipped.append(doc)
                continue
            r["entity"], r["doc"] = e["entity"], doc
            r["label"], r["order"] = period_label(r), period_order(r)
            final.append(r)
        # one report per committee and period: ELEC can list the same quarter under two form names
        best = {}
        for r in final:
            k = (r["entity"], r["year"], r["period"], r["electionDate"])
            if k not in best or (r["amendment"], r["doc"]) > (best[k]["amendment"], best[k]["doc"]):
                best[k] = r
        final = sorted(best.values(), key=lambda r: (r["entity"], r["order"]))
        out = f"data/parsed/{scope}.json"
        json.dump({"generated": datetime.now().isoformat(timespec="seconds"), "scope": scope, "fetched": raw["fetched"],
                   "reports": final, "failed": failed}, open(out, "w", encoding="utf-8"))
        print(f"{scope}: {len(final)} reports parsed -> {out}" +
              (f" | {len(skipped)} skipped (before {SINCE}, or not a period this parser knows)" if skipped else "") +
              (f" | {len(failed)} FAILED" if failed else ""))
        for doc, name, err in failed:
            print(f"  FAILED filing {doc} ({name}): {err}")


if __name__ == "__main__":
    have = [s for s in SCOPES if os.path.exists(f"data/raw/{s}.json")]
    main(sys.argv[1:] or have)
