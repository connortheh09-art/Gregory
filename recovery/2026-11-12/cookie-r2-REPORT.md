# Cookie-turn silence repair R2 — isolated, not deployed

## Evidence and diagnosis
- R4 admitted the door request at 23:40:55 UTC and five-cookie offer at 23:41:01 UTC; both closed reaction_refused without a voice reply. Later presence checks selected listen.
- Original refusal logging did not identify the exact publication-gate failure. Historical attribution remains bounded by that missing telemetry.
- Recovered old-PC Recorder flags around both turns were fresh, enabled, alive and outside menus. The short "You" fragment was captured before the cookie refusal; source shows why a later recognized utterance could invalidate an unpublished reply.
- Demonstrated source defect: CoreVoiceAdapter._stt called interrupt for every meaningful new utterance after assembly, even with no playback or client-queued reply. Host interrupt advances the voice-session generation; the old delivery stamp then fails publication admission. Core generation is distinct.
- Separate reproduced defect: cancelled owner turns disappeared from recent context. Unchanged baseline fails the cancelled-door/cookie replay: the next prompt contains neither input.

## Narrow changes
1. Interrupt only when playback/TTS is active or a reply is queued on the client. Explicit stop retains its existing independent path. No cancellation or control permission is weakened.
2. Retain up to four public admitted-but-unanswered voice inputs in ephemeral RAM, with 120-second expiry and voice-connection/world/Core-generation scope. Only earlier inputs reach the next prompt, labelled no reply published/not executed. Never retain cancelled generated replies or replay their actions. Private inbox claims excluded; invalidation clears; a published reply resolves older inputs.
3. Clarify that listen is for unfinished explanations/explicit waits, whereas direct questions/presence checks merit a reply. Model still may select listen; no canned speech or forced action.
4. Log bridge publication refusal and host offer refusal with bounded reason and request ID, without prompt text or credentials.

## Scope and review
- Four runtime files plus test_cookie_silence.py. Built on the already-qualified, undeployed rest-cap tree; the rest cap is unchanged by this delta. Baseline/after hashes in manifest.json.
- Grady read-only review requested by Connor. R2 approval: Discord message 1569883718590660669. He reported independently running cookie13, turn-taking20, voice-handoff27, harness18 and bridge5 checks successfully; those are reviewer-reported counts, not this runner's totals.
- Windows isolated qualification: 213/213, zero failures/errors/skips, 7.765 seconds. All five final source hashes independently rechecked against manifest. No live run/game/model/config changes.
- Final frozen Linux qualification: 740/740 passed, zero failures/errors/skips, 125.032 seconds; all final source hashes unchanged. See linux-result.json.
- Setup history retained outside frozen R2: initial Linux run lacked requests/Pillow and baseline fixtures; these were restored using existing task-local dependencies, no global install. One concurrent focused run hit an existing three-second fixture deadline; final frozen qualification is the decisive result. R1 checks do not qualify later R2 source.

## Limits / live acceptance
- Not deployed. No fresh Gemma inference, voice join, game launch or runtime acceptance by this task.
- Root cancellation behavior is demonstrated in fixtures and fits the retained timeline; the exact historical gate reason cannot be recovered from the original silent branch.
- Listen guidance needs actual model/owner acceptance, not merely a schema/fixture pass.
- The gate sees client state only: a host-queued reply not yet polled (roughly the poll interval) may escape interruption and start playing. This known boundary is not fixed or claimed harmless universally.
- No phrase blacklist: "You"/"Thanks for watching" could be real speech. STT confidence/no-speech metadata is a separate follow-up; current callback returns only text.
- Next supervised acceptance: door then cookie without playback must receive valid replies in order; a presence check must get an acknowledgment; genuine playback barge-in and explicit stop must still suppress old output. Do not claim successful door interaction/teleport or audible speech from mere task acceptance/queueing.
