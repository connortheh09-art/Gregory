#!/usr/bin/env python3
"""gmod_bridge.py -- the GMod brain/collector (file transport only).

REDESIGN 2026-10-14: no HTTP anywhere. Facepunch blocks client-side http.* to
private addresses (127.0.0.1), and -allowlocalhttp is dedicated-server-only, so
the old state/action HTTP server was dead on arrival. The GMod side now talks to
disk via the SERVER realm (see greg_sv.lua); this process only touches files:

    tail  <data>/greg/state.json   -> latest snapshot
    tail  <data>/greg/chat.json    -> player lines become goals
    write <data>/greg/cmd.json      -> picked up by greg_sv.lua, sent to client

Run it next to GMod on the same box (LM Studio on 127.0.0.1:1234 is fine -- that
is a real Python HTTP client, not a sandboxed game one).
"""

from __future__ import annotations

import argparse
import json
import math
import heapq
import re
from collections import deque
from difflib import SequenceMatcher
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
import os
import time
from pathlib import Path

import requests

PORT_NOTE = "file transport (no listener)"

SYSTEM = (
    "You are the action policy for a Garry's Mod player. You receive an exact "
    "game state snapshot and a goal. Pick exactly ONE action and reply with JSON "
    "only: {\"action\": \"...\", ...}. Valid actions: say {text}, look {yaw, "
    "pitch}, use {hold}, key {bind, hold}, spawn {model}, console {cmd}, move {dir, duration, sprint, jump}, inspect {reason}, wait. "
    "In free-roam choose a small achievable self_goal and move, turn or jump; do not idle. "
    "dir is forward/back/left/right; duration is seconds (0.1 to 3). "
    "Use eye.dist/hitClass, nearby and clearance for obstacles, never vision for walls. "
    "inspect is a collector tool only: request it for visual appearance the API lacks. "
    "In chat mode obey the directive literally, including stop/wait; never substitute exploration. "
    "CHAT OUTPUT: use one JSON object with reply (optional string, max 12 words) and "
    "action (an action OBJECT, not a string). Example: "
    "{\"reply\":\"On my way. Try not to move the entire city.\","
    "\"action\":{\"action\":\"move\",\"dir\":\"forward\",\"duration\":1}}. "
    "You are Greg: dry, sharp, conversational, no filler. Reply to the meaning, "
    "never repeat/quote the player's wording. Use actual actions for requests, "
    "not promises. State has no pathfinder; never invent player coordinates. "
    "Never invent state. Never act while dead, disabled or in menus."
)


def log(msg: str) -> None:
    print(f"[greg] {msg}", flush=True)


def _norm(s) -> str:
    """Loose comparison key: lowercase, alphanumeric+space only."""
    return " ".join(
        "".join(ch if (ch.isalnum() or ch == " ") else " " for ch in str(s).lower()).split()
    )


def echo_of(reply: str, incoming: str) -> bool:
    """Conservative lexical echo guard; semantic paraphrase isn't provable here."""
    a, b = _norm(reply), _norm(incoming)
    if not a or not b:
        return False
    if a == b:
        return True
    aa, bb = a.split(), b.split()
    if min(len(aa), len(bb)) >= 3 and (a in b or b in a):
        return True
    return min(len(aa), len(bb)) >= 4 and SequenceMatcher(None, aa, bb).ratio() >= 0.8


class ChatGate:
    """Identity, not text: only attributed NON-bot SteamIDs can enter intent."""
    def __init__(self) -> None:
        self.seen = deque(maxlen=256)

    def accept(self, rec: dict, target: str, allow: set[str]) -> bool:
        sid, user = rec.get("steamid"), str(rec.get("user") or "").strip()
        # Fail closed while target is unknown or sender identity is absent.
        if not target or not isinstance(sid, str) or not sid.strip() or sid.strip().casefold() == target.strip().casefold():
            return False
        if not user or (allow and user not in allow):
            return False
        key = (sid, str(rec.get("t", "")), str(rec.get("msg", "")))
        if key in self.seen:
            return False
        self.seen.append(key)
        return True


SPAWN_MODELS = {
    "barrel": "models/props_c17/oildrum001.mdl",
    "oildrum": "models/props_c17/oildrum001.mdl",
    "oil drum": "models/props_c17/oildrum001.mdl",
    "crate": "models/props_junk/wood_crate001a.mdl",
    "box": "models/props_junk/wood_crate001a.mdl",
    "wooden crate": "models/props_junk/wood_crate001a.mdl",
    "watermelon": "models/props_junk/watermelon01.mdl",
    "melon": "models/props_junk/watermelon01.mdl",
}

DEATH_LINES = [
    "Ow. That one counted.",
    "Dead. This is temporary, my attitude is not.",
    "I died. Rude.",
    "Down. Give me a second to be dramatic about it.",
]
RESPAWN_LINES = [
    "Back. Miss me?",
    "Up again. Try harder.",
    "Respawned. What did I miss?",
    "I'm back. Nobody panic.",
]


