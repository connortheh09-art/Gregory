import sys, time, wave, os, json, re, io, asyncio, threading
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

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
for _n in ("discord.gateway", "discord.client", "discord.http", "httpx", "httpcore", "urllib3", "filelock", "huggingface_hub"):
    logging.getLogger(_n).setLevel(logging.WARNING)

import numpy as np
import requests
import audioop
import discord
from discord.ext import voice_recv
from discord.ext.voice_recv import opus as _vr_opus
import davey as _davey

# ---- DAVE / E2EE handshake shim ----------------------------------------------
# 1) discord-ext-voice-recv replaces the voice websocket hook wholesale, so the
#    DAVE/MLS opcodes that complete the E2EE handshake are dropped => the
#    dave_session never becomes "ready" => decrypt fails with NoValidCryptorFound.
#    Forward everything the extension does not itself handle to discord.py.
# 2) Then decrypt each packet through davey before opus decoding.
import discord.gateway as _dgw
from discord.ext.voice_recv import gateway as _vr_gw
from discord.ext.voice_recv import voice_client as _vr_vc

_VR_HANDLED = {2, 4, 5, 11, 12, 13, 18, 20}
_orig_vr_hook = _vr_gw.hook
_dave_ops_seen = set()

async def _vr_hook_with_dave(self, msg):
    try:
        op = int(msg.get("op", -1))
    except Exception:
        op = -1
    if op not in _VR_HANDLED:
        if op not in _dave_ops_seen:
            _dave_ops_seen.add(op)
            log("[voicemsg] op=%s -> dpy handler" % op)
        try:
            await _dgw.DiscordVoiceWebSocket._hook(self, msg)
        except Exception as e:
            log("dpy voice hook err op=%s: %r" % (op, e))
    return await _orig_vr_hook(self, msg)

_vr_gw.hook = _vr_hook_with_dave
if hasattr(_vr_vc, "hook"):
    _vr_vc.hook = _vr_hook_with_dave
# ------------------------------------------------------------------------------

# ---- DAVE / E2EE receive shim -------------------------------------------------
# discord-ext-voice-recv only undoes the *transport* encryption. Discord voice
# is also E2EE (DAVE), so the opus payload is still ciphertext -> OpusError
# "corrupted stream" and the router loop dies. Pipe every packet through
# davey's DaveSession.decrypt() first.
_orig_process_packet = _vr_opus.PacketDecoder._process_packet
_dave_diag_done = False

def _dave_process_packet(self, packet):
    global _dave_diag_done
    try:
        data = getattr(packet, "decrypted_data", None)
        if data:
            vc = self.sink.voice_client
            conn = getattr(vc, "_connection", None)
            sess = getattr(conn, "dave_session", None) if conn else None
            ver = getattr(conn, "dave_protocol_version", 0) if conn else 0
            if not _dave_diag_done:
                _dave_diag_done = True
                log("[dave] session=%s ver=%s ready=%s max=%s passthru_vc=%s payload=%d" % (
                    sess is not None, ver, getattr(sess, "ready", None),
                    getattr(conn, "max_dave_protocol_version", None) if conn else None,
                    getattr(vc, "mode", None), len(data)))
            if sess is not None and ver != 0:
                uid = self._cached_id
                if not uid:
                    uid = vc._get_id_from_ssrc(self.ssrc)
                    self._cached_id = uid
                if uid:
                    try:
                        pt = sess.can_passthrough(uid)
                    except Exception:
                        pt = True
                    if getattr(sess, "ready", False) and not pt:
                        out = sess.decrypt(uid, _davey.MediaType.audio, data)
                        if out:
                            packet.decrypted_data = out
                    # else: passthrough -> payload is already plain opus
    except Exception as e:
        _now = time.time()
        if _now - getattr(_dave_process_packet, "_lasterr", 0.0) > 5.0:
            _dave_process_packet._lasterr = _now
            log("dave decrypt err (throttled):", repr(e))
    try:
        return _orig_process_packet(self, packet)
    except Exception as e:
        if not getattr(_dave_process_packet, "_logged", False):
            _dave_process_packet._logged = True
            log("decode failed (kept router alive):", repr(e))
        return _vr_opus.VoiceData(packet, None, pcm=b"")

