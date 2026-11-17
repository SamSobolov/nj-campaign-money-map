"""Fetch committees, filings and report PDFs from ELEC's search site (njelecefilesearch.com).

Usage: python fetch_elec.py [scope ...]      (default: every scope)

Scopes
  county_party     the 42 county party committees, 2026               (Form R-3)
  legislative      Senate and Assembly candidates, 2026 and 2027      (Form R-1)
  countywide       commissioner, sheriff, clerk, surrogate, register
                   and county executive candidates, 2026 and 2027     (Form R-1)
  middlesex_muni   mayor and municipal candidates in Middlesex County (Form R-1)
  middlesex_party  municipal party committees in Middlesex County     (Form R-3)

Candidate scopes also take the joint candidates committees at the same level.

For each scope this writes data/raw/<scope>.json (gitignored: it holds donor home addresses) and
downloads, into reports/<folder>/, the PDF of the latest amendment of every report since SINCE.
Finished committees are cached in data/raw/cache/ for CACHE_HOURS, so a run that stops can simply
be started again.

The endpoints are the ones ELEC's own search pages call. They are not a documented API, so every
response is shape-checked and the script stops loudly if ELEC changes something.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BASE = "https://www.njelecefilesearch.com"
UA = "Mozilla/5.0 (compatible; elec-fetch)"
PAUSE = 0.6      # seconds between requests
SINCE = 2026     # earliest report year to load
CACHE_HOURS = 20  # a committee fetched more recently than this is not fetched again
MIDDLESEX = ",".join(str(c) for c in range(1201, 1226))   # ELEC location codes of its 25 municipalities

SCOPES = {
    "county_party": {"years": [2026], "pac": True, "offices": ["N", "O"], "where": "county", "pdfs": "reports/county"},
    "legislative": {"years": [2026, 2027], "pac": False, "offices": ["1", "2", "E"], "where": "ld",
                    "pdfs": "reports/legislative"},
    "countywide": {"years": [2026, 2027], "pac": False, "offices": ["3", "4", "5", "6", "7", "8", "E"],
                   "where": "county", "pdfs": "reports/countywide"},
    "middlesex_muni": {"years": [2026, 2027], "pac": False, "offices": ["9", "G", "E"], "where": "middlesex",
                       "pdfs": "reports/middlesex"},
    "middlesex_party": {"years": [2026, 2027], "pac": True, "offices": ["H", "I"], "where": "middlesex",
                        "pdfs": "reports/middlesex"},
}
PARTY = {"DEMOCRAT": "D", "REPUBLICAN": "R"}

CONT_COLS = [("CONTRIBUTOR", "CONTRIBUTOR"), ("Address", "STREET1"), ("EMP_NAME", "EMP_NAME"),
             ("EmployerAddress", "EMP_STREET1"), ("OccupationName", "OccupationName"), ("CAND_NAME", "CAND_NAME"),
             ("ContributorType", "ContributorType"), ("ContributionType", "ContributionType"),
             ("CONT_DATE", "CONT_DATE"), ("CONT_AMT", "CONT_AMT"), ("CONTRIB_S", "CONTRIB_S")]
EXP_COLS = [("PAYEE", "PAYEE"), ("Address", "STREET1"), ("CAND_NAME", "CAND_NAME"), ("EXPENSE_DESC", "EXPENSE_DESC"),
            ("PAYEE_TYPE", "PAYEE_TYPE"), ("CHECK_NUM", "CHECK_NUM"), ("CK_DATE", "CK_DATE"), ("CK_AMT", "CK_AMT"),
            ("ENTITY_S", "ENTITY_S")]
ENT_COLS = [(c, c) for c in ("ENTITYNAME", "LOCATION", "OFFICE", "PARTY", "ELECTIONTYPE", "ELECTIONYEAR")]

_last = [0.0]


def http(url, data=None, binary=False, tries=4):
    for attempt in range(tries):
        wait = PAUSE - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, data=data)
        req.add_header("User-Agent", UA)
        req.add_header("X-Requested-With", "XMLHttpRequest")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read()
            _last[0] = time.time()
            return body if binary else body.decode("utf-8")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            _last[0] = time.time()
            if attempt == tries - 1:
                sys.exit(f"ELEC request failed after {tries} tries: {url.split('?')[0]} ({e}). Run again to resume.")
            time.sleep(10 * (attempt + 1))


def api(path, params, post=False):
    q = urllib.parse.urlencode(params)
    body = http(BASE + path, q.encode()) if post else http(f"{BASE}{path}?{q}")
    try:
        return json.loads(body)
    except ValueError:
        sys.exit(f"ELEC returned something that is not JSON from {path}: {body[:200]!r}")


def need(rows, keys, what):
    """Stop if ELEC renamed or dropped a field we depend on."""
    if rows and not set(keys) <= set(rows[0]):
        sys.exit(f"ELEC changed the shape of {what}: missing {sorted(set(keys) - set(rows[0]))}")
    return rows


def table(path, cols, extra, page=500):
    """Page through one of the site's DataTables endpoints."""
    rows, start = [], 0
    while True:
        p = {"draw": "1", "start": str(start), "length": str(page), "search[value]": "", "search[regex]": "false"}
        for i, (d, n) in enumerate(cols):
            p.update({f"columns[{i}][data]": d, f"columns[{i}][name]": n, f"columns[{i}][searchable]": "true",
                      f"columns[{i}][orderable]": "true", f"columns[{i}][search][value]": "",
                      f"columns[{i}][search][regex]": "false"})
        p.update(extra)
        d = api(path, p, post=True)
        if "data" not in d or "recordsTotal" not in d:
            sys.exit(f"ELEC changed the shape of {path}: {list(d)[:8]}")
        rows += d["data"]
        start += len(d["data"])
        if not d["data"] or start >= d["recordsTotal"]:
            if len(rows) != d["recordsTotal"]:
                sys.exit(f"{path}: got {len(rows)} rows but ELEC reports {d['recordsTotal']}")
            return rows


