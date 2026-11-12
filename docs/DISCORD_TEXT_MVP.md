# Gregory Discord Text MVP — supervised first conversation

One Gregory. Existing Core root/profile/persona, existing MemoryStore and the
existing `LMStudioProvider` → `greg_model.post_chat` route. No tools, dispatch,
gameplay, voice, automatic posts, conversation-to-episode promotion or second
character database. New application/bot, not Gordon/Greg's OpenClaw identity.

## A — first supervised demonstration

Required: one initialized Core root and exclusive existing writer lock; reviewed
bounded model-turn execution off the writer; real Gemma endpoint/model; genuine
persisted retrieval; allowlisted guild/channel/participants and explicit prefix
or leading mention; inspectable correlation records; reliable termination and
an owner-approved, foreground, time-limited connection window. No production
service deployment is required to demonstrate this.

Four turns: greeting → known persisted episode → unknown-memory question →
restart same Core root and repeat recall. Inspect `/api/correlation?id=...` and
`/api/status`; check unchanged character ID, new run ID, original memory IDs and
citations, outcome and provider request/response records. Use real persisted
non-fixture experience for the live recall claim. A synthetic fixture is not
Gregory remembering an actual live encounter. Gemma's recall/unknown honesty is
live acceptance, not something a prompt or scripted test can certify.

Runner: `python tools/gregory_discord_text.py --config PRIVATE_CONFIG.json`
validates without starting Core, Discord or inference. After approval,
`--connect --minutes 10` starts a foreground 0–20 minute session, existing Core
and read-only Control Center. It refuses a missing initialized root; another
Core holding the writer lock prevents a second authoritative instance.
`DISCORD_BOT_TOKEN` is an environment secret, never config, CLI argument or repo.
SDK `discord.py` is optional/lazy-imported, not installed on owner PCs by this
work. Live SDK/Gateway path is unverified until the approved window.

Private config (IDs are placeholders; no token):
```
{"core_root":"/existing/initialized/Gregory", "lm_endpoint":"http://127.0.0.1:1234/v1/chat/completions",
 "lm_model":"explicit-loaded-Gemma-id", "guild_id":"1", "channel_id":"2", "bot_id":"3",
 "users":["4"], "bots":["5","6"]}
```
Use a new private channel with View Channel/Send Messages/Read History only.
Enable Message Content intent for prefix messages; mentions have documented
exceptions, but don't depend on those for the prefix path. No Members/Presence
or VC intent/features. Outbound allowed_mentions is always empty; returned
intent is discarded. A configured bot must explicitly trigger, cannot reply to
Gregory's own outbound parent, and shares a per-channel turn cap. Unresolved
bot reply parents are refused by the runner.

## Model and writer lifecycle

Source-grounded blocker: old synchronous `think` wedged lookup/stop; caller
Future timeout did not cancel work. New negatives demonstrated both failures.
The writer journals model request, starts one daemon data-only ModelTask and
continues processing. The original submit Future still resolves to final
speech for compatibility. Writer polling owns every completion, deadline,
inference, decision and command-result write. A timed-out result gets no
model.response/inference/decision. Later completion gets metadata-only
`model.late_discarded`. Admission remains busy until the underlying call
actually finishes. Status exposes model state, inflight age and degradation.

The deadline bounds the **turn**, not arbitrary transport-thread execution.
Python cannot safely kill a thread. A hung daemon has no Core/store reference,
cannot post, cannot pin interpreter exit and blocks further model admissions.
Stop cancels the pending turn, closes stores and exits the writer without
joining that daemon. Do not describe this as forcibly cancelling LM Studio's
server-side computation. Only one model task per running Core. Process-level
isolation/restart hardening is additional work, not a claim made here.

**Operator stop rule for A:** if `/api/status` reports
`core.model_state="timed_out"` and `core.model_busy=true`, stop the foreground
session (Ctrl-C); do not keep sending questions. The underlying call still owns
the one model slot. Inspect `discord_supervised_stop`, including pending
transport/drain flags, before requesting a new supervised run. This is not an
automatic restart/recovery feature. The text client requires an explicit numeric
`deadline_seconds` before admission; its wait budget is that deadline plus 3s,
never an unrelated 3s default. Boolean deadline/queue settings are refused.

