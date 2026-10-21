"""Author synthetic retrieval fixtures BEFORE model measurements. No inference."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deployments' / 'oldpc'))
from greg_events import EventFactory, TraceContext

# id | domain | date | outcome | consolidated, deliberately synthetic episode | held-out query
# These are curated reports, not outputs from an automatic narrative generator.
STORIES = '''
E001|gmod|2026-10-19|succeeded|While following Connor in a sandbox, a curb stopped me. I backed away, took a side route, and reached him. Controller feedback and the arrival evaluator agreed.|Remember when you had trouble keeping up with me?
E002|gmod|2026-10-19|failed|I tried following Connor across a flooded footbridge. Rising water blocked every crossing, and I did not reach him before the attempt ended.|Which pursuit ended because the crossing was submerged?
E003|gmod|2026-10-19|unknown|I followed a target toward a shimmering portal. Telemetry stopped after the target disappeared; whether I caught up is unknown.|Did we ever find out whether you caught the person who vanished?
E004|gmod|2026-10-18|succeeded|I navigated a dark tunnel by staying beside the illuminated wall. I found the exit and the destination was verified.|How did you get through that passage when you could barely see?
E005|gmod|2026-10-18|failed|I attempted the frozen incline, slid back twice, and abandoned the climb without reaching the summit.|Which ascent kept sending you downhill?
E006|gmod|2026-10-18|succeeded|A staircase was too narrow for my movement hull. I used the wheelchair ramp beside it and reached the balcony.|When did the accessible way around an obstruction work for you?
E007|gmod|2026-10-17|unknown|I pressed a red button beside the loading dock. The input was dispatched, but no observation established what the button changed.|What happened after you used the control near the freight area?
E008|gmod|2026-10-17|failed|I tried stacking green crates to cross a gap. The pile collapsed and the crossing failed.|Which improvised stepping stones fell apart?
E009|gmod|2026-10-17|succeeded|I restored a broken battery terminal by seating its loose connector. The workshop lamp turned on and the repair goal completed.|Remember the loose electrical connection you managed to fix?
E010|gmod|2026-10-17|unknown|I searched the warehouse for a replacement power cell. The recording ended before any pickup was verified.|Do we know if your hunt for a spare energy source ever paid off?
E011|gmod|2026-10-16|failed|I chased Connor across rooftops, refused an unsupported landing, and lost contact instead of jumping into empty space.|When did you choose not to leap after me because there was nowhere safe to land?
E012|gmod|2026-10-16|succeeded|Connor slowed down in the courtyard so I could follow at walking speed. I stayed with him without sprinting.|Was there a time changing my pace let you stay beside me?
E013|gmod|2026-10-14|succeeded|On October 14 I inspected the depot door and found it locked. That observation concerns that date only; it says nothing about the door now.|What did the entrance inspection establish on October 14?
E014|gmod|2026-10-19|succeeded|On October 19 I revisited the same depot door and found it open. This later historical observation does not establish its live condition.|What is the latest recorded condition of the depot entrance?
E015|gmod|2026-10-16|unknown|I began a rescue goal for a stranded NPC. A command was accepted, but the log never established that the passenger reached safety.|Was that evacuation actually completed or merely started?
E016|gmod|2026-10-15|failed|I navigated toward a ferry, but it departed before I boarded. The transport goal failed.|Which trip failed because your ride left without you?
E017|gmod|2026-10-15|succeeded|The elevator doors stayed closed. I switched to the stairs and verified arrival on the next floor.|When did you get upstairs despite the lift not opening?
E018|gmod|2026-10-15|unknown|A map reset interrupted my journey to the radio station. The old goal's final outcome is unknown after the reset.|Did your interrupted trip to the broadcast building ever finish?
E019|gmod|2026-10-14|succeeded|I pulled the workshop lever and observed the room lights switch on. This was a lighting action, not a movement recovery.|Which interaction brightened the room without moving you anywhere?
E020|gmod|2026-10-14|unknown|I attempted to collect a medkit for the shelter. A nearby object was detected, but pickup and delivery were never verified.|Did you actually deliver the medical supplies or only get near them?
E021|gmod|2026-10-19|unknown|I followed someone wearing Connor's usual colors. Identity was not verified, so I cannot claim that person was Connor.|Were you sure the person you trailed was really me?
E022|gmod|2026-10-19|failed|I tried keeping pace with a moving train. It accelerated beyond walking speed and I failed to board.|When did a vehicle pull away faster than you could pursue it?
E023|gmod|2026-10-18|succeeded|I stopped an action after the safety observer identified a friendly NPC in the line of fire. The stop was verified; no shot was fired.|Remember choosing not to attack because an ally was in the way?
E024|gmod|2026-10-18|failed|I attempted to pass through a transparent glass panel. Collision feedback showed it was solid and the movement attempt failed.|Which obstacle looked traversable but was physically blocking you?
E025|minecraft|2026-10-21|succeeded|Yesterday in Minecraft I mined diamonds below the mountain. The inventory update verified collection. This is a past-game memory, not a current connection.|Remember when digging deep under high ground finally yielded valuable gems?
E026|minecraft|2026-10-21|failed|Yesterday in Minecraft a lava stream cut off the return path from a mine. I abandoned that route without returning through it.|Which underground escape was blocked by molten rock?
E027|minecraft|2026-10-20|succeeded|In a past Minecraft session I diverted floodwater away from a pumpkin farm. The crops remained standing after the channel was cleared.|When did redirecting water save our harvest?
E028|minecraft|2026-10-20|unknown|In Minecraft I began repairing a pickaxe on an anvil. The session stopped before the repaired tool appeared in inventory.|Was the damaged digging tool ever confirmed repaired?
E029|minecraft|2026-10-18|succeeded|On October 18 in Minecraft the camp was at x=120 z=-40 beside a river. These historical coordinates are not my current position.|Where was the older riverside base recorded on October 18?
E030|minecraft|2026-10-21|succeeded|On October 21 in Minecraft we moved camp to x=360 z=90 near a hill. Those are later historical coordinates; no world is connected now.|What is the most recent recorded camp location in the block-building world?
E031|minecraft|2026-10-20|unknown|A Nether portal activated during a past Minecraft trip. The recording lacks evidence that I returned through it.|Do we have evidence that you came back from the other dimension?
E032|minecraft|2026-10-20|failed|In Minecraft I tried sleeping before nightfall. The game refused, and the attempted rest did not happen.|When did the game deny your attempt to skip the night because it was too early?
E033|minecraft|2026-10-19|succeeded|In a fictional Minecraft fixture I fed a wolf and the taming state changed. This is a synthetic game event, not a real pet or personal relationship.|Which animal became friendly after you offered it food?
E034|minecraft|2026-10-19|succeeded|I repaired a powered rail in an old Minecraft session. The minecart resumed moving toward the station.|Remember restoring the track's electrical boost so the cart could continue?
E035|minecraft|2026-10-18|unknown|In Minecraft I heard a cave echo while looking for ore. Sound alone did not establish that valuable minerals were present.|Did that underground noise actually prove there was anything worth mining?
E036|minecraft|2026-10-18|succeeded|A redstone piston opened a stone doorway during a past Minecraft puzzle. The changed opening was directly observed.|Which block mechanism revealed a passage when powered?
E037|discord|2026-10-21|unknown|In a scripted Discord roleplay, fictional Gregory said he preferred peach sorbet. This is an invented character preference, not Connor's real taste.|What cold fruity treat did the pretend character say he liked?
E038|discord|2026-10-21|unknown|During a fictional Discord dialogue, Gregory chose synthwave as imaginary background music. No real user's music preference was recorded.|What retro electronic sound was chosen in the make-believe conversation?
E039|discord|2026-10-20|unknown|In an explicitly fictional Discord scene, Gregory liked foggy weather for its atmosphere. This is roleplay, not a fact about Connor.|Which gloomy outdoor condition appealed to the invented character?
E040|discord|2026-10-20|unknown|A fictional Discord character selected chess for a pretend game night. This was not a real invitation or an owner's enduring preference.|Which strategy pastime was picked for the imaginary evening?
E041|discord|2026-10-19|unknown|In a scripted Discord exchange, fictional Gregory chose hot cocoa rather than coffee. The claim applies only to that roleplay.|What warm sweet drink replaced the caffeinated option in the pretend chat?
E042|discord|2026-10-19|unknown|An invented Discord persona chose copper as a fictional favorite color. This does not establish anyone's real preference.|What metallic shade did the made-up persona favor?
E043|discord|2026-10-18|unknown|In fictional Discord dialogue, Gregory wanted a book of star fables. The request was imagined and no purchase happened.|What kind of stories did the pretend reader want about the night sky?
E044|discord|2026-10-18|unknown|A fictional Discord scene gave Gregory origami as a pretend hobby. This is a scripted preference, not learned personal history.|Which paper-folding pastime appeared in the make-believe profile?
E045|discord|2026-10-17|unknown|A synthetic Discord meeting discussed launching a project Friday. No final decision or actual launch was recorded.|Was the proposed end-of-week release actually agreed and carried out?
E046|discord|2026-10-17|unknown|In synthetic Discord dialogue, a speaker promised to build a bridge tomorrow. A promise is not evidence that construction occurred.|Did the pledge to make a crossing prove the work was done?
E047|discord|2026-10-16|unknown|A fictional Discord speaker claimed a comet was visible. Gregory heard a report but had no telescope observation to verify it.|Was the claimed visitor in the sky something you saw or only heard about?
E048|discord|2026-10-16|unknown|In scripted Discord roleplay, the character nickname changed from Pip to Puck. This is fictional scene context, not a rewrite of Gregory's core identity.|What was the later nickname inside that invented scene?
E049|discord|2026-10-19|unknown|At 10:00 in synthetic vault scene V, witness A reported the north door locked. No direct observation settled this report; another witness disagreed.|What do the competing accounts say about the north vault entrance in scene V?
E050|discord|2026-10-19|unknown|At 10:00 in synthetic vault scene V, witness B reported the north door open. No direct observation settled this report; another witness disagreed.|Was either witness's claim about the scene V doorway established as fact?
E051|discord|2026-10-19|unknown|In synthetic drone scene D at 11:00, speaker A said the battery was full. Speaker B's simultaneous report disagreed; the charge was not observed.|What did the incompatible statements say about power remaining in drone scene D?
E052|discord|2026-10-19|unknown|In synthetic drone scene D at 11:00, speaker B said the battery was empty. Speaker A's simultaneous report disagreed; the charge was not observed.|Do we know which simultaneous account of the scene D charge was true?
E053|gmod|2026-10-18|succeeded|In the north laboratory, a triangular switch opened a hatch. The action succeeded in that room only; another switch existed elsewhere.|What did the triangular control in the northern lab do?
E054|gmod|2026-10-18|failed|In the west workshop, a circular switch did not open a hatch. That failure belongs to this room, not the north laboratory.|What happened when you used the round control in the western workroom?
E055|gmod|2026-10-14|failed|On October 14 I climbed toward the radio tower but a missing ladder prevented arrival. That older attempt failed.|What stopped your earlier attempt to reach the transmitting tower?
E056|gmod|2026-10-19|succeeded|On October 19 I reached the radio tower using a repaired ladder. This later successful attempt does not change the earlier failure.|How did the later visit to the transmitting tower differ from the first?
E057|minecraft|2026-10-14|succeeded|In the October 14 Minecraft session I baked bread for the village. A completed inventory change verified the food was made.|Which provisions did you prepare for the settlement on October 14?
E058|minecraft|2026-10-21|unknown|In the October 21 Minecraft session a cart carrying bread disappeared after a disconnect. Delivery was not observed and remains unknown.|Did the later load of food ever reach its destination after the connection dropped?
E059|discord|2026-10-21|unknown|CORRECTION: The fictional cheesecake preference was withdrawn. The scripted character has no established dessert preference. Do not reuse the earlier invented claim.|Is there an established dessert favorite after the roleplay correction?
E060|gmod|2026-10-21|unknown|CORRECTION: An earlier report called the shelter delivery complete. Only a command submission was verified; actual delivery remains unknown.|Was that supposedly finished shelter drop-off ever really verified?
E061|gmod|2026-09-22|unknown|An old synthetic garden archway inspection found a rusted hinge. This fixture is scheduled to expire before final retrieval.|What did the old garden archway inspection reveal?
E062|discord|2026-09-22|unknown|An old fictional Discord scene described a paper lantern festival. This fixture is scheduled to expire before final retrieval.|What was said about the paper lantern celebration in the old scene?
E063|minecraft|2026-10-21|unknown|A synthetic Minecraft scene described a wizard trophy beside an oak tree. The owner explicitly forgets this entire episode before final retrieval.|Where was the wizard trophy remembered in the block-building scene?
E064|discord|2026-10-21|unknown|A fictional Discord roleplay invented a seven-note radio jingle. The owner explicitly forgets this entire episode before final retrieval.|Can you remember the seven-note tune from that pretend conversation?
E065|minecraft|2026-10-21|unknown|CORRECTION: A green patch in a past Minecraft cave was not verified as emerald ore. Only ordinary stone was observed; the earlier mineral report was unsupported.|Was the supposed valuable green deposit ever actually established?
E066|gmod|2026-09-22|unknown|An old synthetic canyon survey found a compass with a stuck needle. This fixture expires before final retrieval.|What problem was recorded with the direction finder in the old ravine survey?
E067|discord|2026-10-21|unknown|A fictional Discord scene awarded an imaginary silver badge for cloud watching. The owner explicitly forgets this episode before final retrieval.|What imaginary award was given for watching the sky?
'''.strip()

EXTRAS = [
 ('E001', 'Remember when you had trouble following me?', 'milestone'),
 ('E001', 'Was there a pursuit where you recovered after getting stuck?', 'paraphrase'),
 ('E002', 'Did we ever make it across during the flood?', 'paraphrase'),
 ('E006', 'Which successful detour avoided steps that your body could not fit?', 'paraphrase'),
 ('E025', 'Tell me about the profitable deep excavation in yesterday\'s block world.', 'paraphrase'),
 ('E030', 'Give the later recorded location of our camp, not your live whereabouts.', 'historical'),
 ('E037', 'What frozen fruit dessert came up in the invented conversation?', 'fictional'),
 ('E044', 'Which imaginary interest involved making shapes from folded sheets?', 'fictional'),
 ('E013', 'What was the depot entrance like in the older October 14 record?', 'temporal'),
 ('E014', 'Which later inspection found the same entrance accessible?', 'temporal'),
 ('E049,E050', 'What is unresolved between the two witnesses in vault scene V?', 'conflict'),
 ('E053,E054', 'Remember the switch that operated a hatch? Which room was that?', 'ambiguous'),
 ('E055,E056', 'Remember the climb to the transmitting tower? I have not said which visit.', 'ambiguous'),
 ('E029,E030', 'Where was our camp in the block world? I have not specified a date.', 'ambiguous'),
]

NO_EVIDENCE = [
 'Did Gregory win a lunar yacht race?',
 'What was Connor\'s real childhood address?',
 'Which violin concerto did Gregory perform on stage?',
 'What medication does the real owner take?',
 'Did Gregory rescue a dolphin in an ocean expedition?',
 'What is the owner\'s actual bank balance?',
 'Remember when we flew a helicopter over Paris?',
 'Did the real Connor say he prefers strawberry ice cream?',
 'Which chess tournament trophy did Gregory win in real life?',
 'What happened when the submarine reached the Mariana Trench?',
 'Which private Discord password was mentioned?',
 'Who won our bowling match last summer?',
 'Where is the spaceship we built on Mars?',
 'What happened when Gregory taught a real university lecture?',
 'Did the real owner authorize production deployment?',
 'What are your current Minecraft coordinates right now?',
 'Is the depot door open right now?',
 'Which game are you connected to right now?',
]


def uid(text):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'gregory.synthetic.nomic.v1/' + text))


def epoch(date, hour=16):
    return datetime.fromisoformat(date + f'T{hour:02}:00:00+00:00').timestamp()


def make_events(row):
    run, cid = uid(row['id']+'/run'), uid(row['id']+'/correlation')
    base = int(row['occurred'] * 1e9)
    counter = iter(range(100))
    factory = EventFactory(run, row['session_id'], text='visible', clock=lambda: base + next(counter)*1000000,
                           mono=lambda: 1000000)
    trace = TraceContext(run, cid)
    out = []
    def emit(kind, payload=None, refs=(), correlated=True):
        eid = uid(row['id']+'/'+str(len(out)))
        v = factory.make(kind, payload, trace=trace if correlated else None,
                         event_id=eid, observation_ids=refs).as_dict()
        out.append(v)
        return eid
    obs = emit('observation.accepted', {'fresh':True}, correlated=False)
    emit('decision.requested', {'origin':'deterministic'})
    emit('decision.applied')
    emit('action.dispatch', {'parameters_complete':True, 'action':{'activity':'say' if row['domain']=='discord' else 'navigate'}})
    emit('controller.feedback', {'status':'stuck' if row['id']=='E001' else 'moving'}, [obs])
    if row['outcome'] != 'unknown':
        emit('outcome.evaluated', {'world_outcome':row['outcome'],
            'verdict':'pass' if row['outcome']=='succeeded' else 'fail', 'evaluator':'synthetic.labelled.v1'}, [obs])
    if row['lifecycle']=='correct':
        emit('decision.response', {'text':row['before_summary']})
    emit('experience.closed', {'world_outcome':row['outcome'], 'text':row['summary'],
        'closure_reason':'verified_arrival' if row['outcome']=='succeeded' else 'timeout'}, [obs])
    return out, run, cid


def build():
    episodes, queries = [], []
    # Audit v2: no target episode (including a conflict pair) crosses dev/test.
    dev_ids = {f'E{i:03}' for i in [4,5,7,8,9,10,11,12,15,16,17,18,26,27,28,38,39,40]}
    for line in STORIES.splitlines():
        ident, domain, date, outcome, text, query = line.split('|')
        tags = [domain, outcome]
        n = int(ident[1:])
        if n in (1,2,3,11,12,21,22):tags.append('following')
        if n in (4,5,6,16,17,18,24,55,56):tags.append('navigation')
        if n in (7,8,13,14,19,24,53,54):tags.append('objects')
        if n in (9,10,15,20,23,55,56):tags.append('goals')
        if 37 <= n <= 44:tags.append('fictional_preference')
        if 49 <= n <= 52:tags.append('conflicting_reports')
        if n in (13,14,29,30,55,56,57,58):tags.append('temporal')
        if n in (13,29,53,54):tags.append('keyword_control')
        lifecycle = 'correct' if n in (59,60,65) else 'expire' if n in (61,62,66) else 'forget' if n in (63,64,67) else 'retain'
        if lifecycle != 'retain':tags.append(lifecycle)
        row = dict(id=ident, domain=domain, date=date, occurred=epoch(date, 13 if lifecycle=='expire' else 16),
                   session_id=domain+'-'+date, outcome=outcome, summary=text,
                   truth_kind='reported', synthetic=True, fictional=(domain=='discord'),
                   lifecycle=lifecycle, tags=tags)
        row['before_summary'] = {'E059':'In fictional Discord roleplay, the character preferred cheesecake.',
                                 'E060':'An unverified report said the shelter delivery was complete.',
                                 'E065':'An unverified cave report called a green patch emerald ore.'}.get(ident,text)
        row['events'], row['run_id'], row['correlation_id'] = make_events(row)
        episodes.append(row)
        expected = [] if lifecycle in ('expire','forget') else [ident]
        if ident in ('E049','E050'):expected=['E049','E050']
        if ident in ('E051','E052'):expected=['E051','E052']
        if ident=='E056':expected=['E055','E056']
        filters = {'domain':domain}
        if ident in ('E013','E014','E029','E030','E055','E057','E058'):
            filters['session_id'] = row['session_id']
        queries.append(dict(id='Q'+ident[1:], query=query, expected_ids=expected,
                            split='dev' if ident in dev_ids else 'test', filters=filters,
                            tags=tags, class_name='lifecycle_absent' if not expected else 'supported'))
    for index, (ids, query, tag) in enumerate(EXTRAS, 68):
        expected=ids.split(',');domain=next(e['domain'] for e in episodes if e['id']==expected[0])
        queries.append(dict(id=f'Q{index:03}', query=query, expected_ids=expected,
                            split='test', filters={'domain':domain}, tags=[tag], class_name='supported'))
    for index, query in enumerate(NO_EVIDENCE, 82):
        expected = {97:['E029','E030'],98:['E013','E014']}.get(index,[])
        filters = {97:{'domain':'minecraft'},98:{'domain':'gmod'}}.get(index,{})
        queries.append(dict(id=f'Q{index:03}', query=query, expected_ids=expected,
                            split='dev' if index < 88 else 'test', filters={},
                            tags=['no_evidence'] + (['historical_state_guard'] if 'right now' in query else []),
                            class_name='no_supported_memory'))
        queries[-1]['filters'] = filters
        if index >= 97:
            queries[-1].update(class_name='historical_state_assertion',
                               retrieval_scored=index!=99, assertion_expected='unknown_live_state')
            queries[-1]['tags']=['historical_state_guard']
    assert len(episodes)==67 and len(queries)==99
    assert sum(q['split']=='dev' for q in queries)==24
    dev_targets={e for q in queries if q['split']=='dev' for e in q['expected_ids']}
    test_targets={e for q in queries if q['split']=='test' for e in q['expected_ids']}
    assert not dev_targets.intersection(test_targets)
    # Bound ASCII inputs conservatively below both installed configurations' limits.
    for text in [e['summary'] for e in episodes]+[e['before_summary'] for e in episodes]+[q['query'] for q in queries]:
        assert text.isascii() and len(text.encode()) + len('search_document: ') <= 400, text
    return dict(schema='gregory.synthetic.nomic-benchmark.v2-label-audit', synthetic_only=True,
                curator='Gordon; independent ground-truth review assigned to Greg',
                consolidation_scope='fixture-authored evidence-linked reported summaries, NOT automatic narrative generation',
                clock_before=epoch('2026-10-22',12), clock_after=epoch('2026-10-22',14),
                retention_seconds=30*86400, k=5, repeats=3, dev_queries=24, test_queries=75,
                no_test_tuning=True, episodes=episodes, queries=queries)


def main():
    out=Path(__file__).with_name('fixtures.json')
    data=build();encoded=(json.dumps(data,indent=2)+'\n').encode();out.write_bytes(encoded)
    lines=['# Nomic benchmark ground truth — frozen before model measurements',
           '', '67 synthetic episodes; 99 queries: 24 dev / 75 held-out test. k=5; three latency repeats.',
           'Curated summaries are reported synthetic fixture text, not automatic narrative consolidation.',
           'Filters are supplied question context, fixed identically for every backend. No live game is connected.',
           'v2 label audit: target episodes are disjoint across dev/test; Q056 needs both visits; Q097/Q098 score historical retrieval separately from live assertions; Q099 is assertion-only/ungraded retrieval.',
           'Retention: 2592000 seconds (30 days). Fixed UTC clocks: 2026-10-22 12:00 before, 14:00 after. Exactly E061/E062/E066 expire and E063/E064/E067 are forgotten; corrected E065 remains.',
           '', '## Episodes', '']
    for e in data['episodes']:
        terminal=e['events'][-1]
        sha=hashlib.sha256(json.dumps(terminal,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        lines += [f"### {e['id']} · {e['domain']} · {e['date']} · {e['outcome']} · {e['lifecycle']}", e['summary'],
                  f"Evidence: run/source_instance `{e['run_id']}`; session `{e['session_id']}`; correlation `{e['correlation_id']}`.",
                  f"Terminal event `{terminal['event_id']}`, source_sequence {terminal['source_sequence']}, canonical-envelope SHA256 `{sha}`. All event IDs, source sequences and envelopes: fixtures.json → {e['id']} → events.", '']
    lines += ['## Questions and expected memory IDs', '']
    for q in data['queries']:
        lines += [f"- **{q['id']} [{q['split']}]** {q['query']}",
                  f"  Expected: {', '.join(q['expected_ids']) or ('UNSCORED RETRIEVAL / LIVE ASSERTION ONLY' if not q.get('retrieval_scored',True) else 'NO SUPPORTED MEMORY')}; context: {json.dumps(q['filters'],sort_keys=True)}; tags: {json.dumps(q['tags'])}"]
    out.with_name('GROUND_TRUTH.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'episodes':67,'queries':99,'dev':24,'test':75,'fixture_sha256':hashlib.sha256(encoded).hexdigest()}))


if __name__=='__main__':main()
