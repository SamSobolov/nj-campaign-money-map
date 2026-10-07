import json,re,collections,pdfplumber
d=json.load(open('data/county.json'))
ok=0
for r in d['reports']:
    t="\n".join((p.extract_text() or '') for p in pdfplumber.open('reports/county/'+r['file']).pages[:3])
    def line(lbl):
        m=re.search(lbl+r'.*?(\$[\d,]+\.\d{2})\s*(\$[\d,]+\.\d{2})',t,re.S)
        return float(m.group(1)[1:].replace(',','')) if m else 0
    s=collections.Counter()
    for e in r['expenses']: s[e['schedule']]+=e['amount']
    filed={8:line(r'1\. Operating Disbursement'),10:line(r'2a\. NJ Gub')+line(r'2b\. NJ Leg')+line(r'2c\. All other'),
           11:line(r'3a\. NJ Gub')+line(r'3b\. NJ Leg')+line(r'3c\. All other')+line(r'3d\. Indep')}
    c1=sum(c['amount'] for c in r['contributions'] if not c['inKind']); f1=line(r'2\. Monetary Contributions \(In Excess')
    c2=sum(c['amount'] for c in r['contributions'] if c['inKind']); f2=line(r'4\. In-kind contributions, more than')
    bad=[f"S{k} parsed {s[k]:,.2f} filed {filed[k]:,.2f}" for k in (8,10,11) if abs(s[k]-filed[k])>0.5]
    if abs(c1-f1)>0.5: bad.append(f"S1 parsed {c1:,.2f} filed {f1:,.2f}")
    if abs(c2-f2)>0.5: bad.append(f"S2 parsed {c2:,.2f} filed {f2:,.2f}")
    if bad: print(r['county'],r['party'],'Q%d'%r['quarter'],r['file'],'; '.join(bad))
    else: ok+=1
print('reconciled exactly:',ok,'of',len(d['reports']))
