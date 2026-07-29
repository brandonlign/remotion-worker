#!/usr/bin/env python3
from __future__ import annotations
import json, urllib.error, urllib.parse, urllib.request
from pathlib import Path

OUT=Path('blindslope_download_probe'); OUT.mkdir(exist_ok=True)
AOI='88.55,27.25,88.72,27.40'
TEMP='2026-06-17T00:00:00Z,2026-07-30T00:00:00Z'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None
OPENER=urllib.request.build_opener(NoRedirect)

def probe(url, timeout=10):
    req=urllib.request.Request(url,headers={'User-Agent':'BlindSlope-Pilot/1.5','Accept':'*/*','Range':'bytes=0-1023'})
    try:
        with OPENER.open(req,timeout=timeout) as r:
            body=r.read(1024); return {'status':r.status,'final_url':r.geturl(),'location':r.headers.get('Location'),'content_type':r.headers.get('Content-Type'),'content_length':r.headers.get('Content-Length'),'bytes_read':len(body),'body_prefix':body[:200].decode('utf-8','replace'),'error':None}
    except urllib.error.HTTPError as e:
        body=e.read(1024); return {'status':e.code,'final_url':e.geturl(),'location':e.headers.get('Location'),'content_type':e.headers.get('Content-Type'),'content_length':e.headers.get('Content-Length'),'bytes_read':len(body),'body_prefix':body[:200].decode('utf-8','replace'),'error':None}
    except Exception as e:
        return {'status':None,'final_url':url,'location':None,'content_type':None,'content_length':None,'bytes_read':0,'body_prefix':'','error':f'{type(e).__name__}: {e}'}

def fetch_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'BlindSlope-Pilot/1.5','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)

s_ids=[
 'NISAR_S2_PR_GUNW_024_170_A_015_025_3700_SH_20260707T233026_20260707T233103_20260719T233025_20260719T233102_P00500_M_F_I_001',
 'NISAR_S2_PR_GUNW_024_069_A_015_025_3700_SH_20260630T232207_20260630T232244_20260712T232206_20260712T232243_P00500_M_F_I_001',
]
s_probes=[]
for sid in s_ids:
    base=f'https://bhoonidhi.nrsc.gov.in//bhoonidhi/data//NISAR/SSAR/2026/JUL/{sid}.zip'
    for label,url in [('no_token',base),('token_none',base+'?token=None&product_id='+urllib.parse.quote(sid))]:
        s_probes.append({'scene_id':sid,'variant':label,'url':url,'result':probe(url)})

short='NISAR_L2_GUNW_PROVISIONAL_V1'
collections=fetch_json('https://cmr.earthdata.nasa.gov/search/collections.umm_json?'+urllib.parse.urlencode({'short_name':short,'page_size':20}))
items=collections.get('items',[]); asf=[x for x in items if x.get('meta',{}).get('provider-id')=='ASF']
concept=(asf or items)[0]['meta']['concept-id']
params={'concept_id':concept,'bounding_box':AOI,'temporal':TEMP,'page_size':2000,'sort_key[]':'start_date'}
granules=fetch_json('https://cmr.earthdata.nasa.gov/search/granules.umm_json?'+urllib.parse.urlencode(params)).get('items',[])
want=[('_170_A_015_','20260707','20260719'),('_069_A_015_','20260630','20260712')]
l_entries=[]
for item in granules:
    meta=item.get('meta',{}); umm=item.get('umm',{}); name=str(umm.get('GranuleUR') or meta.get('native-id') or '')
    if not any(a in name and b in name and c in name for a,b,c in want): continue
    urls=[]
    for related in umm.get('RelatedUrls',[]) or []:
        url=related.get('URL'); kind=(str(related.get('Type',''))+' '+str(related.get('Subtype',''))).upper()
        if url and ('GET DATA' in kind or url.lower().endswith(('.h5','.zip'))):
            urls.append({'url':url,'type':related.get('Type'),'subtype':related.get('Subtype'),'result':probe(url)})
    l_entries.append({'granule_id':name,'concept_id':meta.get('concept-id'),'data_urls':urls})

report={'s_band':s_probes,'l_band':l_entries,'success_statuses':[200,206]}
(OUT/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True,default=str)+'\n')
print(json.dumps(report,indent=2,sort_keys=True,default=str))
