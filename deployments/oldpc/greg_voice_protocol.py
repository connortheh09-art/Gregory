"""Shared voice directive spelling; no audio/network/model imports."""
import re


def inbox_text(text):
    """Explicit one-turn permission to discuss the sender's DMs in this call."""
    if not isinstance(text, str):
        return False
    value = ' '.join(re.sub(r'[^a-z0-9]+', ' ', text.casefold()).split())
    value = re.sub(r'^gregory\s+', '', value)
    return value in {'check my dms in this call', 'read my dms in this call',
                    'check my messages in this call', 'read my messages in this call'}


def stop_text(text):
    if not isinstance(text,str):return False
    value=' '.join(re.sub(r'[^a-z0-9]+',' ',text.casefold()).split())
    value=re.sub(r'^gregory\s+','',value)
    return value in {'stop','wait','halt','freeze','stop moving','stop now','stand still','stay still','don t move','do not move'}


# Force phrases never reach the model. Loose on purpose: Whisper drops and reshapes words,
# so 'forced stop', 'force, stop', 'forstop' and a phrase buried at the start of a longer
# sentence all have to land. Force back stays strict: a reverse drive is not harmless.
_FORCE = {'force', 'forced', 'forceful', '4orce'}
_FILLER = {'now', 'please', 'already', 'immediately', 'it'}
_FORCE_STOP = {'stop', 'halt', 'freeze', 'stop moving', 'stand still', 'stay still'}
_FORCE_BACK = {'back', 'backward', 'backwards', 'back up', 'backup', 'reverse'}
_FUSED_STOP = re.compile(r'^(?:4orce|force|forced|forceful|for)(?:stop|halt|freeze)$')
_FUSED_BACK = re.compile(r'^(?:4orce|force|forced|forceful)(?:back|backup|backwards?|reverse)$')
_STOP_HEAD = {'stop', 'halt', 'freeze'}
_STOP_PAIR = {'stop moving', 'stand still', 'stay still'}
_BACK_HEAD = {'back', 'backward', 'backwards', 'backup', 'reverse'}
# Words that may precede the command without making it a different sentence.
_LEAD_IN = {'okay', 'ok', 'uh', 'um', 'uhh', 'hey', 'greg', 'gregory', 'gregorys', 's',
            'so', 'yeah', 'well', 'right', 'alright'}


def force_command(text):
    """Return 'stop', 'back', or None. The caller must also check the speaker is the owner."""
    if not isinstance(text, str):
        return None
    value = ' '.join(re.sub(r'[^a-z0-9]+', ' ', text.casefold()).split())
    value = re.sub(r'^gregory\s+', '', value)
    words = value.split()
    # A short lead-in ('okay Gregory, force stop') is still the same command.
    for _ in range(3):
        if words and words[0] in _LEAD_IN:
            words = words[1:]
        else:
            break
    if not words:
        return None
    head = words[0]
    rest = words[1:]
    while rest and rest[-1] in _FILLER:
        rest.pop()
    # Whisper fuses the two words into one: 'forstop', 'forcestop'.
    # Stop tolerates trailing commentary; back must be the whole command.
    if _FUSED_STOP.match(head):
        return 'stop'
    if _FUSED_BACK.match(head) and not rest:
        return 'back'
    if head not in _FORCE:
        return None
    if not rest:
        return None
    # Stop tolerates trailing commentary; that is the 'Forstop and then...' miss.
    if rest[0] in _STOP_HEAD or ' '.join(rest[:2]) in _STOP_PAIR:
        return 'stop'
    # Back must be the whole command: a two-second reverse drive is not a harmless misfire.
    if rest[0] in _BACK_HEAD and len(rest) == 1:
        return 'back'
    if ' '.join(rest[:2]) in _FORCE_BACK and len(rest) == 2:
        return 'back'
    return None


def force_action(command):
    """The command a force phrase becomes, bypassing persona, temperature and queue."""
    if command == 'stop':
        return {'action': 'wait', 'mode': 'stop'}
    if command == 'back':
        return {'action': 'move', 'dir': 'back', 'duration': 1.0, 'walk': True, 'mode': 'stop'}
    return None
