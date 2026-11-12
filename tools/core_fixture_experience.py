"""Real Recorder export for isolated Core tests/demo; explicitly synthetic, never live."""
from contextlib import closing
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deployments/oldpc'))
from greg_recorder import Recorder, open_reader, export_run
from greg_experience import ExperienceTracker


def capture_fixture(root):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=True)
    recorder=Recorder(root/'fixture-recorder.sqlite3','fixture-session-A',max_mib=64,
                      build='core-fixture-NOT-live')
    if not recorder.wait_ready(): raise RuntimeError('fixture recorder unavailable')
    tracker=ExperienceTracker(recorder,landmark_capture=True)
    state=dict(steamid='fixture-actor',bridgeSession='fixture-adapter-A',controlEpoch=1,
        map='gm_construct',seq=1,t=1,serverTime=time.time(),enabled=True,dead=False,menu=False,
        pos=dict(x=0,y=0,z=0),eye=dict(hit=True,hitWorld=False,hitEntityValid=True,
        hitPos=dict(x=18,y=9,z=7),hitClass='prop_physics',hitName='NOT PERSISTED',
        entIndex=71,model='models/props_junk/wood_crate001a.mdl',entityPos=dict(x=20,y=10,z=5)))
    try:
        tracker.accepted_state(state)
        trace=tracker.begin_decision(lane='deterministic')
        tracker.decision_result(trace,accepted=True,reason='fixture-only')
        tracker.dispatch(dict(seq=1,session='fixture-command',action=dict(action='navigate',
            id='fixture-route',points=[dict(x=40,y=0,z=0)],lease=2.5)))
        receipt=tracker.observe_landmark()
        if receipt['outcome']!='prop_observed': raise RuntimeError('fixture landmark not captured')
        tracker.shutdown()
    finally:
        health=recorder.close()
    if health['thread_alive'] or health['dropped'] or health['invalid']:
        raise RuntimeError('fixture recorder loss')
    output=root/'fixture-export.jsonl'
    with closing(open_reader(root/'fixture-recorder.sqlite3')) as db:
        export_run(db,recorder.run_id,output)
    events=[json.loads(line) for line in output.read_text().splitlines()]
    for event in events: event.pop('ingest_sequence',None)
    result=dict(events=events,run_id=recorder.run_id,correlation_id=trace.correlation_id,
                domain='gmod',source_label='fixture-NOT-live-GMod')
    (root/'fixture-import.json').write_text(json.dumps(result),encoding='utf8')
    return result


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True)
    args=p.parse_args();result=capture_fixture(args.root)
    print(json.dumps({'fixture_only':True,'run_id':result['run_id'],
                      'import_file':str(Path(args.root)/'fixture-import.json')}))
