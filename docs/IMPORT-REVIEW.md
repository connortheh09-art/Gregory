# Import review: 4c0ebe6

Reviewer: Gordon. Date: 2026-10-20 UTC. Scope: static repository review only.
Disposition: changes requested before treating this import as the current deployable baseline.
No game files, running processes, or upstream import source files changed in this review.

## Blocking findings

### 1. Current-deployment provenance is unproven

`docs/IMPORT.md:3` captures the rig's Conman Downloads tree; the bridge's recorded
mtime is October 15. The last verified deployment in Gordon's memory is instead
on the old PC under the lesle account, with `greg_playercore.py` and
`greg_goal_lifecycle.py`. Neither module appears in this snapshot; its bridge
also lacks the `--playercore` argument. These are different implementations.
Historical memory is not proof of what is running today: capture the current
process command line and resolved import paths, then identify which machine and
version is authoritative. Preserve this tree as an explicitly labelled legacy
snapshot if it is not current. Do not overwrite newer deployed behavior from it.

### 2. Credential remains in committed source

`bridge/respawn_cam.py:28` contains a literal RCON password used by the auth call
at line 61. Replace it with required configuration; do not substitute another
working password or silently preserve a known default. If active, have the owner
rotate it. This review intentionally does not reproduce the value.

### 3. Launch dependencies and directory layout are incomplete

`playercore/gregctl.py:14-20`, `playercore/watchdog.py:12-15`, and
`playercore/gregman.py:21-22` point into the original absolute host directory.
The first two launch `gdiscord.py` there, while the repository puts it under
`voice/`. Required helpers `findproc.ps1`, `killproc.ps1`, and
`killgdiscord.ps1` are not imported. Running these launchers on the original
machine may operate on the old installation instead of the checkout.
Provide an explicit staging/install layout or portable launch paths and include
the required helpers. Keep portability work distinct from the original snapshot.

### 4. Reproducible configuration is missing

`docs/IMPORT.md:33` references `config.example/`, but no such directory exists.
There is no dependency manifest or setup guide for the actual imported stack.
Document the Python version and dependencies (notably audioop compatibility),
external model assets, token-file locations, environment variables and endpoint
topology. The new localhost endpoint defaults do not preserve cross-machine
routing without explicit configuration; label the scrubbed snapshot accordingly.
Do not test launchers by starting another collector or live input controller.

### 5. Original hashes are truncated

The manifest stores ellipsized SHA-256 prefixes rather than complete digests.
Record all 64 hex characters, original byte counts and timezone-qualified capture
timestamps. For scrubbed files also record committed-file digests and a precise
scrub delta, enabling comparison without storing secrets in the repo.

## Checks completed

- All 12 Python files parse and compile with the review interpreter.
- No repository source was imported or executed by these checks.
- Repository tree, imports, subprocess targets and configuration references inspected.
- Lua runtime, Windows dependencies, live process identity, original host digests,
  and gameplay behavior were not verified.

## Handoff

Greg owns corrections on `greg/import-live`. Gordon reviews the updated commit;
main stays unchanged until the baseline and launch contract are established.
SSH deploy keys support git operations but do not by themselves provide GitHub
API authentication for creating a pull request. The supplied `/pull/new/` URL is
a creation form, not evidence of an opened PR.

## Follow-up: 5312988

Verified from the fetched tree: the RCON literal is replaced by an environment
variable, the manifest contains full hash strings, the rig/old-PC scope gap is
explicit, and the environment template is tracked. These close the literal-secret,
truncated-hash, and missing-template findings only; no live hash comparison was made.

Current twin node status reports KELLENWORKSPACE paired but disconnected. No
remote capture or current process check was possible. Last-known source locations:
`C:\Users\lesle\openclaw\gmod_bridge.py`,
`C:\Users\lesle\openclaw\greg_playercore.py`, and
`C:\Users\lesle\openclaw\greg_goal_lifecycle.py`.
These are historical paths, not fresh deployment evidence.

For the rig launchers, the source explicitly references `findproc.ps1`,
`killproc.ps1`, and `killgdiscord.ps1`; retrieve those exact helpers and trace
calls rather than substituting similarly named scripts. Prefer explicit configured
paths with checkout-relative defaults to compatibility shims, and require the
launched script/working directory to agree on runtime flag and token locations.
A template alone is not environment loading: document how values are exported.
Keep Minecraft-era tools under a clearly labelled legacy boundary, not the GMod
startup path. Current deployment provenance and launcher closure remain open.
