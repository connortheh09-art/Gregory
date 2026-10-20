import sys, time, wave, os, json, re, collections
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

def _cuda_dlls():
    dirs = []
    for sp in list(sys.path):
        nv = os.path.join(sp, "nvidia")
        if os.path.isdir(nv):
            for sub in os.listdir(nv):
                b = os.path.join(nv, sub, "bin")
                if os.path.isdir(b):
                    dirs.append(b)
    for d in dirs:
        try: os.add_dll_directory(d)
        except Exception: pass
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    return dirs

_CUDA_DIRS = _cuda_dlls()

import numpy as np
import requests

BASE = "http://127.0.0.1:1234/v1"
TOKEN = os.environ.get("LM_API_TOKEN", "")
HDR = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}

SYSTEM = ("You are Greg. You are hanging out in a Discord voice call with your friend Connor. You hear him "
          "talking and you answer out loud. You are dry, quick and genuinely funny, and you actually like Connor. "
          "Keep it to a sentence or two. Just talk, the way a person talks. No narration, no stage directions, "
          "no emoji, no lists.")


def clean(txt):
    t = txt or ""
    t = re.sub(r"\[[^\]]*\]", " ", t)
    t = re.sub(r"\*+", " ", t)
    t = re.sub(r"^\s*(sighs?|long pause|chuckles?|laughs?|grins?|smirks?)[,:.]?\s*", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.encode("ascii", "ignore").decode("ascii").strip()
    return t


def trim(history, keep=12):
    while len(history) > keep + 1:
        del history[1]
    while len(history) > 2 and history[1]["role"] != "user":
        del history[1]

def log(*a):
    print(*a, flush=True)

def pick_model():
    r = requests.get(BASE + "/models", headers=HDR, timeout=15).json()
    ids = [m["id"] for m in r.get("data", [])]
    log("MODELS:", ids)
    for i in ids:
        if "9b" in i.lower() and "flash" in i.lower():
            return i
    return ids[0] if ids else "qwen3.5-9b-deepseek-v4-flash"

def load_whisper():
    from faster_whisper import WhisperModel
    return WhisperModel("small", device="cuda", compute_type="float16")

def record(dur, sr=16000, name=None):
    import soundcard as sc
    mic = None
    if name:
        for m in sc.all_microphones(include_loopback=False):
            if name.lower() in m.name.lower():
                mic = m; break
    if mic is None:
        mic = sc.default_microphone()
    with mic.recorder(samplerate=sr, channels=1) as rec:
        a = rec.record(numframes=int(sr*dur))
    if a.ndim > 1: a = a[:, 0]
    return np.asarray(a, dtype="float32"), sr

def chat(model, history):
    body = {"model": model, "messages": history, "temperature": 0.8,
            "max_tokens": 120, "stream": False,
            "frequency_penalty": 0.6, "presence_penalty": 0.4}
    t0 = time.time()
    r = requests.post(BASE + "/chat/completions", headers=HDR, json=body, timeout=180).json()
    t1 = time.time()
    if "choices" not in r:
        return "[ERR] " + json.dumps(r)[:300], t1-t0, {}
    txt = clean(r["choices"][0]["message"].get("content") or "")
    return txt, t1-t0, r.get("usage", {})


def bench():
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "I didn't know you were listening, so the first couple bits of this are gonna be silent. I was just reading."}]
    def run(model, mt, extra=None, label=""):
        body = {"model": model, "messages": msgs, "temperature": 0.7, "max_tokens": mt, "stream": False}
        if extra: body.update(extra)
        t0 = time.time()
        try:
            r = requests.post(BASE + "/chat/completions", headers=HDR, json=body, timeout=300).json()
        except Exception as e:
            log("%-38s %-18s ERR %s" % (model, label, e)); return
        dt = time.time() - t0
        if "choices" not in r:
            log("%-38s %-18s ERR %s" % (model, label, json.dumps(r)[:150])); return
        u = r.get("usage", {})
        rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
        txt = (r["choices"][0]["message"].get("content") or "").strip().replace("\n", " ")
        log("%-38s %-18s %.2fs reason=%s reply=%r" % (model, label, dt, rt, txt[:150]))
    run("qwen3.5-9b-deepseek-v4-flash", 1500, None, "big-budget")
    run("qwen3.5-9b-deepseek-v4-flash", 400, {"chat_template_kwargs": {"enable_thinking": False}}, "no-think")
    run("google/gemma-4-e4b", 250, None, "gemma-e4b")
    run("magnum-v4-12b", 250, None, "magnum-12b")
    run("qwen2.5-0.5b-instruct", 250, None, "qwen0.5b")