## Provenance, privacy and delivery

Conversation is its own operational category, not observation, Recorder or
MemoryStore evidence. Core is sole SQLite writer. Adapter/client hold no SQL
handle. Metadata includes source and receipt times, author/channel/message IDs,
content digest and correlation; query and response text are hash-only for this
path. Raw input/output exist transiently and in Discord, not a new transcript
or episodic database. Existing non-Discord Core logging remains unchanged.
This is code-level capability separation in one process, not OS isolation.

Core atomically reserves `(guild,channel,message)` and content/author fingerprint
with the received event. Duplicate delivery returns the existing correlation
and state, never calls the model or sends again; changed content conflicts.
States: received → intent → sending → accepted/unknown; errors/cancellation
before sending are terminal. Discord's returned outbound ID means API
acceptance, not proof of client delivery. A sending marker encountered after
restart becomes unknown; never blindly resend. MVP also conservatively refuses
to resume a pre-send received/intent turn. A new explicitly triggered message
is required. No exactly-once network-delivery claim, including SDK retries.

Disconnect increments a delivery generation and requests cancellation of active
sends. A turn from a previous generation cannot resume after reconnect. A send
interrupted before its result is processed becomes `unknown`, even if Discord
may already have accepted it. Cancellation is not proof of non-delivery. Close
always cancels sends in a `finally`, including on queue-drain timeout, and checks
cancellation completion under a separate bounded wait. A forced consumer abort
resolves local queued callers as `aborted`; the failed close remains an error,
not a claim that every Core/outbound receipt was committed. An unresolved
`sending` record stays ambiguous and is never automatically resent.

Retrieval preserves original memory/citation identity in MemoryStore and
correlation memory IDs. The prompt includes a bounded first-hit evidence block;
the reply includes a historical-memory ID or an explicit no-match footer. This
footer is provenance, not proof that the generated prose is truthful. Inspect
the full existing memory endpoint for all citations and warnings.
If the backend reports a false/missing historical-only contract, the text path
refuses inference/posting rather than printing a false "Historical memory"
footer. The original fault remains visible in Core's existing lookup/error
records; the adapter does not replace it with a safe-looking constant. Failure,
cancelled and unknown transitions require a typed error category.

## Review correction scope

Independent review reproduced 227 tests on `044953e3` and conditionally accepted
the source; it did not qualify live Discord/Gemma. Nine targeted cases now pin
close timeout cancellation, explicit client deadline, disconnect/send/reconnect,
channel namespace separation, author conflict, invalid memory contract, typed
failure states, boolean settings, and disconnect during the sending-marker
commit before HTTP begins. The pre-fix run is preserved (six affected
cases fail, two identity controls already pass; boolean subtests add failures).
The tests reuse existing Core fixtures without rerunning inherited cases twice.
The extra pre-send race was reproduced separately during correction review:
after the durable marker await, the old code could still start HTTP despite a
disconnect. The generation is now checked again immediately before network I/O.

This correction remains on the Discord branch based on `668455ec`; it does NOT
include or close the separate `0720c800` GMod producer-shutdown candidate. If the
branches are combined later, that combined tree needs its own regression run.
Core+Discord share a host in this MVP, not necessarily Gemma's host: the existing
LM Studio provider accepts an explicit local/private endpoint. Connor chooses
the qualified host/account; no placement change is implied by this review.

## B — continuous unattended operation (not this milestone)

Automatic restart/outbox resumption, long-running rate persistence, extended
watchdog/supervisor/recovery, multi-process capability isolation and soak tests.
None authorizes bypassing A's one-Core/memory/timeout/termination requirements.
GMod sampler/Windows collector/rollback gates remain unchanged, but do not gate
isolated Discord fixtures or a separately approved non-game conversation.

## Evidence scope

Tests use real Core/MemoryStore/journal and fake Discord/provider, plus the
existing LM Studio provider transport test. No bot token, real Discord, Gemma,
authoritative root, owner PC or game was contacted by these tests.
SDK primary reference: https://discordpy.readthedocs.io/en/stable/quickstart.html
API: https://discordpy.readthedocs.io/en/latest/api.html
