"""Turn the parsed reports (data/parsed/<scope>.json) into the site's data model (data/site_data.json).

Usage: python build_data.py

What the site gets
  committees     the county party committees, one per county and party, with their filings
  entities       one per county-party bank account, plus one per candidate, joint candidates
                 committee and municipal party committee
  contributions, expenditures     itemized rows, each tied to an entity

Spending buckets are assigned from ELEC's purpose text until the team's own key codes arrive;
BUCKET_RULES below is the mapping to review.

Contributor types: the PDF does not print the contributor type the filer selected, but ELEC's
search database has it. Each parsed contribution is matched to its database row (same committee,
date and amount, then name) and takes ELEC's type; rows with no match keep the inferred type.
"""
import collections, csv, json, os, re

from fetch_elec import SCOPES, SINCE
from parse_r3 import contributor_type

KEY = {
    "M": "Mail",
    "P": "Print & Signs",
    "D": "Digital",
    "T": "TV & Radio",
    "S": "Staff & Consultants",
    "X": "Transfers & Contributions",
    "O": "Overhead, Events & Fees",
    "U": "Other / Unspecified",
}
# first match wins; applied to ELEC's category (text before " - ") and then to the full purpose
BUCKET_RULES = [
    ("X", r"CONTRIBUTION|DONATION|CHARIT|IN MEMORIAM|CONDOLENCE|SPONSOR|LOAN PAYMENT"),
    ("M", r"DIRECT MAIL|PRINTING-MAILING|POSTCARD|^POSTAGE|MAILER"),
    ("T", r"CABLE TV|\bRADIO\b|\bTV\b|TELEVISION|MEDIA- ?PRODUCTION"),
    ("D", r"MEDIA - INTERNET|WEBSITE|WEB |ONLINE|TEXT|ROBO|TELEMARKETING|E[- ]?MAIL|FACEBOOK|SOCIAL MEDIA|DIGITAL|DOMAIN|"
          r"SOFTWARE|VIDEO CONFERENCE|CONFERENCE CALL|GOOGLE|IT CONSULTING|X CORP"),
    ("P", r"PRINTING|HANDOUTS|FLYERS|PALM ?CARD|LAWN SIGN|BILLBOARD|MEDIA- ?MIXED|NEWSPAPER|LETTERS|BUSINESS CARDS|BANNER|"
          r"NAME TAGS|\bSIGNS?\b|PENS\b|MAGNETS|ADVERTIS|AD JOURNAL"),
    ("S", r"CONSULT|SALARY|PAYROLL|STIPEND|PROFESSIONAL SERVICES|COMPLIANCE|LEGAL|ACCOUNTING|RESEARCH|POLLING|FIELD|GOTV|"
          r"WAGES|COMMITTEE SERVICES|^SERVICES$|MEDIA SERVICES|CAMPAIGN SERVICES|DESIGN SERVICES"),
    ("O", r"OFFICE|RENT|UTILIT|FOOD|BEVERAGE|EVENT|FUNDRAIS|HALL|BANK|CHARGE|FEE|INSURANCE|TAX|TRAVEL|PHONE|SUPPLIES|"
          r"CREDIT CARD|CLEAN|ALARM|WATER|PARKING|PETTY CASH|MEETING|SUMMIT|RE-?ORG|PARADE|CANDY|ENTERTAINMENT|TICKET|DUES|"
          r"SUBSCRIPTION|PO BOX|MEMBERSHIP|REIMBURSEMENT|CONVENTION|PHOTO|GOVERN|WINRED|ANEDOT|NOTARY|SNOW|STAMPS|CHECK|"
          r"DEPOSIT|PRETZEL|TENT|BUSSES|SUNSHINE|FLOWERS|REGISTRATION|BARTENDER|GLOVES|PLAQUE|ROOM|CHANGE FOR|ELECTION NIGHT|GALA"),
]

# ELEC contributor types -> the groups the site shows. Types not listed fall back to inference.
ELEC_TYPES = {
    "INDIVIDUAL": "Individual",
    "BUSINESS/CORP": "Business",
    "UNION": "Union/PAC", "UNION PAC": "Union/PAC", "BUSINESS/ CORP ASSOC/ PAC": "Union/PAC",
    "IDEOLOGICAL ASSOC/ PAC": "Union/PAC", "PROFESSIONAL PAC": "Union/PAC", "TRADE ASSOCIATION PAC": "Union/PAC",
    "CANDIDATE COMMITTEE": "Political committee", "POLITICAL PARTY CMTE": "Political committee",
    "POLITICAL CLUB": "Political committee", "POLITICAL CMTE": "Political committee",
    "LEGISLATIVE LEADERSHIP CMTE": "Political committee",
}
QEND = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
# A candidate closing out the primary moves the balance to the general-election account, where it
# becomes the opening balance. ELEC's standard purpose text for that entry:
ROLLOVER = re.compile(r"^FUNDS (TRANSFERRED|DISBURSED) TO NEXT ELECTION")
SUFFIXES = {"JR", "SR", "II", "III", "IV"}
# site scope and entity type for each fetch scope
CAMPAIGN_SCOPES = {"legislative": "legislative", "countywide": "countywide", "middlesex_muni": "municipal",
                   "middlesex_party": "municipal_party"}