def bench1(model):
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "I didn't know you were listening, so the first couple bits of this are gonna be silent. I was just reading."}]
    body = {"model": model, "messages": msgs, "temperature": 0.7, "max_tokens": 250, "stream": False}
    t0 = time.time()
    try:
        r = requests.post(BASE + "/chat/completions", headers=HDR, json=body, timeout=300).json()
    except Exception as e:
        log("ERR", e); return
    dt = time.time() - t0
    if "choices" not in r:
        log("ERR", json.dumps(r)[:200]); return
    u = r.get("usage", {})
    rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
    txt = (r["choices"][0]["message"].get("content") or "").strip().replace("\n", " ")
    log("%-38s %.2fs reason=%s reply=%r" % (model, dt, rt, txt[:200]))

MODEL_OVERRIDE = "magnum-v4-12b"


def vad_listen(total, micname, model, w, history, thresh=0.006, silence_ms=650.0,
               frame_ms=100, sr=16000, max_utt_s=25.0):
    import soundcard as sc
    mic = None
    for m in sc.all_microphones(include_loopback=False):
        if micname.lower() in m.name.lower():
            mic = m
            break
    if mic is None:
        mic = sc.default_microphone()
    log("VAD listening on", mic.name, "silence_ms=%.0f" % silence_ms)
    t_end = time.time() + total
    preroll = collections.deque(maxlen=4)
    with mic.recorder(samplerate=sr, channels=1) as rec:
        while time.time() < t_end:
            fr = rec.record(numframes=int(sr * frame_ms / 1000.0))
            if fr.ndim > 1:
                fr = fr[:, 0]
            preroll.append(fr)
            if float(np.sqrt(np.mean(np.square(fr)))) < thresh:
                continue
            utt = list(preroll)
            silent = 0.0
            t_start = time.time()
            while time.time() < t_end and (time.time() - t_start) < max_utt_s:
                fr = rec.record(numframes=int(sr * frame_ms / 1000.0))
                if fr.ndim > 1:
                    fr = fr[:, 0]
                utt.append(fr)
                if float(np.sqrt(np.mean(np.square(fr)))) < thresh:
                    silent += frame_ms / 1000.0
                    if silent >= silence_ms / 1000.0:
                        break
                else:
                    silent = 0.0
            audio = np.concatenate(utt)
            dur = len(audio) / float(sr)
            if dur < 0.6:
                continue
            t0 = time.time()
            segs, _ = w.transcribe(audio, language="en")
            text = " ".join(s.text.strip() for s in segs).strip()
            stt = time.time() - t0
            if len(text) < 3:
                log("  (no words in %.1fs utterance)" % dur)
                continue
            history.append({"role": "user", "content": text})
            trim(history)
            reply, llm, usage = chat(model, history)
            history.append({"role": "assistant", "content": reply})
            log("YOU :", text)
            log("GREG:", reply)
            log("TIMING utt %.1fs stt %.2fs llm %.2fs total %.2fs %s" %
                (dur, stt, llm, stt + llm, json.dumps(usage)))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "listen"
    if mode == "bench":
        bench(); return
    if mode == "bench1":
        bench1(sys.argv[2]); return
    micname = "Yeti"
    model = MODEL_OVERRIDE
    log("USING MODEL:", model)
    log("loading whisper...")
    w = load_whisper()
    log("READY. mic =", micname)
    history = [{"role": "system", "content": SYSTEM}]

    if mode == "turns":
        turns = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        secs = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
        for i in range(turns):
            log("--- turn %d: listening %.1fs ---" % (i+1, secs))
            a, sr = record(secs, name=micname)
            t0 = time.time(); segs, _ = w.transcribe(a, language="en")
            text = " ".join(s.text.strip() for s in segs).strip()
            stt = time.time() - t0
            if len(text) < 2:
                log("(nothing heard)"); continue
            history.append({"role": "user", "content": text})
            trim(history)
            reply, llm, usage = chat(model, history)
            history.append({"role": "assistant", "content": reply})
            log("YOU :", text); log("GREG:", reply)
            log("TIMING stt %.2fs llm %.2fs total %.2fs %s" % (stt, llm, stt+llm, json.dumps(usage)))
    else:
        total = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
        thresh = float(sys.argv[3]) if len(sys.argv) > 3 else 0.006
        silence_ms = float(sys.argv[4]) if len(sys.argv) > 4 else 650.0
        vad_listen(total, micname, model, w, history, thresh, silence_ms)
        log("LISTEN WINDOW DONE")

main()
