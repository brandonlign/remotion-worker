#!/usr/bin/env python3
from __future__ import annotations
import io, json, re, urllib.request, zipfile
from pathlib import Path

HEAD={'User-Agent':'BlindSlope-Pilot/1.2','Accept':'application/json'}
def get(url,timeout=60):
    req=urllib.request.Request(url,headers=HEAD)
    with urllib.request.urlopen(req,timeout=timeout) as r: return r.read()
meta=json.loads(get('https://pypi.org/pypi/bhoonidhi-downloader/json'))
wheel=next(x for x in meta['urls'] if x['filename'].endswith('.whl'))
z=zipfile.ZipFile(io.BytesIO(get(wheel['url'])))
print('FILES',json.dumps(z.namelist(),indent=2))
needles=['download','qazip','qzip','getproductmeta','dirpath','order','zip','scene_id','filename','token']
out=[]
for name in z.namelist():
    if not name.endswith('.py'): continue
    text=z.read(name).decode('utf-8','replace')
    lines=text.splitlines()
    matches=[i for i,line in enumerate(lines) if any(n in line.lower() for n in needles)]
    if not matches: continue
    merged=[]
    for i in matches:
        start=max(0,i-15); end=min(len(lines),i+30)
        merged.append({'start_line':start+1,'end_line':end,'text':'\n'.join(f'{j+1}: {lines[j]}' for j in range(start,end))})
    out.append({'file':name,'contexts':merged})
print('--- DOWNLOAD CONTEXTS BEGIN ---')
print(json.dumps(out,indent=2))
print('--- DOWNLOAD CONTEXTS END ---')
Path('bhoonidhi_download_contexts.json').write_text(json.dumps({'version':meta['info']['version'],'wheel':wheel['url'],'contexts':out},indent=2)+'\n')
