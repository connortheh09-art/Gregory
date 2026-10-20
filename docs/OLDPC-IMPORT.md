# Old-PC import handoff

The 2026-10-20 on-disk KELLENWORKSPACE snapshot is in
[`deployments/oldpc/`](../deployments/oldpc/README.md). It adds the actual
playercore/lifecycle modules and their sibling dependencies, plus the seven
installed Gregory Lua files. It does not replace or certify the separate
rig-era imports.

Original and imported full SHA-256 values, source paths, exact mtimes and
the single trace-path scrub are recorded in its source manifest. Runtime
acceptance and deployment remain separate. Main is untouched by this branch.