def literal(text: str) -> dict | None:
    """Anchored commands only; ordinary conversation/questions fall through."""
    t = str(text).strip().lower().replace("°", " degrees").replace("−", "-")
    t = re.sub(r"[.!?]+$", "", t).strip()
    t = re.sub(r"^(?:(?:hey|please)\s+|greg[, :]+)+", "", t)
    t = re.sub(r"^(?:can|could|would) you\s+", "", t)
    t = re.sub(r"(?:,?\s+(?:please|if you can))+$", "", t).strip()
    if t in {"stop", "stop moving", "stop now", "wait", "stand still", "stay still", "don't move", "do not move"}:
        return {"kind": "stop"}
    if t in {"come here", "come to me", "come to my position", "follow me", "face me"}:
        return {"kind": "face" if t == "face me" else "approach"}
    m = re.fullmatch(r"(?:look|stare|face)(?:\s+(?:at|towards?))?\s+me\b.*", t)
    if m:
        return {"kind": "face"}
    m = re.fullmatch(r"(?:look|stare|face)\s+(?:at|towards?)\s+([a-z0-9_.\-\[\]]{2,32})", t)
    if m:
        return {"kind": "look_at", "target": m[1]}
    if t in {"jump", "hop"}:
        return {"kind": "once", "action": {"action": "move", "dir": "forward", "duration": 0.3,
                                             "sprint": False, "jump": True}}
    m = re.fullmatch(r"(?:turn|look)(?: the camera)? (left|right|around|behind|up|down)", t)
    if m:
        direction = m[1]
        if direction in {"up", "down"}:
            return {"kind": "angle", "pitch_delta": -30 if direction == "up" else 30}
        return {"kind": "angle", "yaw_delta": {"left": 90, "right": -90, "around": 180, "behind": 180}[direction]}
    m = re.fullmatch(r"(?:turn|look)(?: the camera)?(?: (left|right))? ([+-]?\d+(?:\.\d+)?)"
                     r"(?: degrees?)?(?: (left|right))?", t)
    if m:
        direction = m[1] or m[3]
        value = number(m[2], 0)
        return {"kind": "angle", "yaw_delta": -abs(value) if direction == "right" else abs(value) if direction == "left" else value}
    m = re.fullmatch(r"(?:look|face)(?: at)? yaw ([+-]?\d+(?:\.\d+)?)", t)
    if m:
        return {"kind": "angle", "yaw": number(m[1], 0)}
    m = re.fullmatch(r"(sprint|run|walk|move)(?: (forward|back|backward|left|right))?"
                     r"(?: for (\d+(?:\.\d+)?) (?:seconds?|secs?))?", t)
    if m:
        return {"kind": "once", "action": {"action": "move", "dir": "back" if m[2] == "backward" else m[2] or "forward",
                "duration": min(3, max(0.1, number(m[3], 1.5))), "sprint": m[1] in {"sprint", "run"},
                "walk": m[1] == "walk", "jump": False}}
    m = re.fullmatch(r"(?:kill yourself|kill|die|suicide)", t)
    if m:
        return {"kind": "once", "action": {"action": "console", "cmd": "kill"},
                "reply": "Fine. Watch this."}
    m = re.fullmatch(r"spawn (?:a |an |some |the )?(.+)", t)
    if m:
        what = m[1].strip()
        model = SPAWN_MODELS.get(what)
        if model is None:
            return {"kind": "once", "action": {"action": "spawn", "model": SPAWN_MODELS["barrel"]},
                    "reply": f"No '{what}' in the kit. Barrel it is."}
        return {"kind": "once", "action": {"action": "spawn", "model": model},
                "reply": "Dropped one. Try not to make it a car."}
    return None


def player_position(state: dict, sid: str, name: str) -> dict | None:
    """Distance/name alone cannot determine bearing; NEVER guess coordinates."""
    nearby = [p for p in state.get("nearby", []) if isinstance(p, dict) and p.get("class") == "player"]
    found = [p for p in nearby if p.get("steamid") == sid]
    if not found:
        found = [p for p in nearby if p.get("name") == name]
    if len(found) != 1:
        return None
    entry = found[0]
    pos = entry.get("pos") or entry.get("position") or entry
    if not isinstance(pos, dict) or any(k not in pos for k in ("x", "y", "z")):
        return None
    if not all(math.isfinite(number(pos[k], float("nan"))) for k in ("x", "y", "z")):
        return None
    return pos