def name_key(name):
    toks = re.findall(r"[A-Z0-9]+", (name or "").upper())
    return toks[0] if toks else ""


def elec_type_rows(entity):
    """{(date, cents): [(first word of name, site group), ...]} from one committee's database rows"""
    rows = {}
    for r in entity["contributions"]:
        group = ELEC_TYPES.get((r["ContributorType"] or "").strip().upper())
        if group:
            rows.setdefault((r["CONT_DATE"][:10], round(r["CONT_AMT"] * 100)), []).append((name_key(r["CONTRIBUTOR"]), group))
    return rows


def elec_type(rows, c):
    """ELEC's type for one parsed contribution, or None when there is no confident match."""
    cands = rows.get((c["date"], round(c["amount"] * 100)), [])
    groups = {g for _, g in cands}
    if len(groups) == 1:
        return groups.pop()
    named = {g for k, g in cands if k and k == name_key(c["name"])}
    return named.pop() if len(named) == 1 else None


def bucket(purpose, schedule):
    if schedule == 10:
        return "X"
    p = re.sub(r"\s+", " ", purpose.upper()).strip()
    for text in (p.split(" - ")[0], p):
        for code, rx in BUCKET_RULES:
            if re.search(rx, text):
                return code
    return "U"


def title(s):
    small = {"OF", "AND", "THE", "FOR"}
    out = " ".join(w.capitalize() if w not in small else w.lower() for w in s.split())
    out = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), out)
    out = re.sub(r"([-'])([a-z])", lambda m: m.group(1) + m.group(2).upper(), out)
    return re.sub(r"\b(Ii|Iii|Iv)\b", lambda m: m.group(1).upper(), out)


def person(name):
    """ELEC lists candidates as 'LAST, FIRST M SUFFIX'."""
    if "," not in name:
        return title(name)
    last, rest = [x.strip() for x in name.split(",", 1)]
    toks = rest.split()
    suffix = toks.pop() if toks and toks[-1].upper().strip(".") in SUFFIXES else ""
    return title(" ".join(toks + [last] + ([suffix] if suffix else [])))


def load(scope):
    raw = json.load(open(f"data/raw/{scope}.json", encoding="utf-8"))
    parsed = json.load(open(f"data/parsed/{scope}.json", encoding="utf-8"))
    reps = collections.defaultdict(list)
    for r in parsed["reports"]:
        reps[r["entity"]].append(r)
    return raw, reps


class Rows:
    """Collects contribution and expenditure rows for the site."""

    def __init__(self):
        self.contributions, self.expenditures, self.matched = [], [], 0

    def add(self, entity_id, report, types, account_entity=None):
        """Add one report's rows. Returns the amount the committee moved to its own next-election
        account, which is left out of the expenditures because it is not spending."""
        # candidate rows are far more numerous, so they drop empty fields and the columns only the workbook uses
        slim = (lambda row: {k: v for k, v in row.items() if (k == "purpose" or (v != "" and v is not False)) and k not in ("schedule", "q")}) \
            if account_entity is None else (lambda row: row)
        carried = 0.0
        for c in report["contributions"]:
            filed_type = None if c["type"] == "Small-dollar group" else elec_type(types, c)
            kind = filed_type or c["type"]
            self.matched += bool(filed_type)
            self.contributions.append(slim({
                "entityId": account_entity(c["account"]) if account_entity else entity_id, "name": c["name"],
                "type": "In-kind" if c["inKind"] and kind == "Business" else kind, "amount": c["amount"],
                "date": c["date"], "employer": c["employer"], "occupation": c["occupation"],
                "address": "" if kind == "Individual" else c["address"], "inKind": c["inKind"], "q": report["quarter"]}))
        for x in report["expenses"]:
            if ROLLOVER.search(x["purpose"].upper()):
                carried += x["amount"]
                continue
            self.expenditures.append(slim({
                "entityId": account_entity(x["account"]) if account_entity else entity_id, "vendor": x["vendor"],
                "address": "" if contributor_type(x["vendor"], "", "") == "Individual" else x["address"],
                "amount": x["amount"], "date": x["date"], "purpose": x["purpose"],
                "code": bucket(x["purpose"], x["schedule"]), "schedule": x["schedule"], "q": report["quarter"]}))
        return carried