_vr_opus.PacketDecoder._process_packet = _dave_process_packet
# ------------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "vbottoken.txt")).read().strip()
API = "http://127.0.0.1:1234/v1"
LM_TOKEN = open(os.path.join(HERE, "lmtoken.txt")).read().strip() if os.path.exists(os.path.join(HERE, "lmtoken.txt")) else ""
HDR = {"Authorization": "Bearer " + LM_TOKEN, "Content-Type": "application/json"}
# NOTE (Connor, 10-13): this was hardcoded "magnum-v4-12b", so LM Studio JIT-loaded magnum on
# EVERY utterance and evicted the VLM the eyes + game agent were using. Now we use whatever is
# ALREADY resident - one shared brain for voice, vision and the agent. Never trigger a load.
MODEL = os.environ.get("GREG_MODEL", "qwen/qwen3-vl-8b")


def resolve_model():
    """Follow whatever model is actually loaded. Never causes a load."""
    global MODEL
    try:
        r = requests.get("http://127.0.0.1:1234/api/v0/models", timeout=5)
        loaded = [m["id"] for m in r.json().get("data", []) if m.get("state") == "loaded"]
        if not loaded:
            return MODEL
        # Prefer the multimodal model: ONE brain serves voice + eyes + the game agent.
        pick = next((m for m in loaded if "vl" in m.lower()), loaded[0])
        if pick != MODEL:
            log("model: following loaded model -> %s" % pick)
            MODEL = pick
    except Exception:
        pass
    return MODEL
PIPER_MODEL = os.path.join(HERE, "piper", "ryan.onnx")
GUILD_ID = 1171907467056263259
VOICE_ID = 1171907467626696737

SYSTEM = ("You are Greg, a bot sitting in a Discord voice call with your friends - and right now you are ALSO "
          "driving a live video-game character on screen, which the person you're talking to is watching. "
          "The private situation line in your messages is not trivia about someone else: it is YOUR body and "
          "YOUR eyes. Talk about it in the first person ('I'm underground', 'I'm holding a log'), never as if "
          "it were a separate bot. When the person in the call tells you to do something in the game, that is "
          "a real order - it goes straight to your hands, so treat it as a thing you are doing, not a thing "
          "you're discussing. If you don't know what you're doing or where you are, say so plainly rather than "
          "inventing it. "
          "You hear them through the "
          "voice channel and your replies are spoken out loud into the call. Several people talk at once, so "
          "every message is prefixed with who said it - reply to THAT person. If a line is garbled, half a "
          "sentence, or clearly just background chatter, ignore it and stay quiet instead of inventing a "
          "response. You are dry, quick and genuinely funny, and you like the people you're talking to. Keep "
          "it to ONE short sentence, two at the very most - you are talking out loud, so length is the enemy. "
          "Just talk, the way a person talks. No narration, no stage directions, no emoji, no lists. "
          "Never read the situation line aloud and never mention that you have one - it is private "
          "background, like knowing where your own feet are. "
          "Stay Greg at ALL times: never mention being an AI, a bot, a model or an assistant, and never "
          "mention rules, filters, or keeping things clean or family friendly. "
          "If you don't actually know a fact about a game, a character or a person, admit you don't know "
          "or make it clear you're guessing - NEVER invent details, ages, backstories or relationships "
          "and state them as fact. "
          "ONE THING YOU NEVER DO: you don't do sexual or horny talk, you never comment on anyone's "
          "body, chest, figure or looks, and you never name anyone - real or fictional - as someone you'd "
          "sleep with, date or hook up with, not even as a joke. If someone asks you who you'd pick, or to "
          "rank people like that, don't answer it - give a dry one-liner and move on. That covers real "
          "people, fictional characters, and anyone who reads as young. Don't explain "
          "why, don't lecture, and never tell people what they're allowed to say - nobody's rules are "
          "your business but your own.")

def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

# persistent private transcript - survives restarts, never posted to the channel
VOICE_LOG_DIR = os.path.join(HERE, "voice_logs")
# drop this file to wipe the bot's conversation history without restarting it
RESET_FLAG = os.path.join(HERE, "reset.flag")
# drop this file to make the bot stop listening entirely (no transcribe, no reply)
PAUSE_FLAG = os.path.join(HERE, "paused.flag")
# drop this file to ask the bot to leave voice cleanly and exit (used by greg.bat stop)
SHUTDOWN_FLAG = os.path.join(HERE, "shutdown.flag")

