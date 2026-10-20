# Gregory memory and decision fixes — 2026-10-20

Scope: `deployments/oldpc`, based on `main` at `d1f89bb`. This changes neither
model selection nor the agreed old-PC vision / remote Gemma action-brain split.
No live processes, installed game files, Lua controllers or launch settings were changed.

## Source findings and changes

- **Recorded outcomes missing from action prompts.** `EventMemory.summary` excluded
  `goal_lifecycle`, so it hid completed/failed goals and their reasons. It now
  includes compact lifecycle/rescue records and an explicit current-goal projection
  alongside the active task. Historical event text remains quoted data, not instructions.
- **Goal avoidance forgotten on restart, mixed across maps on transitions.**
  `Goals.recent` was in-memory only. The world digest now keeps up to 12 distinct
  normalized completed/failed **self-goal** names per map. On accepted map/session
  transitions Runtime restores only that map's avoidance history. It also recovers
  unflushed outcomes from the bounded event tail. Saved tasks/routes are never resumed;
  explicit human requests can still retry a destination. Abandoned goals are not
  added to durable avoidance. This is bounded recent avoidance, not a permanent blacklist.
- **Map filtering applied too late for agenda recall.** The collector sliced the
  global tail before the agenda filtered by map. It now selects map-local events
  first, so another map's recent events do not consume this map's recall budget.
- **Exact landmark names rejected as ambiguous.** `Station` collided with
  `Station roof` because routing only used substring matching. Exact case-insensitive
  names now win. Unique partial names still work; ambiguous or empty names are refused.
- **Malformed persisted chat could break history.** Loaded turns were not validated
  before `.get` calls and loaded histories were not bounded. Reload now validates
  roles/content, preserves valid turns, bounds text/turn/thread counts, and normalizes
  invalid eviction timestamps. Existing SteamID/map isolation and old-session labels remain.

The source manifest continues to describe the **original imported snapshot**;
Git records these subsequent changes. It is not a checksum manifest for this patch.

## Offline verification

From the repository root, using Python 3.10+:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q deployments/oldpc
git -c core.whitespace=cr-at-eol diff --check
```

The tests use temporary memory directories and do not contact a model, install
dependencies, start GMod, or write live command mailboxes. `cr-at-eol` accounts
for the original imported playercore's CRLF line endings, which are preserved.

## Remaining runtime acceptance

These fixes improve available context and deterministic behavior; they do not
prove that a model is more intelligent or that Gregory plays better.

1. Discover actual node processes, loaded model IDs and launch options. Establish
   the real observation path rather than inferring blindness from a missing flag.
2. With the agreed vision/action split, trace observation freshness, prompt/model,
   parsed decision, Lua execution and visible result on one simple goal.
3. Confirm a failed or completed self-goal is recalled after a controlled restart,
   without restoring its route or command. Explicit human retry should still work.
4. Check current-goal commitment, map transitions, latency and GMod/model coexistence.
   No live deployment or gameplay acceptance is claimed by the offline checks.
