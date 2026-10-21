"""Synthetic PR1-contract experiences; no game, network or real-person data."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployments' / 'oldpc'))
from greg_events import EventFactory, TraceContext, new_id
from gregory_core.embeddings import EmbeddingSpace


def experience(*, session='synthetic-session', start=1700000000, movements=0,
               closed=True, outcome='succeeded', gap=False, model=False):
    run, cid = new_id(), new_id()
    counter = iter(range(10000))
    factory = EventFactory(run, session, clock=lambda: int(start * 1e9) + next(counter) * 1000000)
    trace = TraceContext(run, cid)
    events = []
    def emit(kind, payload=None, refs=(), correlated=True):
        e = factory.make(kind, payload, trace=trace if correlated else None, observation_ids=refs).as_dict()
        events.append(e)
        return e['event_id']
    obs = emit('observation.accepted', {'fresh': True}, correlated=False)
    emit('decision.requested', {'origin': 'model' if model else 'deterministic'})
    if model:
        emit('decision.response', {'text': 'untrusted model narrative'})
    emit('decision.applied')
    emit('action.dispatch', {'parameters_complete': True, 'action': {'activity': 'follow'}})
    emit('controller.feedback', {'status': 'stuck'}, [obs])
    for _ in range(movements):
        emit('controller.feedback', {'status': 'moving'}, [obs])
    if gap:
        emit('telemetry.gap', correlated=False)
    if outcome != 'unknown':
        emit('outcome.evaluated', {'world_outcome': outcome,
             'verdict': 'pass' if outcome == 'succeeded' else 'fail', 'evaluator': 'synthetic.fixture.v1'}, [obs])
    if closed:
        emit('experience.closed', {'world_outcome': outcome,
             'closure_reason': 'verified_arrival' if outcome == 'succeeded' else 'timeout'}, [obs])
    return events, run, cid


class FixtureEmbedder:
    """Hand-labelled vectors for ranking plumbing, NEVER real Nomic embeddings."""
    space = EmbeddingSpace('synthetic-fixture-NOT-Nomic', 'fixture-v1', dimensions=3)

    def document(self, text):
        if 'orchard' in text:
            return (0, 1, 0)
        if 'Minecraft' in text:
            return (0, 0, 1)
        return (1, 0, 0)

    def query(self, text):
        if 'fruit' in text or 'orchard' in text:
            return (0, 1, 0)
        if 'Minecraft' in text:
            return (0, 0, 1)
        return (1, 0, 0)