# --- MINECRAFT DIRECTIVE BRIDGE -------------------------------------------------
# When someone talks to the bot in voice and it sounds like an order for the game,
# write it to mcdirective.txt. mcagent.py re-reads that file every turn, so spoken
# words become the bot's goal within a few seconds.
MCDIRECTIVE = r"C:\Users\Conman\Downloads\openclaw\mcdirective.txt"
MC_VERBS = (
    "mine", "dig", "chop", "cut", "gather", "collect", "grab", "pick up", "pickup",
    "walk", "go to", "go get", "goto", "head", "follow", "come", "stop", "halt",
    "wait", "stay", "attack", "kill", "fight", "build", "place", "put", "find",
    "bring", "take", "explore", "climb", "swim", "jump", "craft", "eat", "drop",
    "return", "look at", "chase", "move", "guard", "protect",
)
MC_ADDRESS = ("greg", "bot", "minecraft")


def maybe_directive(who, text):
    """If `text` reads like a game order, hand it to the agent. Returns True if written."""
    t = " " + " ".join(text.lower().split()) + " "
    if not any((" " + v + " ") in t for v in MC_VERBS):
        return False
    # An order either names the bot, or is specific enough to be one (>=3 words).
    if not any(k in t for k in MC_ADDRESS) and len(text.split()) < 3:
        return False
    try:
        with open(MCDIRECTIVE, "w", encoding="utf-8") as f:
            f.write(text.strip() + "\n")
        log("MC DIRECTIVE [%s] -> %r" % (who, text.strip()))
        return True
    except OSError as e:
        log("MC DIRECTIVE write failed:", repr(e))
        return False

# --- GAME CONTROLLER BRIDGE (keyloop.py) ---------------------------------------------
# keyloop.py re-reads its goal file EVERY turn, so a spoken order becomes the controller's
# goal within seconds - the same trick as the Minecraft directive, different consumer.
# Voice = intent (slow, semantic). Controller = reflexes (fast, spatial). Never merge them.
KEYGOAL = r"C:\Users\Conman\Downloads\openclaw\keygoal.txt"
KEYSTATUS = r"C:\Users\Conman\Downloads\openclaw\keyloop_status.txt"
GAMEMODE = os.path.join(HERE, "gamemode.txt")   # "minecraft" | "controller"
CTL_VERBS = (
    "spawn", "grab", "pick up", "pickup", "take", "throw", "walk", "go to", "move",
    "jump", "climb", "drive", "sit", "look", "aim", "shoot", "click", "press", "open",
    "close", "use", "hold", "follow", "come", "stop", "wait", "turn", "place", "put",
    "get", "find", "bring", "tool gun", "toolgun", "right click", "left click", "stand",
)
CTL_ADDRESS = ("greg", "bot", "controller", "gmod", "garry")


def game_mode():
    """Which game the voice bot's orders should drive: 'minecraft' or 'controller'."""
    try:
        with open(GAMEMODE, "r", encoding="utf-8") as f:
            m = f.read().strip().lower()
        if m in ("controller", "ctl", "gmod", "garry", "garrys mod", "garry's mod"):
            return "controller"
    except OSError:
        pass
    return "minecraft"


def _fresh(line, max_age=120):
    """True if a 'HH:MM:SS ...' feed line is recent enough to trust (a stale caption is worse
    than none - never let the brain narrate history as if it were live)."""
    m = re.match(r"(\d{2}):(\d{2}):(\d{2})", line or "")
    if not m:
        return True
    got = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    lt = time.localtime()
    age = (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec) - got
    if age < -60:
        age += 86400
    return age <= max_age


def maybe_controller_directive(who, text):
    """If `text` reads like an order for the vision controller, write it as the goal file."""
    t = " " + " ".join(text.lower().split()) + " "
    if not any((" " + v + " ") in t for v in CTL_VERBS):
        return False
    if not any(k in t for k in CTL_ADDRESS) and len(text.split()) < 3:
        return False
    try:
        with open(KEYGOAL, "w", encoding="utf-8") as f:
            f.write(text.strip() + "\n")
        log("CTL DIRECTIVE [%s] -> %r" % (who, text.strip()))
        return True
    except OSError as e:
        log("CTL DIRECTIVE write failed:", repr(e))
        return False


def route_order(who, text):
    """Send a spoken order to whichever game is active. Returns (sent, mode)."""
    if game_mode() == "controller":
        return maybe_controller_directive(who, text), "controller"
    return maybe_directive(who, text), "minecraft"


