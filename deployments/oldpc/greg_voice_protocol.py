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
# so 'forced stop', 'force, stop' and 'force stop now' all have to land.
_FORCE = {'force', 'forced', 'forceful', '4orce'}
_FILLER = {'now', 'please', 'already', 'immediately', 'it'}
_FORCE_STOP = {'stop', 'halt', 'freeze', 'stop moving', 'stand still', 'stay still'}
_FORCE_BACK = {'back', 'backward', 'backwards', 'back up', 'backup', 'reverse'}


def force_command(text):
    """Return 'stop', 'back', or None. The caller must also check the speaker is the owner."""
    if not isinstance(text, str):
        return None
    value = ' '.join(re.sub(r'[^a-z0-9]+', ' ', text.casefold()).split())
    value = re.sub(r'^gregory\s+', '', value)
    words = [w for w in value.split() if w not in _FILLER]
    if len(words) < 2 or words[0] not in _FORCE:
        return None
    target = ' '.join(words[1:])
    if target in _FORCE_STOP:
        return 'stop'
    if target in _FORCE_BACK:
        return 'back'
    return None


def force_action(command):
    """The command a force phrase becomes, bypassing persona, temperature and queue."""
    if command == 'stop':
        return {'action': 'wait', 'mode': 'stop'}
    if command == 'back':
        return {'action': 'move', 'dir': 'back', 'duration': 1.0, 'walk': True, 'mode': 'stop'}
    return None