class LocalGrid:
    """Bounded 2-D configuration-space belief; scan already uses a body hull."""
    CELL, RANGE, LIMIT = 32, 512, 6000

    def __init__(self) -> None:
        self.cells = {}  # (ix, iy) -> (blocked, last_observed_monotonic)
        self.frame = None
        self.stamp = None
        self.last_move = None
        self.failed_moves = 0
        self.goal = None
        self.progress_pos = None
        self.progress_at = 0.0
        self.status = ""
        self.waypoint = None
        self.best_distance = float("inf")
        self.goal_progress_at = 0.0
        self.refusal_scan = None

    def cell(self, x, y):
        return math.floor(x / self.CELL), math.floor(y / self.CELL)

    def center(self, cell):
        return ((cell[0] + 0.5) * self.CELL, (cell[1] + 0.5) * self.CELL)

    def line(self, a, b):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        count = max(1, math.ceil(length / (self.CELL / 4)))
        return {self.cell(a[0] + (b[0] - a[0]) * i / count,
                          a[1] + (b[1] - a[1]) * i / count) for i in range(count + 1)}

    @staticmethod
    def scan(state):
        scan = state.get("scan")
        if not isinstance(scan, list) or len(scan) != 16:
            return None
        values = [number(v, float("nan")) if not isinstance(v, bool) else float("nan") for v in scan]
        return values if all(math.isfinite(v) and 0 <= v <= 512 for v in values) else None

    def blocked(self, cell):
        return self.cells.get(cell, (False, 0))[0]

    def observe(self, state, now):
        pos, rays = state.get("pos") or {}, self.scan(state)
        if rays is None or any(k not in pos or not math.isfinite(number(pos[k], float("nan"))) for k in ("x", "y", "z")):
            self.status = "I need a valid sonar scan before planning a route."
            return False
        x, y, z = (float(pos[k]) for k in ("x", "y", "z"))
        frame = (state.get("map"), state.get("bridgeSession"), state.get("controlEpoch"), z)
        if self.frame is None or frame[:3] != self.frame[:3] or abs(z - self.frame[3]) > 48:
            self.cells.clear()
            self.last_move = None
            self.failed_moves = 0
            self.progress_pos = None
            self.waypoint = None
            self.refusal_scan = None
            self.frame = frame
            self.stamp = None
            self.goal = None
            self.best_distance = float("inf")
            self.goal_progress_at = now
        stamp = (state.get("seq"), state.get("serverTime"), x, y, tuple(rays))
        self.cells = {c: item for c, item in self.cells.items()
                      if now - item[1] <= (12 if item[0] else 30)
                      and abs(self.center(c)[0] - x) <= 1024 and abs(self.center(c)[1] - y) <= 1024}
        if stamp == self.stamp:
            return True
        self.stamp = stamp
        free, hits = set(), set()
        endpoints = []
        # -- VERIFY: scan[i] is a hull-center travel distance at ABSOLUTE yaw
        # i*22.5 degrees (Lua index i+1), not an eye ray or relative angle.
        def ray(yaw, distance, maximum):
            r = math.radians(yaw)
            end = (x + math.cos(r) * distance, y + math.sin(r) * distance)
            margin = 20 if distance < maximum else 0
            free_end = (x + math.cos(r) * max(0, distance - margin),
                        y + math.sin(r) * max(0, distance - margin))
            free.update(self.line((x, y), free_end))
            if distance < maximum:
                hits.add(self.cell(*end))
            return end
        for i, distance in enumerate(rays):
            endpoints.append(ray(i * 22.5, distance, self.RANGE))
        # Bridge adjacent hit samples only when depths agree: a conservative wall
        # hypothesis, not free-space interpolation across an unseen doorway.
        for i, distance in enumerate(rays):
            j = (i + 1) % 16
            other = rays[j]
            if distance < 512 and other < 512 and abs(distance - other) <= max(48, min(distance, other) * 0.4):
                hits.update(self.line(endpoints[i], endpoints[j]))
        heading = number((state.get("ang") or {}).get("y"), 0)
        probes = state.get("clearance") or {}
        for direction, offset in (("forward", 0), ("left", 90), ("back", 180), ("right", -90)):
            d = number(probes.get(direction), float("nan"))
            if math.isfinite(d) and 0 <= d <= 120:
                ray(heading + offset, d, 120)
        for c in free - hits:
            self.cells[c] = (False, now)
        for c in hits:
            self.cells[c] = (True, now)
        self.cells[self.cell(x, y)] = (False, now)
        if len(self.cells) > 8192:
            self.cells = dict(sorted(self.cells.items(), key=lambda item: item[1][1], reverse=True)[:8192])
        if self.progress_pos is None or math.dist((x, y), self.progress_pos) >= 12:
            self.progress_pos, self.progress_at = (x, y), now
        if self.last_move and now - self.last_move[2] >= 0.7:
            old, yaw, _ = self.last_move
            if math.dist((x, y), old) < 8:
                self.failed_moves += 1
                r = math.radians(yaw)
                for d in (32, 64):
                    self.cells[self.cell(x + math.cos(r) * d, y + math.sin(r) * d)] = (True, now)
            else:
                self.failed_moves = 0
            self.last_move = None
        return True

    def search(self, start_xy, goal_xy):
        start = self.cell(*start_xy)
        gx, gy = goal_xy
        def h(c):
            px, py = self.center(c)
            return max(0, math.hypot(px - gx, py - gy) - 80) / self.CELL
        queue, costs, parent = [(h(start), 0, start)], {start: 0}, {}
        expanded = 0
        while queue and expanded < self.LIMIT:
            _, cost, cur = heapq.heappop(queue)
            if cost != costs.get(cur):
                continue
            expanded += 1
            if h(cur) == 0:
                route = [cur]
                while cur in parent:
                    cur = parent[cur]
                    route.append(cur)
                return route[::-1]
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nxt = (cur[0] + dx, cur[1] + dy)
                if abs(nxt[0] - start[0]) > 24 or abs(nxt[1] - start[1]) > 24 or self.blocked(nxt):
                    continue
                if dx and dy and (self.blocked((cur[0] + dx, cur[1])) or self.blocked((cur[0], cur[1] + dy))):
                    continue  # don't cut KNOWN blocked corners
                step = math.hypot(dx, dy) * (1 if nxt in self.cells else 2.5)
                new = cost + step
                if new < costs.get(nxt, float("inf")):
                    costs[nxt], parent[nxt] = new, cur
                    heapq.heappush(queue, (new + h(nxt), new, nxt))
        return []

    def navigate(self, state, target, now):
        if not self.observe(state, now):
            return {"action": "wait"}, self.status
        pos = state["pos"]
        x, y, z = (float(pos[k]) for k in ("x", "y", "z"))
        gx, gy, gz = (float(target[k]) for k in ("x", "y", "z"))
        if self.goal is None or math.dist((gx, gy, gz), self.goal) > 64:
            self.goal = (gx, gy, gz)
            self.progress_at, self.failed_moves = now, 0
            self.waypoint = None
            self.best_distance, self.goal_progress_at = float("inf"), now
            self.refusal_scan = None
        if abs(gz - z) > 64:
            return {"action": "wait"}, "You're on another level. This planner only knows flat routes."
        goal_distance = math.hypot(gx - x, gy - y)
        if goal_distance <= 96:
            self.progress_at = now
            return {"action": "wait"}, "I'm here. Personal space remains a concept."
        rays = self.scan(state)
        if self.refusal_scan is not None:
            if sum(new > old + 64 for new, old in zip(rays, self.refusal_scan)) < 2:
                return {"action": "wait"}, ""
            self.refusal_scan = None
            self.best_distance, self.goal_progress_at = goal_distance, now
            self.progress_at, self.failed_moves = now, 0
        if goal_distance < self.best_distance - 16:
            self.best_distance, self.goal_progress_at = goal_distance, now
        if now - self.goal_progress_at > 45:
            self.refusal_scan = tuple(rays)
            self.waypoint = None
            return {"action": "wait"}, "I can't find a safe route with the current scan."
        if self.failed_moves >= 3 or now - self.progress_at > 10:
            self.refusal_scan = tuple(rays)
            return {"action": "wait"}, "I can't find a safe route with the current scan."
        route = self.search((x, y), (gx, gy))
        if len(route) < 2:
            self.refusal_scan = tuple(rays)
            return {"action": "wait"}, "No route in my current map. I'm stopping here."
        waypoint = self.waypoint
        if waypoint is None or math.dist((x, y), waypoint) < 24 or any(self.blocked(k) for k in self.line((x, y), waypoint)):
            waypoint = self.center(route[1])
            for c in route[1:5]:
                point = self.center(c)
                if math.dist((x, y), point) <= 96 and not any(self.blocked(k) for k in self.line((x, y), point)):
                    waypoint = point
                else:
                    break
            self.waypoint = waypoint
        dx, dy = waypoint[0] - x, waypoint[1] - y
        distance = math.hypot(dx, dy)
        yaw = math.degrees(math.atan2(dy, dx))
        heading = number((state.get("ang") or {}).get("y"), 0)
        delta = (yaw - heading + 180) % 360 - 180
        if abs(delta) > 8:
            return {"action": "look", "yaw": yaw, "pitch": 0}, ""
        rays = self.scan(state)
        angle = (yaw % 360) / 22.5
        visible = min(rays[int(math.floor(angle)) % 16], rays[int(math.ceil(angle)) % 16])
        # Unknown cells are optimistic planning candidates, NEVER permission to
        # execute blindly. Live scans + forward clearance gate each short move.
        # Long smooth strides when the way is clear, short when it isn't. The
        # visibility gate scales with the stride so an open street is not walked
        # in 0.2s twitches, while a tight corner is still taken cautiously.
        travel = min(distance, 200)
        if clear(state, "forward") < 72 or visible < max(80, min(travel, 96) + 24):
            r = math.radians(yaw)
            self.cells[self.cell(x + math.cos(r) * 48, y + math.sin(r) * 48)] = (True, now)
            self.waypoint = None
            return {"action": "wait"}, ""
        duration = max(0.1, min(1.2, travel / 200))
        if self.last_move is None:
            self.last_move = ((x, y), yaw, now)
        return {"action": "move", "dir": "forward", "duration": duration,
                "sprint": False, "jump": False}, ""


