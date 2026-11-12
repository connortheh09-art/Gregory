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
