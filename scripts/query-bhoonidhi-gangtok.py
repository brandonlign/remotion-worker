#!/usr/bin/env python3
from __future__ import annotations
import json, sys, urllib.error, urllib.request
from pathlib import Path

BASE='https://bhoonidhi.nrsc.gov.in'
OUT=Path('bhoonidhi_gangtok_query'); OUT.mkdir(exist_ok=True)
base={
  'userId':'T','prod':'Standard','selSats':'NISAR_SSAR_GUNW','offset':'0',
  'sdate':'JUL%2F08%2F2026','edate':'JUL%2F29%2F2026','query':'area',
  'queryType':'polygon','isMX':'No','tllat':27.40,'tllon':88.55,
  'brlat':27.25,'brlon':88.72,'filters':'%7B%7D'
}
variants=[
 ('guest_standard',base,None),
 ('blank_token',base,''),
 ('null_user',{**base,'userId':None},None),
 ('explicit_product',{**base,'prod':'Level-2_GUNW'},None),
]
results=[]
for name,payload,token in variants:
  headers={'User-Agent':'BlindSlope-Pilot/0.9','Accept':'application/json','Content-Type':'application/json','Origin':BASE,'Referer':BASE+'/bhoonidhi/index.html'}
  if token is not None: headers['token']=token
  req=urllib.request.Request(BASE+'/bhoonidhi/ProductSearch',data=json.dumps(payload,separators=(',',':')).encode(),headers=headers,method='POST')
  try:
    with urllib.request.urlopen(req,timeout=30) as r:
      body=r.read(); status=r.status; error=None
  except urllib.error.HTTPError as e:
    body=e.read(); status=e.code; error=None
  except Exception as e:
    body=b''; status=None; error=f'{type(e).__name__}: {e}'
  try: parsed=json.loads(body)
  except Exception: parsed=None
  count=len(parsed.get('Results',[])) if isinstance(parsed,dict) and isinstance(parsed.get('Results'),list) else None
  record={'name':name,'status':status,'error':error,'result_count':count,'payload':payload,'body_prefix':body[:4000].decode('utf-8','replace')}
  results.append(record)
  (OUT/f'{name}_response.txt').write_bytes(body)
  print(json.dumps(record,indent=2,sort_keys=True))
  if status==200 and count is not None:
    (OUT/'successful_response.json').write_text(json.dumps(parsed,indent=2,sort_keys=True)+'\n')
    break
(OUT/'summary.json').write_text(json.dumps(results,indent=2,sort_keys=True)+'\n')
if not any(r['status']==200 and r['result_count'] is not None for r in results): sys.exit(3)
