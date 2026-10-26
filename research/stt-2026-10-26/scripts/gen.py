import json, os, sys, urllib.request, subprocess, numpy as np
OUT = sys.argv[1]
os.makedirs(f"{OUT}/wav", exist_ok=True)
KEY = os.environ["OPENROUTER_API_KEY"]
V = {"us": "en-US-Harper", "gb": "en-GB-Harry", "in": "en-IN-Priya", "au": "en-AU-Isla"}
# (id, text, amount, merchant/key noun, date words)
P = [
 ("grab", "grab twelve fifty", "12.50", "grab", None),
 ("maxwell", "lunch at maxwell eight forty", "8.40", "maxwell", None),
 ("rent", "paid the rent", None, "rent", None),
 ("dtf", "dinner sixty at din tai fung, split with ann", "60", "din tai fung", None),
 ("chatgpt", "fifteen usd for chatgpt", "15", "chatgpt", None),
 ("taxi", "taxi home twenty three fifty last friday", "23.50", "taxi", "last friday"),
 ("savings", "move three hundred to savings on the twenty fifth", "300", "savings", "twenty fifth"),
 ("query", "how much did I spend on grab this month", None, "grab", "this month"),
 ("temple", "add a temple visit to day three of my japan trip at two pm", None, "temple", "day three"),
 ("laptop", "one point eight k for a new laptop", "1800", "laptop", None),
 ("netflix", "seventeen ninety nine for netflix", "17.99", "netflix", None),
 ("payback", "ann paid me back forty", "40", "ann", None),
]
VOICE_PAIRS = [("us","gb"),("in","au"),("gb","in"),("au","us")]
rng = np.random.default_rng(7)
manifest = []
for i,(pid,text,amt,noun,date) in enumerate(P):
    for acc in VOICE_PAIRS[i % 4]:
        cid = f"{pid}-{acc}"
        body = json.dumps({"model":"microsoft/mai-voice-2.1-flash","input":text,
            "voice":f"{V[acc]}:MAI-Voice-2.1-Flash","response_format":"pcm"}).encode()
        req = urllib.request.Request("https://openrouter.ai/api/v1/audio/speech", body,
            {"Authorization":f"Bearer {KEY}","Content-Type":"application/json"})
        pcm = urllib.request.urlopen(req, timeout=60).read()
        x = np.frombuffer(pcm, dtype="<i2").astype(np.float32)/32768
        x = np.concatenate([np.zeros(6000,np.float32), x, np.zeros(6000,np.float32)])  # 0.25s pad
        for var in ("clean","noisy"):
            y = x
            if var == "noisy":
                # pink-ish noise + low hum at ~15 dB SNR (cafe/street-ish)
                w = rng.standard_normal(len(x)).astype(np.float32)
                b = np.cumsum(w); b -= np.convolve(b, np.ones(400)/400, "same")  # brown-ish, high-passed
                n = 0.5*w/np.std(w) + 0.5*b/np.std(b)
                t = np.arange(len(x))/24000; n += 0.3*np.sin(2*np.pi*120*t)
                sp = np.sqrt(np.mean(x[np.abs(x)>0.01]**2)); n *= sp/ (10**(15/20)) / np.std(n)
                y = np.clip(x+n, -1, 1)
            wav = f"{OUT}/wav/{cid}-{var}.wav"
            subprocess.run(["ffmpeg","-loglevel","error","-y","-f","f32le","-ar","24000","-ac","1","-i","-",wav],
                           input=y.tobytes(), check=True)
            manifest.append({"clip":f"{cid}-{var}","phrase":pid,"accent":acc,"voice":V[acc],"noise":var,
                "expected":text,"amount":amt,"key_noun":noun,"date_words":date,"seconds":round(len(y)/24000,2)})
        print(cid, flush=True)
json.dump(manifest, open(f"{OUT}/manifest.json","w"), indent=1)
