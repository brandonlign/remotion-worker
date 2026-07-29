#!/usr/bin/env python3
from __future__ import annotations
import json, urllib.error, urllib.parse, urllib.request
from pathlib import Path

OUT=Path('blindslope_download_probe'); OUT.mkdir(exist_ok=True)
AOI='88.55,27.25,88.72,27.40'
TEMP='2026-06-17T00:00:00Z,2026-07-30T00:00:00Z'
HEAD={'User-Agent':'BlindSlope-Pilot/1.4','Accept':'*/*','Range':'bytes=0-1023'}

def request(url, follow=True, timeout=45):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl): return None
    opener=urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    req=urllib.request.Request(url,headers=HEAD)
    try:
        with opener.open(req,timeout=timeout) as r:
            body=r.read(1024)
            return {'status':r.status,'final_url':r.geturl(),'headers':dict(r.headers),'bytes_read':len(body),'body_prefix':body[:300].decode('utf-8','replace'),'error':None}
    except urllib.error.HTTPError as e:
        body=e.read(1024)
        return {'status':e.code,'final_url':e.geturl(),'headers':dict(e.headers),'bytes_read':len(body),'body_prefix':body[:300].decode('utf-8','replace'),'error':None}
    except Exception as e:
        return {'status':None,'final_url':url,'headers':{},'bytes_read':0,'body_prefix':'','error':f'{type(e).__name__}: {e}'}

s_ids=[
 'NISAR_S2_PR_GUNW_024_170_A_015_025_3700_SH_20260707T233026_20260707T233103_20260719T233025_20260719T233102_P00500_M_F_I_001',
 'NISAR_S2_PR_GUNW_024_069_A_015_025_3700_SH_20260630T232207_20260630T232244_20260712T232206_20260712T232243_P00500_M_F_I_001',
]
s_month={'170':'JUL','069':'JUL'}
s_probes=[]
for sid in s_ids:
    track='170' if '_170_' in sid else '069'
    base=f'https://bhoonidhi.nrsc.gov.in//bhoonidhi/data//NISAR/SSAR/2026/{s_month[track]}/{sid}.zip'
    variants={
      'no_query':base,
      'token_none':base+'?token=None&product_id='+urllib.parse.quote(sid),
      'token_blank':base+'?token=&product_id='+urllib.parse.quote(sid),
    }
    for label,url in variants.items():
        s_probes.append({'scene_id':sid,'variant':label,'url':url,'no_redirect':request(url,False),'follow_redirects':request(url,True)})

# Query NASA CMR for L-band matched GUNW entries and probe each advertised data link.
short='NISAR_L2_GUNW_PROVISIONAL_V1'
q=urllib.parse.urlencode({'short_name':short,'page_size':20})
cr=request('https://cmr.earthdata.nasa.gov/search/collections.umm_json?'+q,True)
# request() only captures prefix; fetch full JSON here.
def fetch_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'BlindSlope-Pilot/1.4','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=60) as r:return json.load(r)
collections=fetch_json('https://cmr.earthdata.nasa.gov/search/collections.umm_json?'+q)
items=collections.get('items',[])
asf=[x for x in items if x.get('meta',{}).get('provider-id')=='ASF']
concept=(asf or items)[0]['meta']['concept-id']
params={'concept_id':concept,'bounding_box':AOI,'temporal':TEMP,'page_size':2000,'sort_key[]':'start_date'}
granules=fetch_json('https://cmr.earthdata.nasa.gov/search/granules.umm_json?'+urllib.parse.urlencode(params)).get('items',[])
want=[('_170_A_015_','20260707','20260719'),('_069_A_015_','20260630','20260712')]
l_entries=[]
for item in granules:
    meta=item.get('meta',{}); umm=item.get('umm',{})
    name=str(umm.get('GranuleUR') or meta.get('native-id') or '')
    if not any(a in name and b in name and c in name for a,b,c in want): continue
    urls=[]
    for related in umm.get('RelatedUrls',[]) or []:
        url=related.get('URL')
        kind=(str(related.get('Type',''))+' '+str(related.get('Subtype',''))).upper()
        if url and ('GET DATA' in kind or url.lower().endswith(('.h5','.zip'))):
            urls.append({'url':url,'type':related.get('Type'),'subtype':related.get('Subtype'),'no_redirect':request(url,False),'follow_redirects':request(url,True)})
    l_entries.append({'granule_id':name,'concept_id':meta.get('concept-id'),'data_urls':urls})

report={'s_band':s_probes,'l_band':l_entries,'interpretation':{'success_statuses':[200,206],'auth_or_redirect_statuses':[301,302,303,307,308,401,403]}}
(OUT/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True,default=str)+'\n')
print(json.dumps(report,indent=2,sort_keys=True,default=str))
