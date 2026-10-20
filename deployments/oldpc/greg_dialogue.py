"""Only explicit dialogue fields can reach chat; never speak raw model output."""
import json,re,time,threading
from pathlib import Path
try:
    from greg_events import observed as _observed
except Exception:
    def _observed(*args, **kwargs): pass
_lock=threading.Lock()
_debug=re.compile(r'<\/?(?:think|analysis|reasoning)>|\b(?:analysis|reasoning|chain.of.thought)\s*:|eye trace|hit world|waiting_obstacle|controlEpoch|locomotion|\bcursor\b|no new chatter',re.I)
def dialogue(value):
    if not isinstance(value,str):return ''
    text=' '.join(value.split())
    # Reject whole invalid/overlong speech instead of chopping a thought mid-sentence.
    if not text or len(text.encode('utf-8'))>240 or _debug.search(text):return ''
    if text.startswith(('{','[','```')):return ''
    return text
def model_json(message,source='model'):
    raw=message.get('content','') if isinstance(message,dict) else ''
    if not isinstance(raw,str):return {}
    cleaned=re.sub(r'<think>.*?</think>','',raw,flags=re.S|re.I).strip()
    if cleaned.startswith('```') and cleaned.endswith('```'):
        cleaned=re.sub(r'^```(?:json)?\s*','',cleaned)[:-3].strip()
    parse_status='invalid_json' if raw.strip() else 'empty'
    try:
        value=json.loads(cleaned)
        parse_status='object' if isinstance(value,dict) else 'non_object'
        if not isinstance(value,dict):value={}
    except (ValueError,TypeError):value={}
    _observed('decision.parsed', {'json_valid': parse_status=='object', 'parse_status':parse_status, 'parsed': value})
    # Bounded diagnostic record stays on disk, not in chat. Reasoning fields are never read.
    try:
        path=Path(__file__).with_name('greg_model_audit.jsonl')
        with _lock:
            if path.exists() and path.stat().st_size>262144:path.replace(path.with_suffix('.previous.jsonl'))
            with path.open('a',encoding='utf-8')as f:
                f.write(json.dumps({'time':time.time(),'source':source,'content':raw[:2000],
                    'has_reasoning_field':bool(message.get('reasoning_content') or message.get('reasoning')),
                    'json_valid':bool(value)},ensure_ascii=True)+'\n')
    except OSError:pass
    return value
