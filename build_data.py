"""Turn parsed R-3 reports (data/county.json) into the site's data model (data/site_data.json).

Spending buckets are assigned from ELEC's purpose text until the team's own key codes arrive;
BUCKET_RULES below is the mapping to review.
"""
import csv, json, re

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
          r"NAME TAGS|\bSIGNS?\b|PENS\b|MAGNETS"),
    ("S", r"CONSULT|SALARY|PAYROLL|STIPEND|PROFESSIONAL SERVICES|COMPLIANCE|LEGAL|ACCOUNTING|RESEARCH|POLLING|FIELD|GOTV|"
          r"WAGES|COMMITTEE SERVICES|^SERVICES$|MEDIA SERVICES"),
    ("O", r"OFFICE|RENT|UTILIT|FOOD|BEVERAGE|EVENT|FUNDRAIS|HALL|BANK|CHARGE|FEE|INSURANCE|TAX|TRAVEL|PHONE|SUPPLIES|"
          r"CREDIT CARD|CLEAN|ALARM|WATER|PARKING|PETTY CASH|MEETING|SUMMIT|RE-?ORG|PARADE|CANDY|ENTERTAINMENT|TICKET|DUES|"
          r"SUBSCRIPTION|PO BOX|MEMBERSHIP|REIMBURSEMENT|CONVENTION|PHOTO|GOVERN|WINRED|ANEDOT|NOTARY|SNOW|STAMPS|CHECK|"
          r"DEPOSIT|PRETZEL|TENT|BUSSES|SUNSHINE|FLOWERS|REGISTRATION|BARTENDER|GLOVES|PLAQUE|ROOM|CHANGE FOR|ELECTION NIGHT|GALA"),
]


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
    return " ".join(w.capitalize() if w not in small else w.lower() for w in s.split())


QEND = {1: "2026-03-31", 2: "2026-06-30", 3: "2026-09-30", 4: "2026-12-31"}


def main():
    reports = json.load(open("data/county.json"))["reports"]
    entities, committees, contributions, expenditures = {}, {}, [], []
    for r in reports:
        ck = f'{r["county"]}|{r["party"]}'
        com = committees.setdefault(ck, {"county": r["county"], "party": r["party"], "name": title(r["committee"]),
                                         "filings": [], "unitemized": 0.0})
        com["filings"].append({"quarter": r["quarter"], "elecId": r["file"].replace(".pdf", ""), "filed": r["filed"],
                               "amendment": r["amendment"], "opening": r["opening"], "receipts": r["receipts"],
                               "expenditures": r["expenditures"], "closing": r["closing"],
                               "unitemized": r["unitemized"]})
        com["unitemized"] += r["unitemized"]
        if r["quarter"] >= max(f["quarter"] for f in com["filings"]):
            com["cashOnHand"], com["asOf"] = r["closing"], QEND[r["quarter"]]
        bal = {a["number"]: a for a in r["accounts"]}

        def ent_for(account_str):
            m = re.search(r"\*{4}\d{4}", account_str or "")
            num = m.group(0) if m else (r["accounts"][0]["number"] if r["accounts"] else "main")
            eid = f'CO-{r["county"]}-{r["party"]}-{num}'
            e = entities.get(eid)
            if not e:
                label = bal[num]["name"] if num in bal else re.sub(r"\s*\*{4}\d{4}", "", account_str or "Main account")
                e = entities[eid] = {"id": eid, "name": com["name"], "account": f"{title(label)} {num}".strip(),
                                     "type": "County Committee", "party": r["party"], "ld": "", "county": r["county"],
                                     "cashOnHand": 0, "asOf": "", "_q": 0}
            return e

        for a in r["accounts"]:
            e = ent_for("x " + a["number"])
            if r["quarter"] >= e["_q"]:
                e["cashOnHand"], e["asOf"], e["_q"] = a["closing"], QEND[r["quarter"]], r["quarter"]
        for c in r["contributions"]:
            e = ent_for(c["account"])
            contributions.append({"entityId": e["id"], "name": c["name"], "type": "In-kind" if c["inKind"] and c["type"] == "Business" else c["type"],
                                  "amount": c["amount"], "date": c["date"], "employer": c["employer"],
                                  "occupation": c["occupation"], "address": "" if c["type"] == "Individual" else c["address"], "inKind": c["inKind"],
                                  "q": r["quarter"]})
        for x in r["expenses"]:
            e = ent_for(x["account"])
            expenditures.append({"entityId": e["id"], "vendor": x["vendor"],
                                 "address": "" if contributor_type(x["vendor"], "", "") == "Individual" else x["address"],
                                 "amount": x["amount"], "date": x["date"], "purpose": x["purpose"],
                                 "code": bucket(x["purpose"], x["schedule"]), "schedule": x["schedule"],
                                 "q": r["quarter"]})
    for e in entities.values():
        e.pop("_q")
    out = {"source": "ELEC Form R-3 quarterly reports, 2026 Q1–Q2", "key": KEY,
           "committees": committees, "entities": list(entities.values()),
           "contributions": contributions, "expenditures": expenditures}
    json.dump(out, open("data/site_data.json", "w"), separators=(",", ":"))
    # mapping review file
    seen = {}
    for x in expenditures:
        p = re.sub(r"\s+", " ", x["purpose"].upper()).strip() or "(blank)"
        s = seen.setdefault(p, [x["code"], 0.0, 0])
        s[1] += x["amount"]; s[2] += 1
    with open("data/bucket_mapping.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["purpose_as_filed", "bucket", "total", "count"])
        for p, (code, tot, n) in sorted(seen.items(), key=lambda kv: -kv[1][1]):
            w.writerow([p, KEY[code], f"{tot:.2f}", n])
    by = {}
    for x in expenditures:
        by[x["code"]] = by.get(x["code"], 0) + x["amount"]
    print(len(entities), "accounts,", len(contributions), "contributions,", len(expenditures), "expenditures")
    for k, v in sorted(by.items(), key=lambda kv: -kv[1]):
        print(f"  {KEY[k]:<28}${v:>14,.2f}")


if __name__ == "__main__":
    main()