def list_entities(scope):
    """Every committee ELEC lists for a scope, as rows of its entity search."""
    s, out = SCOPES[scope], []
    for year in s["years"]:
        for office in s["offices"]:
            q = {"PACOnly" if s["pac"] else "NONPACOnly": "true", "PACName": "", "OfficeCodes": office, "PartyCodes": "",
                 "LocationCodes": MIDDLESEX if s["where"] == "middlesex" else "", "ElectionTypeCodes": "",
                 "ElectionYears": str(year), "SortColumn": "", "SortBy": "", "FirstName": "", "LastName": "",
                 "MI": "", "Suffix": "", "NonIndName": ""}
            for e in need(table("/api/VWEntity/Entities20", ENT_COLS, q),
                          ["ENTITY_S", "ENTITYNAME", "LOCATION", "OFFICE", "PARTY", "ELECTIONTYPE"], "the committee list"):
                loc = e["LOCATION"].strip()
                if s["where"] == "county" and not loc.endswith(" COUNTY"):
                    continue
                if s["where"] == "ld" and "LEGISLATIVE DISTRICT" not in loc:
                    continue
                if s["where"] == "middlesex" and e["ELECTIONTYPE"] not in ("PRIMARY", "GENERAL", "PAC"):
                    continue    # school board, fire district and May elections are out of scope
                e["officeCode"], e["year"] = office, year
                out.append(e)
    return out


def pick_reports(filings, pac):
    """The latest amendment of each detailed report: R-3 for party committees, R-1 (ELEC lists the
    off-year quarterlies as RQ-<year>) for candidates."""
    best = {}
    for f in filings:
        form = f["FormName"]
        if pac:
            ok = form == "R-3"
        else:
            ok = (form == "R-1" and f["DATE_RECEIVED"][:4] >= str(SINCE)) or \
                 (form.startswith("RQ-") and form[3:].isdigit() and int(form[3:]) >= SINCE)
        if not ok or not f["DOCID"]:
            continue
        k = (form, f["PERIOD"])
        if k not in best or (f["AMEND_NO"], f["DATE_RECEIVED"]) > (best[k]["AMEND_NO"], best[k]["DATE_RECEIVED"]):
            best[k] = f
    return [best[k] for k in sorted(best)]


