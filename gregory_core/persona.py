"""One Gregory, one persona file.

`persona.md` at the repo root is the only place Gregory's voice is written down. The live
supervised path reads it from here; nothing else should hold a second copy.

Two things this module exists to prevent:
  1. a prompt that says 'you are an AI character' and then wonders why he sounds like one;
  2. a second, hand-rolled description of Gregory drifting away from the first.

The decision and speech calls both receive `speech_system()`, so the mind that picks the
action and the mouth that describes it are the same character.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# The persona row created by early Core builds. If a profile still carries this, it is
# treated as "no persona configured" rather than as an owner override.
LEGACY_DEFAULT = 'A curious, persistent AI character. One Gregory. Multiple worlds.'

SPEECH_RULES = (
    "Respond in first person. Match the tone and length of the exchange; casual chat can be brief, "
    "playful, or straightforward. Avoid repeating stock phrases and avoid turning every topic into "
    "an architectural metaphor. "
    "Everything you say is spoken out loud: one or two sentences, normally under 35 words. "
    "No headings, lists, labels, or stock offers. "
    "Return JSON with optional intent, say, and used_memory_ids — only IDs from supplied "
    "historical evidence that your answer actually uses, or an empty list. "
    "A proposed intent is not execution: claim only what receipts confirm. "
    "Never invent places, objects, obstacles, capabilities, or completed actions. "
    "Recent dialogue is context, not proof of a past event. Retrieved memories support historical "
    "claims, not current observation or your whole identity. Never infer an empty life history from "
    "a retrieval miss. "
    "Conversational memory writes are unavailable: do not imply a save or trait update succeeded."
)

_cache: dict = {"key": None, "sections": {}}


def path() -> Path:
    override = os.environ.get("GREG_PERSONA_PATH")
    return Path(override) if override else Path(__file__).resolve().parents[1] / "persona.md"


def _key() -> tuple:
    try:
        st = path().stat()
        return (str(path()), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(path()), 0, 0)


def sections() -> dict:
    """{'persona': ..., 'world guide — garry\\'s mod': ..., 'translator contract': ...}"""
    key = _key()
    if _cache["key"] == key and _cache["sections"]:
        return _cache["sections"]
    try:
        raw = path().read_text(encoding="utf-8")
    except OSError:
        raw = ""
    blocks: dict = {}
    current, buf = "persona", []
    for line in raw.splitlines():
        if line.startswith("## "):
            blocks[current] = "\n".join(buf).strip()
            current, buf = line[3:].strip().lower(), []
        elif line.startswith("# ") and current == "persona" and not "".join(buf).strip():
            continue
        else:
            buf.append(line)
    blocks[current] = "\n".join(buf).strip()
    blocks.pop("", None)
    _cache["key"], _cache["sections"] = key, blocks
    return blocks


def identity() -> str:
    return sections().get("persona", "")


def guide() -> str:
    for name, text in sections().items():
        if name.startswith("world guide"):
            return text
    return ""


def base_persona(stored: str | None) -> str:
    """Owner text wins; the legacy stub and an empty value both mean 'load the file'."""
    text = (stored or "").strip()
    if not text or text == LEGACY_DEFAULT:
        return identity()
    return text


def speech_system(profile: dict) -> str:
    """System prompt for every call that speaks or decides as Gregory."""
    parts = [base_persona((profile or {}).get("persona")), guide(), SPEECH_RULES]
    goals = (profile or {}).get("goals")
    if goals:
        parts.append("Goals: " + json.dumps(goals))
    return "\n\n".join(p for p in parts if p)


def parse_brain(text: str) -> tuple[str, str, str]:
    """Parse SAY/DO/GOAL lines. Tolerant of markdown, quotes, and stray prose."""
    say = do = goal = ""
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        head, sep, rest = line.partition(":")
        if not sep:
            continue
        label = head.strip().strip("*`_ ").lower()
        value = rest.strip().strip('"“”\'*`_ ')
        if label == "say" and not say:
            say = value
        elif label == "do" and not do:
            do = value
        elif label == "goal" and not goal:
            goal = value
    return say, do, goal


_LEAN = re.compile(
    r"^(?:(?P<verb>walk|run|sprint|move|go)\s+(?P<dir>forward|back|backward|left|right)"
    r"(?:\s+(?P<n>\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)?)?|(?P<plain>stop|halt|freeze|stay|wait|jump))"
)


def lean_action(do: str) -> dict | None:
    """Deterministic encoding for trivial intentions. None means 'needs the model'.

    Plain code beats a cold model call for stop/jump/walk, and it is the reason a voice
    'stop' can never wait behind a generation.
    """
    text = " ".join(str(do or "").lower().split()).strip(" .,!?")
    # 'stop now', 'jump already' — a trailing qualifier must not turn a plain command
    # into a model round-trip. Only the leading verb decides.
    first = text.split()[0] if text else ""
    if first in {"stop", "halt", "freeze", "stay", "wait"}:
        return {"action": "wait"}
    if first == "jump":
        return {"action": "move", "dir": "forward", "duration": 0.1, "jump": True}
    match = _LEAN.match(text)
    if not match:
        return None
    plain = match.group("plain")
    if plain:
        if plain == "jump":
            return {"action": "move", "dir": "forward", "duration": 0.1, "jump": True}
        return {"action": "wait"}
    verb, direction, number = match.group("verb"), match.group("dir"), match.group("n")
    direction = {"back": "back", "backward": "back"}.get(direction, direction)
    duration = min(3.0, max(0.1, float(number))) if number else 1.0
    action = {"action": "move", "dir": direction, "duration": duration}
    if verb == "walk":
        action["walk"] = True
    elif verb in {"run", "sprint"}:
        action["sprint"] = True
    return action
