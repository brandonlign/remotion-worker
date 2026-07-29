#!/usr/bin/env python3
from __future__ import annotations
import ast, io, json, re, urllib.request, zipfile
from pathlib import Path

HEAD={"User-Agent":"BlindSlope-Pilot/0.6","Accept":"*/*"}
def get(url, timeout=60):
    req=urllib.request.Request(url,headers=HEAD)
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return r.status,r.geturl(),dict(r.headers),r.read()

out={"scene_search":{},"utils":{},"odap_contexts":[]}
status,url,headers,body=get("https://pypi.org/pypi/bhoonidhi-downloader/json")
meta=json.loads(body)
wheel=next(x for x in meta["urls"] if x["filename"].endswith(".whl"))
_,_,_,wb=get(wheel["url"])
z=zipfile.ZipFile(io.BytesIO(wb))
for fname,key in [("bhoonidhi_downloader/scene_search.py","scene_search"),("bhoonidhi_downloader/utils.py","utils")]:
    text=z.read(fname).decode("utf-8","replace")
    lines=text.splitlines()
    tree=ast.parse(text)
    funcs=[]; dicts=[]
    for node in ast.walk(tree):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            funcs.append({"name":node.name,"signature":ast.unparse(node.args),"line":node.lineno})
        if isinstance(node,(ast.Assign,ast.AnnAssign)):
            target=node.targets[0] if isinstance(node,ast.Assign) else node.target
            value=node.value
            if isinstance(target,ast.Name) and isinstance(value,ast.Dict):
                try: dicts.append({"name":target.id,"line":node.lineno,"expression":ast.unparse(value)})
                except Exception: pass
    out[key]={"functions":funcs,"dict_assignments":dicts,"source":text}

_,_,_,jsb=get("https://bhoonidhi.nrsc.gov.in/bhoonidhi/js/odap.js")
js=jsb.decode("utf-8","replace")
for needle in ["ProductSearch","searchObject","TextSearchServlet","SatSenServlet","NISAR"]:
    starts=[m.start() for m in re.finditer(re.escape(needle),js,re.I)]
    for i,pos in enumerate(starts[:20]):
        out["odap_contexts"].append({"needle":needle,"index":i,"context":js[max(0,pos-2500):min(len(js),pos+5000)]})

Path("reverse_bhoonidhi.json").write_text(json.dumps(out,indent=2)+"\n")
print("--- SCENE_SEARCH SOURCE BEGIN ---")
print(out["scene_search"]["source"])
print("--- SCENE_SEARCH SOURCE END ---")
print("--- UTILS RELEVANT SOURCE BEGIN ---")
for line_no,line in enumerate(out["utils"]["source"].splitlines(),1):
    if 150 <= line_no <= 230:
        print(f"{line_no}: {line}")
print("--- UTILS RELEVANT SOURCE END ---")
print("--- ODAP PRODUCTSEARCH CONTEXTS BEGIN ---")
for item in out["odap_contexts"]:
    if item["needle"].lower() in {"productsearch","searchobject","nissenar","nisar"}:
        print(json.dumps(item))
print("--- ODAP PRODUCTSEARCH CONTEXTS END ---")
