import json, re, sys, collections
from decimal import Decimal as D
OUT, RES = sys.argv[1], sys.argv[2]
man = {c["clip"]: c for c in json.load(open(f"{OUT}/manifest.json"))}
rows = [json.loads(l) for l in open(RES)]
U = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
T = {w: 10*i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
NUMW = set(U) | set(T) | {"hundred","thousand","k","point","oh","grand"}
def words_to_vals(tokens):
    """Spoken amount patterns in a run of number words -> candidate values."""
    out = set()
    def small(ts):  # 0..99
        if len(ts)==1 and ts[0] in U: return U.index(ts[0])
        if len(ts)==1 and ts[0] in T: return T[ts[0]]
        if len(ts)==2 and ts[0] in T and ts[1] in U[1:10]: return T[ts[0]]+U.index(ts[1])
    n = len(tokens)
    for i in range(n):
        for j in range(i+1, n+1):
            ts = tokens[i:j]
            v = small(ts)
            if v is not None: out.add(D(v))
            if len(ts)>=2 and ts[-1] in ("hundred",) and small(ts[:-1]) is not None: out.add(D(small(ts[:-1])*100))
            if "point" in ts:  # one point eight k
                k = ts.index("point"); a, b = small(ts[:k]), ts[k+1:]
                mult = 1000 if b and b[-1] in ("k","thousand","grand") else 1
                if mult>1: b = b[:-1]
                if a is not None and b and all(x in U[:10] for x in b):
                    out.add(D(f"{a}.{''.join(str(U.index(x)) for x in b)}")*mult)
            for s in range(1, len(ts)):  # "twelve fifty", "seventeen ninety nine"
                a, b = small(ts[:s]), small(ts[s:])
                if a is not None and b is not None and b>=10: out.add(D(a)+D(b)/100)
    return out
def amounts(text):
    t = text.lower().replace(",", "")
    strict, lenient = set(), set()
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(k\b|thousand|grand)?", t):
        v = D(m.group(1)) * (1000 if m.group(2) else 1); strict.add(v)
    for m in re.finditer(r"(\d+)\.?\s+(\d{2})\b", t):  # "12. 50" / "12 50"
        lenient.add(D(f"{m.group(1)}.{m.group(2)}"))
    toks = re.findall(r"[a-z]+|\d+", t)
    run=[]
    for w in toks+["_end"]:
        if w in NUMW: run.append(w)
        else:
            if run: strict |= words_to_vals(run)
            run=[]
    return strict, strict|lenient
def norm(s): return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()
def wer(ref, hyp):
    r = [w for w in norm(ref) if w not in NUMW and not w.isdigit() and w not in ("pm","usd")]
    h = [w for w in norm(hyp) if w not in NUMW and not w.isdigit() and w not in ("pm","usd","p","m","dollars","dollar")]
    d = list(range(len(h)+1))
    for i in range(1,len(r)+1):
        p, d[0] = d[0], i
        for j in range(1,len(h)+1):
            p, d[j] = d[j], min(d[j]+1, d[j-1]+1, p+(r[i-1]!=h[j-1]))
    return d[len(h)], len(r)
NOUN = {"din tai fung":["dintaifung"],"chatgpt":["chatgpt"],"ann":["ann"]}
def noun_ok(noun, hyp):
    c = re.sub(r"[^a-z]", "", hyp.lower()); w = norm(hyp)
    if noun == "ann": return "ann" in w or "anne" in w
    return re.sub(r"[^a-z]","",noun) in c
def pct(xs, p):
    xs = sorted(xs); return xs[min(len(xs)-1, int(round(p*(len(xs)-1))))]
S = collections.defaultdict(lambda: collections.defaultdict(list))
fails = collections.defaultdict(list)
for r in rows:
    c = man[r["clip"]]; m = r["model"]
    for key in [(m,"all"), (m,r["fmt"]), (m,c["noise"])]:
        S[key]["n"].append(1)
        if not r["ok"]: S[key]["rej"].append(1); continue
        hyp = r["text"] or ""
        S[key]["lat"].append(r["latency"])
        S[key]["cost"].append((r["usage"] or {}).get("cost") or 0); S[key]["sec"].append(c["seconds"])
        if c["amount"]:
            st, le = amounts(hyp); exp = D(c["amount"])
            S[key]["amt"].append(exp in st); S[key]["amt_len"].append(exp in le)
            dg = re.sub(r"\.0+$","",f"{exp:.2f}").replace(".",""); S[key]["heard"].append(exp in le or dg in re.sub(r"[^0-9 ]","",hyp).replace(" ",""))
            if key[1]=="all" and exp not in st: fails[m].append((r["clip"], r["fmt"], "amount", hyp))
        ok = noun_ok(c["key_noun"], hyp); S[key]["noun"].append(ok)
        if key[1]=="all" and not ok: fails[m].append((r["clip"], r["fmt"], "noun", hyp))
        e, n = wer(c["expected"], hyp); S[key]["we"].append(e); S[key]["wn"].append(n)
models = sorted({k[0] for k in S})
def line(k):
    s = S[k]; f = lambda xs: f"{100*sum(xs)/len(xs):.1f}%" if xs else "-"
    cpm = 60*sum(s["cost"])/sum(s["sec"]) if s["sec"] else 0
    return (f"| {k[0]} | {k[1]} | {len(s['n'])} | {f(s['amt'])} | {f(s['amt_len'])} | {f(s['heard'])} | {f(s['noun'])} | "
            f"{100*sum(s['we'])/max(1,sum(s['wn'])):.1f}% | {pct(s['lat'],.5):.2f}s | {pct(s['lat'],.9):.2f}s | ${cpm:.4f} | {len(s['rej'])} |")
print("| model | slice | calls | amount exact (strict) | amount (lenient) | amount digits heard | key noun | WER (non-number words) | p50 | p90 | $/min (billed) | rejected |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")
for m in models:
    for sl in ["all","ogg","webm","mp4","clean","noisy"]:
        if (m,sl) in S: print(line((m,sl)))
json.dump({m: fails[m] for m in models}, open(sys.argv[3], "w"), indent=1)
