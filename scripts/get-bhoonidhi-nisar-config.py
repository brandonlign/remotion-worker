#!/usr/bin/env python3
import json, urllib.request, urllib.error
BASE='https://bhoonidhi.nrsc.gov.in'
payload={"userId":"T","action":"GETAVCONFIG","userEmail":"abc@xyz.com"}
req=urllib.request.Request(BASE+'/bhoonidhi/SatSenServlet',data=json.dumps(payload).encode(),headers={"User-Agent":"BlindSlope-Pilot/0.8","Accept":"application/json","Content-Type":"application/json","Origin":BASE,"Referer":BASE+'/bhoonidhi/index.html'},method='POST')
try:
    with urllib.request.urlopen(req,timeout=30) as r:
        body=r.read(); status=r.status
except urllib.error.HTTPError as e:
    body=e.read(); status=e.code
print('HTTP_STATUS',status)
print(body.decode('utf-8','replace'))
try:
    obj=json.loads(body)
    rows=obj.get('Results',[]) if isinstance(obj,dict) else []
    print('--- NISAR RECORDS ---')
    print(json.dumps([x for x in rows if any(k in json.dumps(x).lower() for k in ['nisar','s-sar','ssar'])],indent=2,sort_keys=True))
except Exception as e:
    print('PARSE_ERROR',type(e).__name__,str(e))
