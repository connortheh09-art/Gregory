#!/usr/bin/env python3
"""M1 constant-vision sensor: capture -> change gate -> VLM caption -> log.

Runs on Connor's PC. Local except the call to the local LM Studio server.

  python vision_loop.py --once
  python vision_loop.py --interval 1.5 --threshold 4 --model qwen/qwen3-vl-8b

Gate: 64-bit dHash of a downscaled frame; only frames whose Hamming distance
from the last accepted frame exceeds --threshold are described.

M2: an optional context digest (Greg's memories) is fetched from the VPS and
injected as a system prefix, hash-gated so it is only re-read when it changes.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageGrab

PROMPT = (
    "In one or two short sentences, describe what is on this screen and what the "
    "user appears to be doing. No preamble, no markdown."
)

CONTEXT_HEADER = (
    "You are Greg, watching Connor's screen. Context about who he is, what we've "
    "been working on and what's going on today follows. Use it to make your "
    "description specific rather than generic; never recite it back verbatim. "
    "If it is irrelevant to the screen, ignore it.\n\n"
)


def dhash(img: Image.Image, size: int = 8) -> np.ndarray:
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    return (a[:, 1:] > a[:, :-1]).astype(np.uint8).ravel()


def hamming(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.count_nonzero(a != b))


def fetch_context(url: str, path: Path, limit: int) -> str:
    """Fetch the digest from the VPS, falling back to a local copy."""
    text = ""
    if url:
        try:
            r = requests.get(url, timeout=8)
            if r.ok:
                text = r.text
        except Exception:
            text = ""
    if not text and path and url_path_exists(path):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    return text.strip()[:limit]


def url_path_exists(p: Path) -> bool:
    try:
        return p.exists()
    except OSError:
        return False


def resolve_loaded_model(endpoint: str) -> str:
    """Ask LM Studio which model is ACTUALLY LOADED RIGHT NOW and use that.

    Uses the native /api/v0/models endpoint, which reports per-model `state`
    (loaded / not-loaded) and `type` (llm / vlm). The OpenAI-style /v1/models
    lists the whole downloaded CATALOG - picking from that makes LM Studio
    lazily JIT-load a second model, which is how lexi got loaded twice.
    Prefers an already-loaded vision model; never triggers a load.
    """
    root = endpoint.rsplit("/chat/completions", 1)[0].rsplit("/v1", 1)[0]
    loaded, allvlm, catalog = [], [], []
    try:
        r = requests.get(root + "/api/v0/models", timeout=10)
        r.raise_for_status()
        for m in r.json().get("data", []):
            mid = m.get("id")
            if not mid:
                continue
            catalog.append(mid)
            if m.get("state") == "loaded":
                loaded.append(mid)
                if m.get("type") == "vlm":
                    allvlm.append(mid)
    except Exception as exc:  # noqa: BLE001
        print(f"[model] /api/v0/models unavailable ({exc}); falling back to /v1/models", flush=True)
    pick = allvlm or loaded
    if pick:
        print(f"[model] loaded={loaded} vlm={allvlm} -> using {pick[0]}", flush=True)
        return pick[0]
    # Nothing loaded: only now consider the catalog, and say so loudly.
    try:
        r = requests.get(root + "/v1/models", timeout=10)
        r.raise_for_status()
        ids = [m.get("id") for m in r.json().get("data", []) if m.get("id")]
    except Exception:  # noqa: BLE001
        ids = []
    if ids:
        print(f"[model] WARNING: nothing loaded; catalog={ids[:3]}...", flush=True)
        return ids[0]
    raise RuntimeError("LM Studio reports no models at all")


def describe(img: Image.Image, endpoint: str, model: str, token: str, timeout: int,
             system: str = "", question: str = PROMPT) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=60)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ],
    })
    body = {"model": model, "temperature": 0.2, "max_tokens": 120, "messages": messages}
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    r = requests.post(endpoint, headers=headers, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=1.5, help="seconds between grabs")
    ap.add_argument("--threshold", type=int, default=5, help="dHash Hamming distance to count as a change")
    ap.add_argument("--model", default="auto",
                    help="'auto' = use whatever LM Studio has loaded (default)")
    ap.add_argument("--endpoint", default="http://127.0.0.1:1234/v1/chat/completions")
    ap.add_argument("--outdir", type=Path, default=Path(r"C:\Users\Conman\Downloads\openclaw\vision"))
    ap.add_argument("--token", default=os.environ.get("LM_API_TOKEN", ""))
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--duration", type=float, default=0.0, help="stop after N seconds (0 = forever)")
    ap.add_argument("--save-frames", action="store_true", help="also write each described frame to disk")
    ap.add_argument("--context-url", default=os.environ.get("CONTEXT_URL", "http://127.0.0.1:18082/greg_context.md"),
                    help="VPS digest URL ('' disables context injection)")
    ap.add_argument("--context-file", type=Path, default=Path(r"C:\Users\Conman\Downloads\openclaw\greg_context.md"))
    ap.add_argument("--context-max-chars", type=int, default=4000)
    ap.add_argument("--context-refresh", type=float, default=300.0, help="seconds between digest refreshes")
    ap.add_argument("--prompt", default="", help="override the caption question")
    ap.add_argument("--prompt-file", type=Path, default=None,
                    help="read the caption question from a file (re-read on change)")
    a = ap.parse_args()

    a.outdir.mkdir(parents=True, exist_ok=True)
    state = a.outdir / "vision_state.log"
    frames = a.outdir / "frames"
    frames.mkdir(exist_ok=True)

    model_auto = a.model.strip().lower() in ("", "auto", "loaded", "current")
    if model_auto:
        try:
            a.model = resolve_loaded_model(a.endpoint)
        except Exception as exc:  # noqa: BLE001
            print(f"[model] could not resolve loaded model ({exc}); defaulting to qwen/qwen3-vl-8b", flush=True)
            a.model = "qwen/qwen3-vl-8b"

    ctx_text, ctx_hash, ctx_at = "", "", 0.0
    system = ""

    prompt_text = a.prompt or PROMPT
    prompt_mtime = 0.0

    def refresh_prompt() -> None:
        """Re-read the question from --prompt-file when it changes on disk."""
        nonlocal prompt_text, prompt_mtime
        if not a.prompt_file:
            return
        try:
            mt = a.prompt_file.stat().st_mtime
        except OSError:
            return
        if mt != prompt_mtime:
            prompt_mtime = mt
            txt = a.prompt_file.read_text(encoding="utf-8", errors="replace").strip()
            if txt:
                prompt_text = txt
                print(f"[prompt] loaded {len(txt)} chars from {a.prompt_file}", flush=True)

    def refresh_context(force: bool = False) -> None:
        nonlocal ctx_text, ctx_hash, ctx_at, system
        if not (a.context_url or a.context_file):
            return
        now = time.time()
        if not force and (now - ctx_at) < a.context_refresh:
            return
        ctx_at = now
        text = fetch_context(a.context_url, a.context_file, a.context_max_chars)
        h = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        if h != ctx_hash:
            ctx_hash = h
            ctx_text = text
            system = (CONTEXT_HEADER + ctx_text) if ctx_text else ""
            print(f"[ctx] digest loaded: {len(ctx_text)} chars", flush=True)

    refresh_context(force=True)
    refresh_prompt()
    print(f"vision sensor: interval={a.interval}s threshold={a.threshold} model={a.model} "
          f"ctx={'on' if system else 'off'}", flush=True)

    last = None
    n = 0
    t0 = time.time()
    while True:
        if a.duration and time.time() - t0 >= a.duration:
            break
        refresh_context()
        refresh_prompt()
        shot = ImageGrab.grab()
        h = dhash(shot)
        dist = 999 if last is None else hamming(h, last)
        if dist > a.threshold:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            try:
                cap = describe(shot, a.endpoint, a.model, a.token, a.timeout, system, prompt_text)
            except Exception as exc:  # noqa: BLE001
                cap = f"[ERROR] {exc}"
                if model_auto:
                    # The resident model may have been swapped out under us.
                    # Re-resolve and retry once so we always use what IS loaded.
                    try:
                        a.model = resolve_loaded_model(a.endpoint)
                        cap = describe(shot, a.endpoint, a.model, a.token, a.timeout, system, prompt_text)
                    except Exception as exc2:  # noqa: BLE001
                        cap = f"[ERROR] {exc2}"
            line = f"{datetime.now().strftime('%H:%M:%S')}  [d={dist}]  {cap}"
            # Normalise smart punctuation to ASCII so the log reads cleanly in any
            # viewer, without destroying the rest of the text.
            line = line.translate(str.maketrans({
                "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                "\u2013": "-", "\u2014": "-", "\u2026": "...", "\u00a0": " ",
            }))
            with state.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            if a.save_frames:
                shot.convert("RGB").save(frames / f"frame_{stamp}.jpg", quality=60)
            print(line, flush=True)
            last = h
            n += 1
        if a.once:
            break
        time.sleep(a.interval)
    print(f"done: {n} frame(s) described -> {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