def filing(r):
    return {"year": r["year"], "quarter": r["quarter"], "label": r["label"], "elecId": str(r["doc"]), "filed": r["filed"],
            "amendment": r["amendment"], "opening": r["opening"], "receipts": r["receipts"],
            "expenditures": r["expenditures"], "closing": r["closing"], "unitemized": r["unitemized"]}


def build_parties(rows):
    """County party committees: one entity per bank account, as the R-3 breaks rows out by account."""
    raw, reps = load("county_party")
    entities, committees = {}, {}
    for e in sorted(raw["entities"], key=lambda e: (e["location"], e["party"])):
        county = title(e["location"][:-len(" COUNTY")])
        types = elec_type_rows(e)
        for r in sorted(reps.get(e["entity"], []), key=lambda r: (r["year"], r["quarter"])):
            ck = f"{county}|{e['party']}"
            com = committees.setdefault(ck, {"county": county, "party": e["party"], "name": title(r["committee"]),
                                             "filings": [], "unitemized": 0.0})
            com["filings"].append(filing(r))
            com["unitemized"] += r["unitemized"]
            com["cashOnHand"], com["asOf"] = r["closing"], f"{r['year']}-{QEND[r['quarter']]}"
            bal = {a["number"]: a for a in r["accounts"]}

            def ent_for(account_str):
                m = re.search(r"\*{4}\d{4}", account_str or "")
                num = m.group(0) if m else (r["accounts"][0]["number"] if r["accounts"] else "main")
                eid = f"CO-{county}-{e['party']}-{num}"
                if eid not in entities:
                    label = bal[num]["name"] if num in bal else re.sub(r"\s*\*{4}\d{4}", "", account_str or "Main account")
                    entities[eid] = {"id": eid, "name": com["name"], "account": f"{title(label)} {num}".strip(),
                                     "type": "County Committee", "scope": "county_party", "party": e["party"], "ld": "",
                                     "county": county, "cashOnHand": 0, "asOf": ""}
                return eid

            for a in r["accounts"]:
                acct = entities[ent_for("x " + a["number"])]
                acct["cashOnHand"], acct["asOf"] = a["closing"], f"{r['year']}-{QEND[r['quarter']]}"
            rows.add(None, r, types, account_entity=ent_for)
    return committees, list(entities.values()), raw["fetched"]


def status_note(group):
    """Why a committee has no itemized report."""
    forms = {f["FormName"] for e in group for f in e["filings"]}
    sworn = sorted(f for f in forms if f in ("A-1", "A-2", "A-3"))
    if sworn:
        return (f"Filed Form {sworn[0]}, a sworn statement that it will stay under ELEC's reporting threshold, "
                f"so there is no itemized report.")
    if any(f == "R-1" or f == "R-3" or f.startswith("RQ-") for f in forms):
        return f"No itemized report on file for {SINCE} or later."
    return "Registered with ELEC; no reports filed yet."


