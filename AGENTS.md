# Gregory engineering — research before reinvention

Follow inherited workspace instructions. This file adds a project development rule, not permission to change architecture, credentials, models, deployment or owner policy.

Before implementing a substantial new Core subsystem, consult [the engineering reference library](docs/reference-library/README.md). Read the relevant pinned implementation, not only its README. In the implementation note record:

- The applicable pattern and source pin, or the concrete gap if none fits.
- What Gregory already provides and what must remain authoritative.
- The smallest proposed adaptation, its trade-offs and one observable acceptance test.
- Whether code reuse is proposed; if so, licensing, attribution and dependency impact.

Time-box the lookup: start with one relevant entry, expand only to answer a specific unresolved question, then implement a narrow reviewed slice. Do not turn this into a framework survey or delay a diagnosed urgent fix to fill every library entry. An existing, current investigation can satisfy the rule; do not repeat it ceremonially.

Keep one Gregory Core. Studying a project does not authorize cloning its runtime, introducing another memory authority, migrating frameworks or enabling autonomy. Preserve participant/privacy scopes, evidence provenance and accepted-versus-observed completion semantics.

Maintain the library as projects improve: add or update a source-pinned card when it informs a real design decision. Distinguish source-inspected, test-probed and live-qualified evidence; a source review is not a runtime acceptance pass.
