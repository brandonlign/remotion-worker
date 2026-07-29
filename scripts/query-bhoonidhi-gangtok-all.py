#!/usr/bin/env python3
from __future__ import annotations
import json, urllib.error, urllib.request
from pathlib import Path

BASE='https://bhoonidhi.nrsc.gov.in'
OUT=Path('bhoonidhi_gangtok_all'); OUT.mkdir(exist_ok=True)
products=[
 ('RIFG','NISAR_SSAR_RIFG','Level-1_RIFG'),
 ('ROFF','NISAR_SSAR_ROFF','Level-1_ROFF'),
 ('RSLC','NISAR_SSAR_RSLC','Level-1_RSLC'),
 ('RUNW','NISAR_SSAR_RUNW','Level-1_RUNW'),
 ('GCOV','NISAR_SSAR_GCOV','Level-2_GCOV'),
 ('GOFF','NISAR_SSAR_GOFF','Level-2_GOFF'),
 ('GSLC','NISAR_SSAR_GSLC','Level-2_GSLC'),
 ('GUNW','NISAR_SSAR_GUNW','Level-2_GUNW'),
]
summary=[]
for short,selector,level in products:
  payload={
    'userId':'T','prod':'Standard','selSats':selector,'offset':'0',
    'sdate':'JUL%2F08%2F2026','edate':'JUL%2F29%2F2026','query':'area',
    'queryType':'polygon','isMX':'No','tllat':27.40,'tllon':88.55,
    'brlat':27.25,'brlon':88.72,'filters':'%7B%7D'
  }
  headers={'User-Agent':'BlindSlope-Pilot/1.0','Accept':'application/json','Content-Type':'application/json','Origin':BASE,'Referer':BASE+'/bhoonidhi/index.html'}
  req=urllib.request.Request(BASE+'/bhoonidhi/ProductSearch',data=json.dumps(payload,separators=(',',':')).encode(),headers=headers,method='POST')
  try:
    with urllib.request.urlopen(req,timeout=40) as r:
      body=r.read(); status=r.status; error=None
  except urllib.error.HTTPError as e:
    body=e.read(); status=e.code; error=None
  except Exception as e:
    body=b''; status=None; error=f'{type(e).__name__}: {e}'
  try: parsed=json.loads(body)
  except Exception: parsed=None
  rows=parsed.get('Results',[]) if isinstance(parsed,dict) and isinstance(parsed.get('Results'),list) else None
  rec={'product':short,'selector':selector,'archive_level':level,'status':status,'error':error,'result_count':len(rows) if rows is not None else None,'results':rows,'body_prefix':body[:1000].decode('utf-8','replace')}
  summary.append(rec)
  (OUT/f'{short}_response.txt').write_bytes(body)
  print(json.dumps({k:v for k,v in rec.items() if k!='results'},indent=2,sort_keys=True))
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
print('--- S-BAND INVENTORY SUMMARY ---')
print(json.dumps([{k:r[k] for k in ['product','selector','status','error','result_count']} for r in summary],indent=2,sort_keys=True))