def direct_action(intent, state: dict) -> tuple[dict, str]:
    plan = intent.plan
    if not plan or intent.done:
        return {"action": "wait"}, ""
    kind = plan["kind"]
    if kind in {"stop", "once", "angle"}:
        intent.done = True
        if kind == "stop":
            return {"action": "wait"}, ""
        if kind == "once":
            return dict(plan["action"]), str(plan.get("reply", ""))
        ang = state.get("ang") or {}
        if "y" not in ang or "p" not in ang:
            return {"action": "wait"}, "I don't have a reliable camera angle yet."
        return {"action": "look", "yaw": (plan.get("yaw", number(ang["y"], 0) + plan.get("yaw_delta", 0)) + 180) % 360 - 180,
                "pitch": min(89, max(-89, number(ang["p"], 0) + plan.get("pitch_delta", 0)))}, ""
    if kind == "look_at":
        # Bearing to a NAMED player. Nearby entries are players-first and carry pos;
        # a name that matches nothing, or two of them, fails closed rather than guessing.
        want = str(plan.get("target") or "").strip().lower()
        cands = [p for p in state.get("nearby", [])
                 if isinstance(p, dict) and p.get("class") == "player"
                 and want and want in str(p.get("name") or "").lower()]
        if not cands:
            return {"action": "wait"}, f"I don't see {plan.get('target')} anywhere near me."
        if len(cands) > 1:
            return {"action": "wait"}, "More than one of you answers to that. Give me a full name."
        target_pos = cands[0].get("pos")
        own = state.get("pos") or {}
        if (not isinstance(target_pos, dict)
                or any(k not in target_pos or not math.isfinite(number(target_pos[k], float("nan"))) for k in ("x", "y", "z"))
                or any(k not in own or not math.isfinite(number(own[k], float("nan"))) for k in ("x", "y", "z"))):
            return {"action": "wait"}, f"I can't get a bearing on {plan.get('target')} yet."
        dx, dy, dz = (number(target_pos[k], 0) - number(own[k], 0) for k in ("x", "y", "z"))
        hd = max(1.0, math.hypot(dx, dy))
        intent.done = True
        return {"action": "look", "yaw": math.degrees(math.atan2(dy, dx)),
                "pitch": min(89, max(-89, -math.degrees(math.atan2(dz, hd))))}, ""
    pos = player_position(state, intent.speaker_id, intent.speaker)
    own = state.get("pos") or {}
    if pos is None or any(k not in own or not math.isfinite(number(own[k], float("nan"))) for k in ("x", "y", "z")):
        # Current snapshot schema often has only class/name/dist: not enough.
        return {"action": "wait"}, "I can't locate you from this snapshot."
    if kind == "approach":
        return intent.navigator.navigate(state, pos, time.monotonic())
    dx, dy, dz = (number(pos[k], 0) - number(own[k], 0) for k in ("x", "y", "z"))
    yaw = math.degrees(math.atan2(dy, dx))
    delta = (yaw - number((state.get("ang") or {}).get("y"), 0) + 180) % 360 - 180
    if abs(delta) > 10 or kind == "face":
        if kind == "face": intent.done = True
        return {"action": "look", "yaw": yaw, "pitch": 0}, ""
    if math.hypot(dx, dy) <= 96:
        return {"action": "wait"}, "I'm here. Personal space remains a concept."
    if abs(dz) > 64 or clear(state, "forward") < 72:
        return {"action": "wait"}, "The direct route is blocked. I don't have pathfinding."
    return {"action": "move", "dir": "forward", "duration": 0.5, "sprint": False, "jump": False}, ""


