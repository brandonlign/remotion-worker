#!/usr/bin/env python3
import io, json, urllib.request, zipfile

def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'BlindSlope-Pilot/1.3'})
    with urllib.request.urlopen(req,timeout=60) as r: return r.read()
meta=json.loads(get('https://pypi.org/pypi/bhoonidhi-downloader/json'))
wheel=next(x for x in meta['urls'] if x['filename'].endswith('.whl'))
z=zipfile.ZipFile(io.BytesIO(get(wheel['url'])))
for fname,ranges in {
    'bhoonidhi_downloader/utils.py':[(85,150)],
    'bhoonidhi_downloader/authenticate.py':[(1,180)],
    'bhoonidhi_downloader/constants.py':[(1,120)],
}.items():
    text=z.read(fname).decode('utf-8','replace').splitlines()
    print(f'--- {fname} BEGIN ---')
    for a,b in ranges:
        for i in range(a-1,min(b,len(text))): print(f'{i+1}: {text[i]}')
    print(f'--- {fname} END ---')
