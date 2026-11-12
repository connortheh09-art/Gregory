"""Existing main-PC Bonzi engine, loopback only; no remote/Piper fallback."""
import audioop
import http.client
import io
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlencode
import wave

VOICE = 'Adult Male #2, American English (TruVoice)'


def start_engine(executable,timeout=8):
    """Explicit launcher hook, not a synthesis fallback. Returns only a process we own.

    Reuse an existing listener without starting or taking ownership of it.
    The caller owns shutdown of a returned process. No shell/batch/console window.
    """
    if sys.platform!='win32':raise RuntimeError('SAPI4 engine launch requires Windows')
    if type(timeout) not in (int,float) or not 0<timeout<=15:raise ValueError('bounded startup timeout required')
    executable=Path(executable).resolve(strict=True)
    if executable.name.lower()!='sapi4.exe' or not executable.is_file():raise ValueError('installed sapi4.exe required')
    def listening():
        try:
            with socket.create_connection(('127.0.0.1',23451),timeout=.2):return True
        except OSError:return False
    if listening():return None
    process=subprocess.Popen([str(executable)],cwd=str(executable.parent),stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    deadline=time.monotonic()+timeout
    try:
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError('SAPI4 engine exited during startup')
            if listening():return process
            time.sleep(.05)
        raise TimeoutError('SAPI4 engine startup deadline')
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=2)
        raise


def wav_to_discord(raw):
    with wave.open(io.BytesIO(raw), 'rb') as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() not in (1, 2):
            raise ValueError('SAPI4 PCM16 mono/stereo required')
        channels, rate = wav.getnchannels(), wav.getframerate()
        data = wav.readframes(wav.getnframes())
    if not data or not 8000 <= rate <= 192000:
        raise ValueError('empty or invalid SAPI4 audio')
    if channels == 2:
        data = audioop.tomono(data, 2, .5, .5)
    if rate != 48000:
        data, _ = audioop.ratecv(data, 2, 1, rate, 48000, None)
    peak = audioop.max(data, 2)
    if 0 < peak < .6 * 32767:
        data = audioop.mul(data, 2, .85 * 32767 / peak)
    return bytes(48000 // 4 * 4) + audioop.tostereo(data, 2, 1, 1)


def synthesize(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError('bounded nonempty speech required')
    query = urlencode(dict(text=text, voice=VOICE, pitch='140', speed='157'))
    connection = http.client.HTTPConnection('127.0.0.1', 23451, timeout=30)
    try:
        connection.request('GET', '/SAPI4?' + query)
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError('local SAPI4 HTTP status ' + str(response.status))
        raw = response.read(8_000_001)
        if len(raw) > 8_000_000:
            raise ValueError('SAPI4 response too large')
    finally:
        connection.close()
    return wav_to_discord(raw)
