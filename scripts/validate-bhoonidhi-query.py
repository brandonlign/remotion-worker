#!/usr/bin/env python3
from __future__ import annotations
import json, urllib.error, urllib.request
from pathlib import Path

BASE='https://bhoonidhi.nrsc.gov.in'
OUT=Path('bhoonidhi_validation'); OUT.mkdir(exist_ok=True)
# (name, bbox minlon,minlat,maxlon,maxlat)
aois=[
 ('gangtok',[88.55,27.25,88.72,27.40]),
 ('hyderabad',[78.30,17.20,78.70,17.60]),
 ('delhi',[76.90,28.40,77.40,28.90]),
 ('india',[68.0,6.0,98.0,38.0]),
]
tests=[]
for aoi_name,b in aois:
  for short,selector,level in [
    ('RSLC','NISAR_SSAR_RSLC','Level-1_RSLC'),
    ('GUNW','NISAR_SSAR_GUNW','Level-2_GUNW'),
  ]:
    for prod in ['Standard',level]:
      # Avoid potentially expensive full-India duplication.
      if aoi_name=='india' and (short!='RSLC' or prod!='Standard'): continue
      tests.append((aoi_name,b,short,selector,prod))

summary=[]
for aoi_name,b,short,selector,prod in tests:
  minlon,minlat,maxlon,maxlat=b
  payload={'userId':'T','prod':prod,'selSats':selector,'offset':'0','sdate':'JUL%2F08%2F2026','edate':'JUL%2F29%2F2026','query':'area','queryType':'polygon','isMX':'No','tllat':maxlat,'tllon':minlon,'brlat':minlat,'brlon':maxlon,'filters':'%7B%7D'}
  headers={'User-Agent':'BlindSlope-Pilot/1.1','Accept':'application/json','Content-Type':'application/json','Origin':BASE,'Referer':BASE+'/bhoonidhi/index.html'}
  req=urllib.request.Request(BASE+'/bhoonidhi/ProductSearch',data=json.dumps(payload,separators=(',',':')).encode(),headers=headers,method='POST')
  try:
    with urllib.request.urlopen(req,timeout=60) as r: body=r.read(); status=r.status; error=None
  except urllib.error.HTTPError as e: body=e.read(); status=e.code; error=None
  except Exception as e: body=b''; status=None; error=f'{type(e).__name__}: {e}'
  try: parsed=json.loads(body)
  except Exception: parsed=None
  rows=parsed.get('Results',[]) if isinstance(parsed,dict) and isinstance(parsed.get('Results'),list) else None
  rec={'aoi':aoi_name,'bbox':b,'product':short,'selector':selector,'prod_field':prod,'status':status,'error':error,'result_count':len(rows) if rows is not None else None,'first_results':rows[:3] if rows else [],'body_prefix':body[:1200].decode('utf-8','replace')}
  summary.append(rec)
  print(json.dumps({k:v for k,v in rec.items() if k!='first_results'},indent=2,sort_keys=True))
  if rows:
    print('FIRST_RESULTS',json.dumps(rows[:3],separators=(',',':')))
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
print('--- VALIDATION MATRIX ---')
print(json.dumps([{k:r[k] for k in ['aoi','product','prod_field','status','error','result_count']} for r in summary],indent=2,sort_keys=True))