def download_pdf(doc_id, folder):
    path = f"{folder}/{doc_id}.pdf"
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return False
    link = api("/SearchCandidateReports/", {"handler": "DownloadReport", "DocId": doc_id}).get("FileNameWithSAS")
    if not link:
        sys.exit(f"ELEC gave no download link for filing {doc_id}")
    body = http(link, binary=True)
    if not body.startswith(b"%PDF"):
        sys.exit(f"Filing {doc_id} did not download as a PDF")
    with open(path, "wb") as f:
        f.write(body)
    return True


def fetch_entity(e, scope):
    s = SCOPES[scope]
    eid = e["ENTITY_S"]
    filings = need(api("/api/VWEntity/GetEntityFilingData", {"ENTITY_S": eid, "EntityOnly": "true"}),
                   ["DOCID", "FormName", "PERIOD", "AMEND_NO", "DATE_RECEIVED", "AMT_REC", "AMT_DISB"], "the filing list")
    chosen = pick_reports(filings, s["pac"])
    joint = None
    if not s["pac"] and e["officeCode"] != "E":
        # a candidate who files through a joint candidates committee: ELEC returns that committee second
        both = api("/api/VWEntity/GetEntityDataWithCommittee", {"ENTITY_S": eid})
        joint = both[1]["ENTITY_S"] if len(both) > 1 else None
    cont = exp = []
    if chosen:      # ELEC's database rows are only needed as a cross-check on parsed reports
        cont = need(table("/api/VWContributionDetail/GetContBitsDataByObject", CONT_COLS, {"ENTITY_S": eid}),
                    ["CONTRIBUTOR", "CONT_DATE", "CONT_AMT", "ContributorType", "ContributionType"], "contributions")
        exp = need(table("/api/VWExpenseDetail/GetBitsDataByObject", EXP_COLS, {"ENTITY_S": eid}),
                   ["PAYEE", "CK_DATE", "CK_AMT", "EXPENSE_DESC", "PAYEE_TYPE"], "expenses")
    new = sum(download_pdf(f["DOCID"], s["pdfs"]) for f in chosen)
    return {"entity": eid, "name": e["ENTITYNAME"].strip(), "office": e["OFFICE"].strip(), "officeCode": e["officeCode"],
            "party": PARTY.get(e["PARTY"].strip(), e["PARTY"].strip()), "location": e["LOCATION"].strip(),
            "year": e["year"], "electionType": e["ELECTIONTYPE"].strip(), "joint": joint, "filings": filings,
            "reports": [f["DOCID"] for f in chosen], "contributions": cont, "expenses": exp, "newPdfs": new}


def main(scopes):
    os.makedirs("data/raw/cache", exist_ok=True)
    for scope in scopes:
        s = SCOPES[scope]
        os.makedirs(s["pdfs"], exist_ok=True)
        ents = list_entities(scope)
        print(f"{scope}: {len(ents)} committees listed by ELEC")
        done, new = [], 0
        for i, e in enumerate(sorted(ents, key=lambda e: (e["LOCATION"], e["ENTITYNAME"], e["ENTITY_S"])), 1):
            cache = f"data/raw/cache/{scope}_{e['ENTITY_S']}.json"
            if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < CACHE_HOURS * 3600:
                rec = json.load(open(cache, encoding="utf-8"))
                for d in rec["reports"]:      # a cached committee still needs its PDFs on disk
                    new += download_pdf(d, s["pdfs"])
            else:
                rec = fetch_entity(e, scope)
                new += rec.pop("newPdfs")
                with open(cache, "w", encoding="utf-8") as f:
                    json.dump(rec, f)
            rec.pop("newPdfs", None)
            done.append(rec)
            if i % 25 == 0 or i == len(ents):
                print(f"  {i}/{len(ents)} committees, {sum(len(r['reports']) for r in done)} reports, {new} new PDFs", flush=True)
        out = f"data/raw/{scope}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"fetched": datetime.now().isoformat(timespec="seconds"), "scope": scope, "since": SINCE,
                       "pdfs": s["pdfs"], "entities": done}, f)
        print(f"{scope}: {len(done)} committees, {sum(1 for r in done if r['reports'])} with detailed reports -> {out}")


if __name__ == "__main__":
    bad = [a for a in sys.argv[1:] if a not in SCOPES]
    if bad:
        sys.exit(f"Unknown scope {bad}. Choose from: {', '.join(SCOPES)}")
    main(sys.argv[1:] or list(SCOPES))