def model_decision(value: dict) -> tuple[dict, str]:
    # Accept legacy single-action replies, but prefer one-call two-slot output.
    action = value.get("action")
    reply = value.get("reply", "")
    if isinstance(action, dict):
        action = normalize(action)
    else:
        action = normalize(value)
    if action.get("action") == "say":
        reply = action.get("text", reply)
        action = {"action": "wait"}
    return action, reply if isinstance(reply, str) else ""


class Tail:
    """Byte-offset tailer that survives truncation/rotation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.pos = 0
        self.partial = b""

    def read_new(self) -> list[str]:
        try:
            with self.path.open("rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                if self.pos > size:      # rotated / truncated -> start over
                    self.pos = 0
                    self.partial = b""
                fh.seek(self.pos)
                data = fh.read()
                self.pos = fh.tell()
        except OSError:
            return []
        out = []
        parts = (self.partial + data).split(b"\n")
        self.partial = parts.pop()
        for ln in (part.decode("utf-8", "replace") for part in parts):
            ln = ln.strip()
            if ln:
                out.append(ln)
        return out


def ask(lm: str, model: str, goal: str, state: dict, mode: str = "chat",
        vision: dict | None = None, refresh_goal: bool = False, history: list | None = None) -> dict:
    user = (
        f"MODE: {mode}\nGOAL: {goal}\n\n"
        + ("Reply as Greg. Return {reply: optional short string, action: action object}; answer and act in ONE response. Never echo the input.\n"
           if mode == "chat" else "")
        + f"ON-DEMAND VISION (appearance only): {json.dumps(vision)}\n"
        + ("Choose a new self_goal (short plain string) alongside the action.\n"
         if refresh_goal else "Keep working on the current goal; omit self_goal.\n")
        + f"GAME STATE (exact):\n{json.dumps(state)}\n\n"
        "Pick one action. JSON only."
    )
    body = {
        "model": model,
        "temperature": 0.4,
        "max_tokens": 200,
        "messages": [{"role": "system", "content": SYSTEM}]
                    + (history or [])[-8:] + [{"role": "user", "content": user}],
    }
    r = requests.post(lm, json=body, timeout=8)
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    i, j = txt.find("{"), txt.rfind("}")
    if i < 0 or j < 0:
        return {"action": "wait"}
    try:
        value = json.loads(txt[i:j + 1])
        return value if isinstance(value, dict) else {"action": "wait"}
    except json.JSONDecodeError:
        return {"action": "wait"}


def resolve_model(root: str) -> str:
    try:
        r = requests.get(root + "/api/v0/models", timeout=2)
        for m in r.json().get("data", []):
            if m.get("state") == "loaded":
                return m["id"]
    except Exception:  # noqa: BLE001
        pass
    return "auto"


def write_cmd(path: Path, seq: int, action: dict, state: dict,
              session: str, mode: str) -> None:
    tmp = path.with_suffix(".json.tmp")
    payload = {"seq": seq, "action": action, "t": time.time(),
               "expires": time.time() + 2, "session": session, "mode": mode,
               "steamid": state["steamid"], "bridgeSession": state["bridgeSession"],
               "controlEpoch": state["controlEpoch"]}
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    # Windows: GMod can hold the target open for an instant, which makes the atomic
    # replace fail with WinError 5. Retry, then fall back to a plain write. This must
    # NEVER raise: a crashed writer takes the whole bot down (it did, mid-follow).
    blob = json.dumps(payload)
    for _ in range(8):
        try:
            os.replace(tmp, path)          # atomic: server never reads a half-written file
            return
        except OSError:
            time.sleep(0.05)
    try:
        path.write_text(blob, encoding="utf-8")
    except OSError as exc:
        log(f"write_cmd failed (continuing): {exc}")


DIRECTIONS = ("forward", "right", "back", "left")
CONSOLE_ALLOW = {"noclip", "kill", "god", "give", "ent_create", "physgun_freeze",
                 "sv_gravity", "r_drawviewmodel"}


def number(value, default: float) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def actionable(state: dict | None, now: float) -> bool:
    return bool(state and state.get("enabled") is True and not state.get("dead")
                and not state.get("menu") and not state.get("inVehicle")
                and 0 <= now - number(state.get("serverTime"), 0) <= 3
                and state.get("steamid") and state.get("bridgeSession")
                and isinstance(state.get("controlEpoch"), (int, float)))


def clear(state: dict, direction: str) -> float:
    distance = number((state.get("clearance") or {}).get(direction), 0)
    eye = state.get("eye") or {}
    if direction == "forward" and number(eye.get("dist"), 9999) < 72:
        distance = 0
    return distance


def fallback(state: dict, step: int) -> dict:
    # API-only; no screenshot or model request. Turning is legitimate progress
    # when all directions are blocked, not a promise to pathfind through walls.
    directions = DIRECTIONS[step % 4:] + DIRECTIONS[:step % 4]
    direction = max(directions, key=lambda d: clear(state, d))
    if clear(state, direction) < 72:
        yaw = number((state.get("ang") or {}).get("y"), 0)
        return {"action": "look", "yaw": (yaw + 65) % 360, "pitch": 0}
    return {"action": "move", "dir": direction, "duration": 1.25,
            "sprint": clear(state, direction) >= 110,
            "jump": step % 4 == 0 and state.get("grounded") is True}


def normalize(action: dict) -> dict:
    if not isinstance(action, dict) or not isinstance(action.get("action"), str):
        return {"action": "wait"}
    act = action.get("action")
    if act == "move":
        direction = action.get("dir", "forward")
        if direction not in DIRECTIONS:
            return {"action": "wait"}
        return {"action": act, "dir": direction,
                "duration": min(3, max(0.1, number(action.get("duration"), 1.25))),
                "sprint": action.get("sprint") is True, "walk": action.get("walk") is True,
                "jump": action.get("jump") is True}
    if act == "console":
        tokens = str(action.get("cmd", "")).split()
        if not tokens or tokens[0].lower() not in CONSOLE_ALLOW:
            return {"action": "wait"}
    if act in {"say", "look", "use", "key", "spawn", "console", "wait", "inspect"}:
        return {k: v for k, v in action.items() if k != "self_goal"}
    return {"action": "wait"}


class Intent:
    """Monotonic arbitration, independent of inference latency."""
    def __init__(self) -> None:
        self.chat = ""
        self.until = 0.0
        self.version = 0
        self.self_goal = ""
        self.self_at = float("-inf")
        self.last_say = ""
        self.last_player_msg = ""
        self.speaker = ""
        self.speaker_id = ""
        self.plan = None
        self.done = False
        self.answered = False
        self.replies = deque(maxlen=16)
        self.history = deque(maxlen=8)
        self.navigator = LocalGrid()

    def direct(self, user: str, text: str, now: float, steamid: str = "") -> None:
        self.chat = f"{user} says: {text}"
        self.until = now + 15
        self.version += 1
        self.last_say = ""
        self.last_player_msg = str(text)
        self.speaker, self.speaker_id = user, steamid
        self.plan, self.done, self.answered = literal(text), False, False
        self.replies.clear()
        self.navigator = LocalGrid()
        self.history.append({"role": "user", "content": f"{user}: {text}"})

    def choose(self, now: float) -> tuple[str, str]:
        if now < self.until:
            return "chat", self.chat
        if self.self_goal and now - self.self_at < 20:
            return "self", self.self_goal
        return "idle", "Choose your own small exploration goal; wander and play."


def inspect(helper: str, state: dict, reason: str) -> dict:
    # VERIFY: wire an existing screenshot+VLM Python helper on the PC.
    # No shell, no new listener, no per-tick capture. The helper returns one JSON object.
    if not helper:
        raise RuntimeError("vision helper not configured")
    result = subprocess.run([sys.executable, helper], input=json.dumps({"state": state,
                            "reason": reason}), text=True, capture_output=True,
                            timeout=12, check=True)
    value = json.loads(result.stdout)
    stamp = number(value.get("t"), 0)
    caption = value.get("caption")
    if not isinstance(caption, str) or not caption.strip() or not 0 <= time.time() - stamp <= 10:
        raise ValueError("vision helper must return a fresh caption and epoch t")
    return {"caption": caption[:2000], "t": stamp}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=r"C:\Program Files (x86)\Steam\steamapps\common\GarrysMod\garrysmod\data")
    ap.add_argument("--lm", default="http://127.0.0.1:1234/v1/chat/completions")
    ap.add_argument("--model", default="auto")
    ap.add_argument("--interval", type=float, default=1.0, help="action cadence, minimum 0.25s")
    ap.add_argument("--turns", type=int, default=0, help="number of commands; 0 = forever")
    ap.add_argument("--allow", default="", help="comma list of nicks allowed to drive via chat")
    ap.add_argument("--steamid", default="", help="controlled player's SteamID; otherwise pin first fresh player")
    ap.add_argument("--vision-helper", default="", help="optional Python screenshot+VLM helper path")
    a = ap.parse_args()

    greg = Path(a.data) / "greg"
    greg.mkdir(parents=True, exist_ok=True)
    state_tail, chat_tail = Tail(greg / "state.json"), Tail(greg / "chat.json")
    chat_tail.read_new()  # do not replay historical directives at startup
    cmd_path = greg / "cmd.json"
    root = a.lm.rsplit("/v1/", 1)[0]
    model = a.model if a.model != "auto" else resolve_model(root)
    allow = {s.strip() for s in a.allow.split(",") if s.strip()}
    target, latest = a.steamid, None
    intent = Intent()
    chat_gate = ChatGate()
    session, seq = uuid.uuid4().hex, 0
    future, pending_context, pending_at, pending_kind = None, None, 0.0, ""
    pending_refresh = False
    ready, vision = None, None
    pending_say = None
    vision_due, request_due, command_due = 0.0, 0.0, 0.0
    interval = max(0.25, number(a.interval, 1))
    previous_context = None
    was_actionable = False
    dead_before = None
    event_say, event_due, event_i = "", 0.0, 0
    # One bounded worker: slow model/vision never blocks state/chat/reflex servicing.
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="greg-policy")
    log(f"watching {greg} (model={model}, target={target or 'first fresh player'})")
    try:
        while True:
            now = time.monotonic()
            for ln in state_tail.read_new():
                try:
                    st = json.loads(ln)
                    if not isinstance(st, dict):
                        continue
                    if not target and actionable(st, time.time()):
                        target = st["steamid"]
                        log(f"pinned target {target}")
                    if st.get("steamid") == target:
                        latest = st
                except (ValueError, TypeError):
                    continue
            me = (latest or {}).get("name", "")
            for ln in chat_tail.read_new():
                try:
                    rec = json.loads(ln)
                    user = str(rec.get("user") or "").strip()
                    if isinstance(rec, dict) and chat_gate.accept(rec, target, allow):
                        intent.direct(user, str(rec.get("msg", "")), now, rec["steamid"])
                        pending_say = None
                        ready = None
                        command_due = 0
                        log(f"CHATDIRECTIVE literal={intent.plan!r} -> {intent.chat!r}")
                except (ValueError, TypeError, AttributeError):
                    continue

            # Death is a real state transition: react to it, don't just go quiet.
            dead_now = bool((latest or {}).get("dead"))
            if latest and dead_now != dead_before:
                if dead_before is not None:
                    if dead_now:
                        event_say = DEATH_LINES[event_i % len(DEATH_LINES)]
                        log(f"DEAD detected -> {event_say!r}")
                    else:
                        event_say = RESPAWN_LINES[event_i % len(RESPAWN_LINES)]
                        log(f"RESPAWN detected -> {event_say!r}")
                    event_i += 1
                    event_due = now + 0.6
                dead_before = dead_now

            # "follow me" should outlive the 15s chat lease for as long as the target
            # stays visible; otherwise every follow order dies 15s in.
            if latest and intent.plan and intent.plan.get("kind") in {"approach", "face"}:
                if player_position(latest, intent.speaker_id, intent.speaker) is not None:
                    intent.until = max(intent.until, now + 5)

            mode, goal = intent.choose(now)
            valid = actionable(latest, time.time())
            context = (target, (latest or {}).get("bridgeSession"),
                       (latest or {}).get("controlEpoch"), intent.version, mode == "chat")
            if context != previous_context or valid != was_actionable:
                ready, vision = None, None
                pending_say = None
                command_due = 0
                # Changing into chat preempts a currently held free-roam action.
                if valid and mode == "chat":
                    seq += 1
                    write_cmd(cmd_path, seq, {"action": "wait"}, latest, session, mode)
                    command_due = now + 0.35  # let Lua observe cancellation before look/move
                previous_context = context
            was_actionable = valid
            if valid:
                intent.navigator.observe(latest, now)

            # Fire the death/respawn line even though actions are suppressed while dead.
            if latest and event_say and now >= event_due:
                seq += 1
                write_cmd(cmd_path, seq, {"action": "say", "text": event_say}, latest, session, "chat")
                log(f"#{seq} event -> say {event_say!r}")
                event_say = ""
                command_due = max(command_due, now + 0.35)

            if future is not None and future.done():
                try:
                    result = future.result()
                    if valid and pending_context == context:
                        if pending_kind == "vision":
                            vision = result
                        elif now - pending_at <= 10:
                            self_goal = result.get("self_goal")
                            if pending_refresh and mode != "chat" and isinstance(self_goal, str) and self_goal.strip():
                                intent.self_goal = self_goal.strip()[:240]
                                intent.self_at = now
                            ready = result  # split reply/action once, below
                except Exception as exc:
                    log(f"{pending_kind} unavailable: {exc}; API fallback remains live")
                future = None
                request_due = now + 1

            if not valid:
                time.sleep(0.1)
                continue
            if vision and time.time() - vision["t"] > 10:
                vision = None
            tool = ready.get("action") if ready else None
            if isinstance(tool, dict) and tool.get("action") == "inspect":
                ready = tool
            if ready and ready.get("action") == "inspect":
                if future is None and now >= vision_due and a.vision_helper:
                    reason = str(ready.get("reason", "describe appearance"))[:240]
                    future = worker.submit(inspect, a.vision_helper, dict(latest), reason)
                    pending_context, pending_at, pending_kind = context, now, "vision"
                    vision_due = now + 10
                ready = None  # never send a collector tool to Lua
            if future is None and now >= request_due and not (mode == "chat" and (intent.plan or intent.answered)):
                pending_refresh = mode != "chat" and now - intent.self_at >= 15
                future = worker.submit(ask, a.lm, model, goal, dict(latest), mode, vision, pending_refresh, list(intent.history)[:-1] if mode == "chat" else [])
                pending_context, pending_at, pending_kind = context, now, "model"
            # Existing Lua accepts ONE verb per envelope. Serialize slots, don't invent
            # a batch verb: execute action first, then optional say >=0.35s later.
            if pending_say and now >= pending_say[0]:
                _, version, text = pending_say
                if mode == "chat" and version == intent.version:
                    seq += 1
                    write_cmd(cmd_path, seq, {"action": "say", "text": text}, latest, session, mode)
                pending_say = None
                command_due = max(command_due, now + 0.35)
            if now >= command_due and pending_say is None:
                reply = ""
                if mode == "chat" and intent.plan:
                    action, reply = direct_action(intent, latest)
                elif ready is not None:
                    if mode == "chat":
                        action, reply = model_decision(ready)
                        if action.get("action") == "wait" and not reply:
                            reply = "I'm here. Give me a concrete move."
                    else:
                        action = normalize(ready.get("action") if isinstance(ready.get("action"), dict) else ready)
                    ready = None
                    if mode == "chat": intent.answered = True
                else:
                    action = None
                if reply:
                    text = " ".join(reply.split()[:12])[:200]
                    norm = _norm(text)
                    if norm and not echo_of(text, intent.last_player_msg) and norm not in intent.replies:
                        intent.replies.append(norm)
                        intent.last_say = text
                        intent.history.append({"role": "assistant", "content": text})
                        pending_say = (now + 0.35, intent.version, text)
                    else:
                        log("say rejected: lexical echo or repeated reply")
                if action and action.get("action") == "move" and clear(latest, action["dir"]) < 72:
                    action = None
                if not action or (mode != "chat" and action.get("action") == "wait"):
                    action = {"action": "wait"} if mode == "chat" else fallback(latest, seq)
                seq += 1
                write_cmd(cmd_path, seq, action, latest, session, mode)
                log(f"#{seq} {mode} goal={goal!r} -> {json.dumps(action)}")
                command_due = now + (action.get("duration", interval) if action["action"] == "move" else interval)
                if a.turns and seq >= a.turns:
                    return 0
            time.sleep(0.1)
    finally:
        if latest and target:
            write_cmd(cmd_path, seq + 1, {"action": "wait"}, latest, session, "stop")
        worker.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    raise SystemExit(main())
