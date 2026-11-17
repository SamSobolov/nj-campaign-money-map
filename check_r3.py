"""Check the parsed reports two independent ways and write data/reconciliation.csv.

Usage: python check_r3.py [scope ...]      (default: every parsed scope)

1. Cover page: each report's parsed schedules against the totals printed on its own cover page.
2. ELEC database: each committee's parsed rows against the itemized rows in ELEC's search database
   (pulled by fetch_elec.py), over the dates the parsed reports cover. The database is a second
   copy of the same filings, so agreement means both are right. It is not used as the source of
   rows because it can lag behind amendments and does not say which schedule a row is on.
"""
import collections
import csv
import json
import os
import sys

from fetch_elec import SCOPES

TOL = 0.005


def cover_checks(r):
    cov, s = r["cover"], collections.Counter()
    for e in r["expenses"]:
        s[e["schedule"]] += e["amount"]
    c1 = sum(c["amount"] for c in r["contributions"] if not c["inKind"])
    c2 = sum(c["amount"] for c in r["contributions"] if c["inKind"])
    return [("Schedule 1 monetary contributions", c1, cov["itemized"]),
            ("Schedule 2 in-kind contributions", c2, cov["inKind"]),
            ("Schedule 8 operating disbursements", s[8], cov["operating"]),
            ("Schedule 9 other expenditures", s[9], cov["other"]),
            ("Schedule 10 contributions made", s[10], cov["toCandidates"]),
            ("Schedule 11 spending on behalf of candidates", s[11], cov["onBehalf"])]


def check_scope(scope, rows, verbose):
    raw = json.load(open(f"data/raw/{scope}.json", encoding="utf-8"))
    parsed = json.load(open(f"data/parsed/{scope}.json", encoding="utf-8"))
    ents = {e["entity"]: e for e in raw["entities"]}
    label = lambda e: f"{e['name']} ({e['location'].title()}, {e['party']}, {e['year']} {e['electionType'].lower()})"

    # 1. each report against its own cover page
    cover_ok = 0
    for r in parsed["reports"]:
        e = ents[r["entity"]]
        checks = cover_checks(r)
        bad = [(m, a, b) for m, a, b in checks if abs(a - b) > 0.5]
        cover_ok += not bad
        for m, a, b in checks:
            rows.append({"scope": scope, "check": "cover page", "committee": e["name"], "location": e["location"],
                         "party": e["party"], "period": r["label"], "filing": r["doc"],
                         "measure": m, "parsed": round(a, 2), "other": round(b, 2), "diff": round(a - b, 2)})
        if bad and verbose:
            print(f"    {label(e)} {r['label']} #{r['doc']}: " +
                  "; ".join(f"{m}: parsed {a:,.2f}, cover {b:,.2f}" for m, a, b in bad))

    # 2. each committee against ELEC's database, over the dates its parsed reports cover
    by_ent = collections.defaultdict(list)
    for r in parsed["reports"]:
        by_ent[r["entity"]].append(r)
    db_ok = db_x_ok = 0
    for eid, reps in by_ent.items():
        e = ents[eid]
        if SCOPES[scope]["pac"]:
            # a party committee gets a new ELEC record each year, so every row belongs to this year's reports
            lo, hi = f"{e['year']}-01-01", f"{e['year']}-12-31"
            inside = lambda d: True
        else:
            # a candidate's record spans years; compare only the dates the parsed rows cover
            dates = [x["date"] for r in reps for x in r["contributions"] + r["expenses"] if x["date"]]
            lo, hi = (min(dates), max(dates)) if dates else ("9999", "0000")
            inside = lambda d: lo <= d[:10] <= hi
        pdf_c = sum(x["amount"] for r in reps for x in r["contributions"] if not x["inKind"] and inside(x["date"]))
        db_c = sum(x["CONT_AMT"] for x in e["contributions"]
                   if x["ContributionType"] in ("MONETARY", "CURRENCY") and inside(x["CONT_DATE"]))
        # ELEC's expense table also holds Schedule 4 refunds to the committee and in-kind items,
        # and leaves out voided checks, so compare like with like. One difference is left in: for a
        # credit card payment or a reimbursement the database lists the sub-payees, the parser the
        # single payment, so the two totals differ whenever the filer's breakdown does not add up.
        pdf_x = sum(x["amount"] for r in reps for x in r["expenses"] if x["amount"] > 0 and inside(x["date"] or lo))
        extra = sum(r["cover"]["refundsIn"] + r["cover"]["inKind"] + r["cover"]["inKindSmall"] for r in reps)
        db_x = sum(x["CK_AMT"] for x in e["expenses"] if inside(x["CK_DATE"]))
        checks = [("itemized monetary contributions", pdf_c, db_c),
                  ("expense rows incl. refunds and in-kind", pdf_x + extra, db_x)]
        bad = [(m, a, b) for m, a, b in checks if abs(a - b) > TOL]
        db_ok += abs(pdf_c - db_c) <= TOL
        db_x_ok += abs(pdf_x + extra - db_x) <= TOL
        for m, a, b in checks:
            rows.append({"scope": scope, "check": "ELEC database", "committee": e["name"], "location": e["location"],
                         "party": e["party"], "period": f"{lo} to {hi}", "filing": "", "measure": m,
                         "parsed": round(a, 2), "other": round(b, 2), "diff": round(a - b, 2)})
        if bad and verbose:
            print(f"    {label(e)}: " + "; ".join(f"{m.split(' incl')[0]}: PDFs {a:,.2f}, database {b:,.2f} ({b - a:+,.2f})"
                                                   for m, a, b in bad))
    n = len(parsed["reports"])
    print(f"{scope}: cover page {cover_ok} of {n} reports match | ELEC database, of {len(by_ent)} committees: "
          f"contributions match for {db_ok}, expenses for {db_x_ok}"
          + (f" | {len(parsed['failed'])} filings failed to parse" if parsed["failed"] else ""))


def main(scopes, verbose):
    rows = []
    for scope in scopes:
        check_scope(scope, rows, verbose)
    with open("data/reconciliation.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("details -> data/reconciliation.csv" + ("" if verbose else "  (add -v to list every mismatch)"))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "-v"]
    main(args or [s for s in SCOPES if os.path.exists(f"data/parsed/{s}.json")], "-v" in sys.argv)
