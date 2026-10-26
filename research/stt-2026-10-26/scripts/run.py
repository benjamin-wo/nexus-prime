import json, os, sys, time, base64, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
OUT, RES = sys.argv[1], sys.argv[2]
MODELS = sys.argv[3].split(",")
KEY = os.environ["OPENROUTER_API_KEY"]
man = json.load(open(f"{OUT}/manifest.json"))
FMTS = [x for x in [("ogg","ogg","ogg"),("webm","webm","webm"),("mp4","m4a","m4a")] if x[0] in os.environ.get("FMTS","ogg,webm,mp4")]
EXTRA = json.loads(os.environ.get("EXTRA","{}"))
TAG = os.environ.get("TAG","")
done = set()
if os.path.exists(RES):
    for l in open(RES): r=json.loads(l); done.add((r["model"].removesuffix(TAG) if TAG else r["model"],r["clip"],r["fmt"]))
jobs = [(m,c["clip"],f,ext,fmt) for m in MODELS for c in man for (f,ext,fmt) in FMTS if (m,c["clip"],f) not in done]
def call(j):
    m,clip,f,ext,fmt = j
    data = base64.b64encode(open(f"{OUT}/clips/{f}/{clip}.{ext}","rb").read()).decode()
    body = json.dumps({"model":m,"input_audio":{"data":data,"format":fmt},"language":"en","temperature":0, **EXTRA}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/audio/transcriptions", body,
        {"Authorization":f"Bearer {KEY}","Content-Type":"application/json"})
    t=time.time(); r={"model":m+TAG,"clip":clip,"fmt":f}
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=90).read())
        r.update(ok=True, text=resp.get("text"), usage=resp.get("usage"))
    except urllib.error.HTTPError as e:
        r.update(ok=False, status=e.code, error=e.read().decode(errors="replace")[:400])
    except Exception as e:
        r.update(ok=False, status=None, error=repr(e)[:400])
    r["latency"]=round(time.time()-t,3)
    return r
with ThreadPoolExecutor(6) as ex, open(RES,"a") as fo:
    for i,r in enumerate(ex.map(call, jobs)):
        fo.write(json.dumps(r)+"\n"); fo.flush()
        if not r["ok"]: print("ERR", r["model"], r["clip"], r["fmt"], r.get("status"), r["error"][:150], flush=True)
print("done", len(jobs))