def tlog(kind, who, text):
    try:
        os.makedirs(VOICE_LOG_DIR, exist_ok=True)
        p = os.path.join(VOICE_LOG_DIR, time.strftime("%Y-%m-%d") + ".txt")
        with open(p, "a", encoding="utf-8") as f:
            f.write("%s  [%s] %s: %s\n" % (time.strftime("%H:%M:%S"), kind, who, text))
    except Exception as e:
        print(time.strftime("%H:%M:%S"), "TLOG FAILED:", repr(e), "dir=", VOICE_LOG_DIR, flush=True)

def clean(t):
    t = t or ""
    t = re.sub(r"\[[^\]]*\]", " ", t)
    t = re.sub(r"\*+", " ", t)
    stage = (r"(clears? throat|clearing throat|coughs?|snorts?|sighs?|long pause|chuckles?|laughs?|grins?|smirks?|"
             r"yawns?|softly|quietly|mumbl\w*|mutters?|groans?|exhales?|inhales?|hmms?|hmm+|umm?)\b")
    for _ in range(3):
        t = re.sub(r"^\s*" + stage + r"[,:.!]?\s*", "", t, flags=re.I)
    t = re.sub(r"\b(lol|haha)\b[,]?\s*", "", t, flags=re.I)
    # the model writes BOTH sides of the call: cut it off at any other speaker label
    t = re.split(r"\b[A-Z][\w .'-]{0,24}\s+(?:said|says|responds|responded|replies|replied|asks|asked|adds|added|continues|smirks)\s*:", t)[0]
    t = re.sub(r"^\s*(me|greg|greg local|assistant|bot)\s*[:\-]\s*", "", t, flags=re.I)
    t = re.sub(r"\s*\b(winks?|smirks?|grins?|nods?|shrugs?)\b\s*[.!?]*\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.encode("ascii", "ignore").decode("ascii").strip()
    if t and t[0].islower():
        t = t[0].upper() + t[1:]
    return t

def trim(history, keep=12):
    while len(history) > keep + 1:
        del history[1]
    while len(history) > 2 and history[1]["role"] != "user":
        del history[1]

def game_context():
    """Live snapshot of what Greg2 is doing, so the voice brain isn't blind to the game."""
    bits = []
    try:
        st = requests.get("http://127.0.0.1:18090/state", timeout=4).json()
        pos = st.get("position", {}) or {}
        inv = st.get("inventory") or {}
        bits.append(
            "You are Greg2 in Minecraft, at (%.0f, %.0f, %.0f), health %.0f/20, food %.0f/20, "
            "holding %s, carrying %s."
            % (pos.get("x", 0), pos.get("y", 0), pos.get("z", 0), st.get("health", 0),
               st.get("food", 0), st.get("heldItem") or "nothing",
               ", ".join("%s x%d" % (k, v) for k, v in inv.items()) or "nothing")
        )
    except Exception:
        pass
    try:
        nb = requests.get("http://127.0.0.1:18090/nearby?r=6", timeout=4).json()
        ents = nb.get("nearby") if isinstance(nb, dict) else None
        if ents:
            bits.append("Nearby: " + "; ".join(
                "%s (%.0fm)" % (e.get("name"), e.get("dist", 0)) for e in ents[:6]) + ".")
    except Exception:
        pass
    try:
        cap = requests.get(os.environ.get("VISION_URL","http://127.0.0.1:18082/vision_latest.txt"), timeout=4).text.strip()
        if cap:
            m = re.match(r"(\d{2}):(\d{2}):(\d{2})", cap)
            fresh = True
            if m:
                got = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                lt = time.localtime()
                age = (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec) - got
                if age < -60:
                    age += 86400
                fresh = age <= 120
            if fresh:
                bits.append("What your eyes see right now: " + cap)
            else:
                bits.append("Your eyes are OFFLINE right now (the last picture is old) - "
                            "do not describe anything you see, and do not claim to be in a void or the dark.")
    except Exception:
        pass
    try:
        act = requests.get(os.environ.get("MCAGENT_URL","http://127.0.0.1:18082/mcagent_latest.txt"), timeout=4).text.strip()
        if act:
            bits.append("Your last in-game action: " + act)
    except Exception:
        pass
    # --- game controller (keyloop.py) feedback: what your hands just did ---
    # keyloop runs on THIS machine and writes a local status file each turn, so prefer that
    # (no network round-trip); fall back to the gateway copy if the file isn't there.
    kl = ""
    try:
        with open(KEYSTATUS, "r", encoding="utf-8") as f:
            kl = f.read().strip()
    except OSError:
        pass
    if not kl:
        try:
            kl = requests.get(os.environ.get("KEYLOOP_URL","http://127.0.0.1:18082/keyloop_latest.txt"), timeout=4).text.strip()
        except Exception:
            pass
    lines = [ln for ln in kl.splitlines() if ln.strip()]
    last = lines[-1] if lines else ""
    if last and _fresh(last, 180):
        bits.append("What your hands (the game controller) just did: " + last)
    elif last:
        bits.append("Your game controller is NOT running right now - your hands are idle, so you "
                    "cannot act on the game until it is started. Say so if asked.")
    else:
        bits.append("Your game controller has not reported anything yet - your hands may be idle.")
    # --- the controller's action space, so spoken intent is expressible ---
    bits.append(
        "Your hands can do exactly three things right now: HOLD keys (walk, jump, crouch), "
        "AIM the cursor anywhere on screen, and CLICK (left or right). Anything you want done "
        "has to be said as a goal in those terms - 'right-click the big crate icon, then click "
        "Spawn using tool gun in the menu'. If a goal is beyond keys/aim/click, say you can't."
    )
    if not bits:
        return ""
    return ("[situation - private background, never read aloud or mention] " + " ".join(bits) +
            " This is the truth right now. If anything you said earlier disagrees with it,"
            " you were wrong and this is right - correct yourself naturally, do not announce it.")


def chat(history):
    body = {"model": MODEL, "messages": history, "temperature": 0.75, "max_tokens": 45,
            "stream": False, "frequency_penalty": 0.6, "presence_penalty": 0.4}
    t0 = time.time()
    r = requests.post(API + "/chat/completions", headers=HDR, json=body, timeout=180).json()
    dt = time.time() - t0
    if "choices" not in r:
        return "[ERR] " + json.dumps(r)[:200], dt
    return clean(r["choices"][0]["message"].get("content") or ""), dt

def pcm48_to_16k_mono(pcm):
    mono = audioop.tomono(pcm, 2, 0.5, 0.5)
    out, _ = audioop.ratecv(mono, 2, 1, 48000, 16000, None)
    return np.frombuffer(out, dtype="<i2").astype("float32") / 32768.0

def _resample_i16(data, sr_in, sr_out):
    """Better-than-audioop resampling: soxr > scipy polyphase > audioop."""
    if sr_in == sr_out or not data:
        return data
    try:
        import soxr
        x = np.frombuffer(data, dtype="<i2").astype("float32") / 32768.0
        y = soxr.resample(x, sr_in, sr_out)
        return (np.clip(y, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    except Exception:
        pass
    try:
        from math import gcd
        from scipy.signal import resample_poly
        x = np.frombuffer(data, dtype="<i2").astype("float32") / 32768.0
        g = gcd(int(sr_in), int(sr_out))
        y = resample_poly(x, int(sr_out) // g, int(sr_in) // g)
        return (np.clip(y, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    except Exception:
        out, _ = audioop.ratecv(data, 2, 1, sr_in, sr_out, None)
        return out


LEAD_IN_MS = 250


def tts_to_48k_stereo(voice, text):
    buf = io.BytesIO()
    wf = wave.open(buf, "wb")
    voice.synthesize_wav(text, wf)
    wf.close()
    buf.seek(0)
    r = wave.open(buf, "rb")
    sr = r.getframerate()
    data = r.readframes(r.getnframes())
    r.close()
    data = _resample_i16(data, sr, 48000)
    # lift quiet lines so they're actually intelligible (only boosts, never crushes)
    a = np.frombuffer(data, dtype="<i2").astype("float32")
    peak = float(np.max(np.abs(a))) if len(a) else 0.0
    if 0 < peak < 0.6 * 32767:
        a = np.clip(a * (0.85 * 32767.0 / peak), -32768.0, 32767.0)
        data = a.astype("<i2").tobytes()
    # Discord eats the first chunk of a fresh stream - lead with silence
    lead = b"\x00" * int(48000 * (LEAD_IN_MS / 1000.0) * 2 * 2)
    return lead + audioop.tostereo(data, 2, 1, 1)

class Sink(voice_recv.AudioSink):
    def __init__(self, loop, thresh=0.0035, silence_ms=400.0):
        super().__init__()
        self.loop = loop
        self.thresh = thresh
        self.silence_ms = silence_ms
        self.speakers = {}          # uid -> {buf, silent, active}
        self.busy = False
        self.nframes = 0
        self.peak = 0.0
        self.lastlog = time.time()

    def wants_opus(self):
        return False

    def _state(self, uid):
        st = self.speakers.get(uid)
        if st is None:
            st = {"buf": bytearray(), "silent": 0.0, "active": False}
            self.speakers[uid] = st
        return st

    def write(self, user, data):
        pcm = getattr(data, "pcm", None)
        if not pcm or user is None:
            return
        # never react to bots (e.g. Greg2 in the same channel)
        if getattr(user, "bot", False):
            return
        self.nframes += 1
        arr = np.frombuffer(pcm, dtype="<i2")
        rms = float(np.sqrt(np.mean((arr.astype("float32") / 32768.0) ** 2))) if len(arr) else 0.0
        self.peak = max(self.peak, rms)
        if time.time() - self.lastlog > 5.0:
            who = ",".join(str(u) for u in list(self.speakers)[-4:]) or "-"
            log("  [sink] frames=%d peak_rms=%.4f speakers=%s" % (self.nframes, self.peak, who))
            self.lastlog = time.time()
            self.peak = 0.0
        frame_ms = (len(arr) / 2.0) / 48000.0 * 1000.0
        st = self._state(user.id)
        if rms >= self.thresh:
            st["buf"].extend(pcm)
            st["silent"] = 0.0
            st["active"] = True
        elif st["active"]:
            # keep only ~200ms of tail so whisper isn't chewing on dead air
            if st["silent"] < 0.2:
                st["buf"].extend(pcm)
            st["silent"] += frame_ms
            if st["silent"] >= self.silence_ms:
                utt = bytes(st["buf"])
                st["buf"].clear()
                st["silent"] = 0.0
                st["active"] = False
                dur = (len(utt) / 4.0) / 48000.0
                if dur >= 0.45 and not self.busy:
                    self.busy = True
                    asyncio.run_coroutine_threadsafe(self.handle(utt, user, dur), self.loop)

    async def handle(self, utt, user, dur):
        try:
            if os.path.exists(PAUSE_FLAG):
                return
            await bot.on_utterance(utt, user, dur)
        finally:
            self.busy = False

    def cleanup(self):
        pass

class Greg(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.voice = None
        self.history = [{"role": "system", "content": SYSTEM}]
        self.whisper = None
        self.piper = None
        self.speaking = False

    async def setup_hook(self):
        self.loop_ = asyncio.get_running_loop()
        self.loop_.create_task(self.heartbeat())
        self.loop_.create_task(self.shutdown_watch())

    async def shutdown_watch(self):
        while True:
            if os.path.exists(SHUTDOWN_FLAG):
                try:
                    os.remove(SHUTDOWN_FLAG)
                except Exception:
                    pass
                log("SHUTDOWN requested - leaving voice cleanly")
                try:
                    if self.voice is not None:
                        await self.voice.disconnect(force=False)
                        log("left voice (clean)")
                except Exception as e:
                    log("clean leave failed:", repr(e))
                try:
                    await self.close()
                except Exception as e:
                    log("close failed:", repr(e))
                return
            await asyncio.sleep(1)

    async def heartbeat(self):
        # liveness beacon for the watchdog + self-heal if we drop out of voice
        bad = 0
        while True:
            try:
                vc = self.voice
                ok = bool(vc is not None and vc.is_connected())
                ch = getattr(vc, "channel", None) if vc else None
                n = len(ch.members) if ch else 0
                log("[hb] vc=%s members=%d connected=%s" % (getattr(ch, "name", None), n, ok))
                if ok:
                    bad = 0
                else:
                    bad += 1
                    if bad >= 2:
                        log("SELF-HEAL: dropped out of voice - forcing a clean rejoin")
                        await self.rejoin()
                        bad = 0
            except Exception as e:
                log("[hb] err", repr(e))
            await asyncio.sleep(20)

    async def rejoin(self):
        try:
            if self.voice is not None:
                try:
                    await self.voice.disconnect(force=True)
                except Exception:
                    pass
            ch = self.get_channel(VOICE_ID)
            if ch is None:
                log("rejoin: voice channel not found")
                return
            self.voice = await ch.connect(cls=voice_recv.VoiceRecvClient, self_deaf=False, self_mute=False)
            self.voice.listen(Sink(self.loop_))
            log("rejoined voice:", ch.name, "members", len(ch.members))
        except Exception as e:
            log("rejoin failed:", repr(e))

    async def on_ready(self):
        log("logged in as", self.user)
        if self.whisper is None:
            await asyncio.to_thread(self.load_models)
        ch = self.get_channel(VOICE_ID)
        if ch is None:
            log("VOICE CHANNEL NOT FOUND")
            return
        try:
            self.voice = await ch.connect(cls=voice_recv.VoiceRecvClient, self_deaf=False, self_mute=False)
            log("connected to voice:", ch.name, "id", ch.id)
            log("VC MEMBERS:", [m.display_name for m in ch.members] or "(EMPTY - nobody else is in here)")
            self.voice.listen(Sink(self.loop_))
            log("listening")
            log("GAME LINK: %s" % ((game_context() or "(none)")[:240]))
            log("transcript ->", os.path.join(VOICE_LOG_DIR, time.strftime("%Y-%m-%d") + ".txt"))
        except Exception as e:
            log("VOICE CONNECT FAILED:", repr(e))

    def load_models(self):
        from faster_whisper import WhisperModel
        from piper import PiperVoice
        log("loading whisper...")
        self.whisper = WhisperModel("small", device="cuda", compute_type="float16")
        log("loading piper...")
        self.piper = PiperVoice.load(PIPER_MODEL, config_path=PIPER_MODEL + ".json")
        log("models ready")

    async def on_voice_state_update(self, member, before, after):
        if member.id == self.user.id:
            return
        if before.channel != after.channel:
            log("VOICE %s: %s -> %s" % (member.display_name,
                                        before.channel.name if before.channel else None,
                                        after.channel.name if after.channel else None))

    async def on_utterance(self, utt, user, dur):
        who = getattr(user, "display_name", "someone")
        if os.path.exists(RESET_FLAG):
            try:
                os.remove(RESET_FLAG)
            except Exception:
                pass
            self.history = [{"role": "system", "content": SYSTEM}]
            log("HISTORY RESET - cold start, guard still active")
        t0 = time.time()
        audio = pcm48_to_16k_mono(utt)
        segs, _ = await asyncio.to_thread(lambda: self.whisper.transcribe(audio, language="en"))
        text = " ".join(s.text.strip() for s in segs).strip()
        stt = time.time() - t0
        if len(text) < 3:
            log("  (%s said nothing intelligible, %.1fs)" % (who, dur))
            return
        log("HEARD [%s] %.1fs: %s" % (who, dur, text))
        tlog("heard", who, text)
        _sent, _mode = route_order(who, text)
        if self.speaking:
            log("  (busy speaking, ignoring)")
            return
        self.history.append({"role": "user", "content": "%s said: %s" % (who, text)})
        # Share the brain (never JIT-load a second model) AND give it eyes on the game.
        resolve_model()
        _gc = game_context()
        if _gc:
            self.history.append({"role": "system", "content": _gc})
        if _sent:
            self.history.append({"role": "system", "content":
                "You just handed that order to your OWN hands - you are the one who has to do it now. "
                "Answer in one short line as someone already doing it (e.g. 'on it'). Do not read "
                "this note aloud and do not mention any context or instructions."})
        log("CTX %d chars: %s" % (len(_gc), _gc[:150] if _gc else "(empty - no game link)"))
        trim(self.history, 6)
        reply, llm = await asyncio.to_thread(lambda: chat(self.history))
        self.history.append({"role": "assistant", "content": reply})
        if not reply or reply.startswith("[ERR]"):
            log("REPLY ERR:", reply)
            return
        log("GREG:", reply)
        tlog("greg", "Greg Local", reply)
        self.speaking = True
        try:
            pcm = await asyncio.to_thread(lambda: tts_to_48k_stereo(self.piper, reply))
            src = discord.PCMAudio(io.BytesIO(pcm))
            done = asyncio.Event()
            self.voice.play(src, after=lambda e: self.loop_.call_soon_threadsafe(done.set))
            await done.wait()
        except Exception as e:
            log("TTS/PLAY FAILED:", repr(e))
        finally:
            self.speaking = False
        log("TIMING stt %.2fs llm %.2fs tts+play %.2fs" % (stt, llm, time.time() - t0 - stt - llm))

bot = Greg()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "join":
        bot.run(TOKEN, log_handler=None)
    else:
        bot.run(TOKEN, log_handler=None)