def build_campaigns(scope, rows, counts):
    """Candidates, joint candidates committees and municipal party committees: one entity each.
    ELEC keeps a separate record for a candidate's primary and general election; those are merged."""
    raw, reps = load(scope)
    site_scope = CAMPAIGN_SCOPES[scope]
    groups = collections.OrderedDict()
    for e in sorted(raw["entities"], key=lambda e: (e["location"], e["name"], e["year"], e["entity"])):
        if e["party"] not in ("D", "R"):
            counts["other party (not shown)"] += 1
            continue
        groups.setdefault((e["name"], e["officeCode"], e["location"], e["party"], e["year"]), []).append(e)
    out, site_id = [], {}
    for (name, office_code, location, party, year), group in groups.items():
        sid = f"EL-{min(e['entity'] for e in group)}"
        for e in group:
            site_id[e["entity"]] = sid
        # a report listed under both the primary and the general record is the same filing: keep one
        seen, reports = set(), []
        for e in group:
            for r in reps.get(e["entity"], []):
                k = (r["year"], r["period"], r["electionDate"], r["receipts"], r["expenditures"], r["closing"])
                if k not in seen:
                    seen.add(k)
                    reports.append(r)
        reports.sort(key=lambda r: (r["order"], r["doc"]))
        joint = office_code == "E"
        is_party = SCOPES[scope]["pac"]
        m = re.match(r"\s*(\d+)", location)
        ent = {
            "id": sid, "scope": site_scope,
            "type": "Municipal Committee" if is_party else "Joint" if joint else "Candidate",
            "name": title(name) if (joint or is_party) else person(name),
            "office": "Joint candidates committee" if joint else "Municipal party committee" if is_party else title(group[0]["office"]),
            "party": party, "year": year, "elections": sorted({title(e["electionType"]) for e in group}, reverse=True),
            "ld": int(m.group(1)) if scope == "legislative" and m else "",
            "county": title(location[:-len(" COUNTY")]) if scope == "countywide" else "Middlesex" if "middlesex" in scope else "",
            "muni": title(location) if "middlesex" in scope else "",
            # ELEC returns committee ids as text in one endpoint and as numbers in another
            "elecEntities": sorted(str(e["entity"]) for e in group),
            "jointElec": sorted({str(e["joint"]) for e in group if e["joint"]}),
            "filings": [filing(r) for r in reports], "unitemized": round(sum(r["unitemized"] for r in reports), 2),
            "cashOnHand": 0, "asOf": "",
        }
        if reports:
            last = reports[-1]
            ent["cashOnHand"] = last["closing"]
            ent["asOf"] = last["order"]       # for ordering; shown only when the report is a quarterly
            if not last["quarter"]:
                ent["asOfLabel"] = last["label"]
        else:
            ent["note"] = status_note(group)
        types = {}
        for e in group:
            for k, v in elec_type_rows(e).items():
                types.setdefault(k, []).extend(v)
        carried = sum(rows.add(sid, r, types) for r in reports)
        if carried:
            ent["carried"] = round(carried, 2)
            counts["candidates who carried a primary balance into the general (not counted as spending)"] += 1
        counts[f"{site_scope}: {ent['type'].lower()}s"] += 1
        counts[f"{site_scope}: with itemized reports"] += bool(reports)
        out.append(ent)
    # link each joint committee to the candidates who file through it
    for ent in out:
        if ent["type"] == "Joint":
            ent["members"] = sorted({c["id"] for c in out if c["type"] == "Candidate" and
                                     set(c["jointElec"]) & set(ent["elecEntities"])})
    for ent in out:
        ent.pop("jointElec")
    return out


def main():
    rows, counts = Rows(), collections.Counter()
    committees, entities, fetched = build_parties(rows)
    for scope in CAMPAIGN_SCOPES:
        if os.path.exists(f"data/parsed/{scope}.json"):
            entities += build_campaigns(scope, rows, counts)
    quarters = sorted({(f["year"], f["quarter"]) for com in committees.values() for f in com["filings"]})
    (y0, q0), (y1, q1) = quarters[0], quarters[-1]
    period = f"{y0} Q{q0}" + ("" if (y0, q0) == (y1, q1) else f"–Q{q1}" if y0 == y1 else f"–{y1} Q{q1}")
    out = {"source": f"ELEC quarterly reports (Forms R-1 and R-3), {period}", "period": period, "since": SINCE,
           "fetched": fetched[:10],
           "key": KEY, "committees": committees, "entities": entities,
           "contributions": rows.contributions, "expenditures": rows.expenditures}
    json.dump(out, open("data/site_data.json", "w"), separators=(",", ":"))

    # mapping review file
    seen = {}
    for x in rows.expenditures:
        p = re.sub(r"\s+", " ", x["purpose"].upper()).strip() or "(blank)"
        s = seen.setdefault(p, [x["code"], 0.0, 0])
        s[1] += x["amount"]; s[2] += 1
    with open("data/bucket_mapping.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["purpose_as_filed", "bucket", "total", "count"])
        for p, (code, tot, n) in sorted(seen.items(), key=lambda kv: -kv[1][1]):
            w.writerow([p, KEY[code], f"{tot:.2f}", n])

    print(f"{period} · {len(committees)} county party committees, {sum(e['type'] == 'County Committee' for e in entities)} accounts")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print(f"{len(rows.contributions)} contributions, {len(rows.expenditures)} expenditures")
    print(f"contributor type from ELEC's database for {rows.matched} of {len(rows.contributions)} contributions; the rest are inferred")
    by = {}
    for x in rows.expenditures:
        by[x["code"]] = by.get(x["code"], 0) + x["amount"]
    for k, v in sorted(by.items(), key=lambda kv: -kv[1]):
        print(f"  {KEY[k]:<28}${v:>14,.2f}")
    print(f"data/site_data.json {os.path.getsize('data/site_data.json'):,} bytes")


if __name__ == "__main__":
    main()
