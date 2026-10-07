"""Parse ELEC Form R-3 (political party committee) PDFs into JSON for the map site.

Usage: python3 parse_r3.py reports/county data/county.json

Keeps only 2026 quarterly R-3s from the 21 county committees; when a quarter
has an original and an amendment, the latest-filed one wins.
"""
import glob, json, re, sys
from datetime import datetime
import pdfplumber

COUNTIES = ["Atlantic", "Bergen", "Burlington", "Camden", "Cape May", "Cumberland", "Essex", "Gloucester", "Hudson",
            "Hunterdon", "Mercer", "Middlesex", "Monmouth", "Morris", "Ocean", "Passaic", "Salem", "Somerset", "Sussex",
            "Union", "Warren"]
# committee names as filed that don't spell out the county or party
ALIASES = {"GCGOP": ("Gloucester", "R"), "CCGOP": ("Camden", "R")}

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


def committee_of(name):
    up = name.upper()
    for k, v in ALIASES.items():
        if up.startswith(k):
            return v
    county = next((c for c in COUNTIES if c.upper() in up or (c == "Cape May" and "CAPE MAY" in up)), None)
    party = "D" if "DEMOCRA" in up else "R" if ("REPUBLICAN" in up or "GOP" in up) else None
    return (county, party) if county and party else (None, None)


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


def parse_report(path):
    with pdfplumber.open(path) as pdf:
        pages = [(p.extract_text() or "", page_lines(p)) for p in pdf.pages]
    full = "\n".join(t for t, _ in pages)
    if "FORM R-3" not in full[:400] or not re.search(r"\((\d{4})-Q(\d)\)", full[:600]):
        return None
    year, q = re.search(r"\((\d{4})-Q(\d)\)", full[:600]).groups()
    name = re.search(r"COMMITTEE NAME OR APPROVED ACRONYM\s*\n(.+)", full).group(1).strip()
    filed = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} [AP]M)", full[:800])
    amend = re.search(r"Amendment #(\d+)", full[:900])
    num = lambda label: money(re.search(label + r"[^\$]*(\$[\d,]+\.\d{2})", full).group(1))
    rep = {
        "file": path.split("/")[-1], "committee": name, "year": int(year), "quarter": int(q),
        "filed": filed.group(1) if filed else "", "amendment": int(amend.group(1)) if amend else 0,
        "opening": num(r"OPENING BALANCE"), "receipts": num(r"RECEIPTS \(\+\)"),
        "expenditures": num(r"EXPENDITURES \(-\)"), "closing": num(r"CLOSING BALANCE"),
        "unitemized": num(r"1\. Monetary Contributions, \$\d+ or less"),
        "contributions": [], "expenses": [], "accounts": [],
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
            if line.startswith("New Jersey Election Law Enforcement Commission") or line.startswith("FORM R-3"):
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
            elif sched in (8, 11):
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


def main(src, out):
    reports = []
    for f in sorted(glob.glob(src + "/*.pdf")):
        try:
            r = parse_report(f)
        except Exception as e:  # report the file and keep going
            print("FAILED", f, e); continue
        if not r or r["year"] != 2026:
            continue
        county, party = committee_of(r["committee"])
        if not county:
            print("SKIP (not a county committee)", f, r["committee"]); continue
        r["county"], r["party"] = county, party
        reports.append(r)
    # latest amendment per committee-quarter wins
    best = {}
    for r in reports:
        k = (r["county"], r["party"], r["quarter"])
        if k not in best or (r["amendment"], r["filed"]) > (best[k]["amendment"], best[k]["filed"]):
            best[k] = r
    final = sorted(best.values(), key=lambda r: (r["county"], r["party"], r["quarter"]))
    for r in final:
        for c in r["contributions"]:
            c["type"] = contributor_type(c["name"], c["employer"], c["occupation"])
        ci = sum(c["amount"] for c in r["contributions"])
        ce = sum(e["amount"] for e in r["expenses"])
        print(f'{r["county"]:<11}{r["party"]} Q{r["quarter"]} am{r["amendment"]} contribs {len(r["contributions"]):>4} '
              f'${ci:>12,.2f} (+unitemized ${r["unitemized"]:,.2f}) | expenses {len(r["expenses"]):>4} ${ce:>12,.2f} '
              f'vs filed ${r["expenditures"]:>12,.2f} | COH ${r["closing"]:,.2f}')
    json.dump({"generated": datetime.now().isoformat(timespec="seconds"), "reports": final}, open(out, "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
