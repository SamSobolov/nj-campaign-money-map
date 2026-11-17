"""Assemble the site from src.html + data.

  docs/index.html  public site (GitHub Pages serves /docs)
  index.html       Claude Artifact build (the artifact host adds its own <head>)
  preview.html     local check
"""
import os, re


def read(path):
    return open(path, encoding="utf-8").read()


def write(path, text):
    # same bytes on every OS: UTF-8 with Unix line endings
    open(path, "w", encoding="utf-8", newline="\n").write(text)


s = read("src.html")
# Google Sheet export link (data/sheet_url.txt); the button is removed until the sheet exists
sheet_url = read("data/sheet_url.txt").strip() if os.path.exists("data/sheet_url.txt") else ""
if not sheet_url:
    s = re.sub(r'\s*<a class="sheet-btn".*?</a>', "", s, flags=re.S)
page = (s.replace("__GEO__", read("geo.json")).replace("__DATA__", read("data/site_data.json"))
         .replace("__SHEET_URL__", sheet_url))

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="description" content="Interactive map of New Jersey county party committee fundraising and spending, built from ELEC Form R-3 filings.">
<meta property="og:title" content="NJ Campaign Money Map">
<meta property="og:description" content="Where New Jersey's county party committees raise and spend their money, from ELEC filings.">
<meta property="og:type" content="website">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%231d4fb8'/%3E%3Cpath d='M9 23V9h4l6 9V9h4v14h-4l-6-9v9z' fill='white'/%3E%3C/svg%3E">
<style>body{margin:0}</style>
</head>
<body>
"""

os.makedirs("docs", exist_ok=True)
write("docs/index.html", HEAD + page + "\n</body>\n</html>\n")
write("index.html", page)
write("preview.html", HEAD + page + "\n</body>\n</html>\n")
print(f"docs/index.html {os.path.getsize('docs/index.html'):,} bytes")
