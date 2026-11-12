"""Bounded engine-authored eye-hit contract. No names, captions or passthrough."""
import math
import re

PROP_CLASSES = frozenset({'prop_physics', 'prop_physics_multiplayer'})


def position(value):
    if not isinstance(value, dict) or set(value) != {'x', 'y', 'z'}:
        raise ValueError('exact position required')
    if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e7
           for v in value.values()):
        raise ValueError('finite bounded position required')
    return dict(value)


def identifier(value, *, model=False):
    pattern = r'[A-Za-z0-9_/.-]+\.mdl' if model else r'[A-Za-z0-9_.-]+'
    if not isinstance(value, str) or not 1 <= len(value) <= 160 or '..' in value or not re.fullmatch(pattern, value):
        raise ValueError('bounded engine identifier required')
    return value


def validate_descriptor(value):
    base = {'schema_version', 'hit', 'hitWorld', 'hitEntityValid', 'outcome', 'hitPos'}
    positive = isinstance(value, dict) and value.get('outcome') == 'prop_observed'
    expected = base | ({'entIndex', 'class', 'model', 'pos'} if positive else set())
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('unknown or missing landmark descriptor field')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('unsupported landmark descriptor')
    if any(type(value[k]) is not bool for k in ('hit', 'hitWorld', 'hitEntityValid')):
        raise ValueError('explicit hit flags required')
    result = dict(value, hitPos=position(value['hitPos']))
    if positive:
        if not value['hit'] or value['hitWorld'] or not value['hitEntityValid']:
            raise ValueError('contradictory prop hit')
        if type(value['entIndex']) is not int or not 1 <= value['entIndex'] <= 65535:
            raise ValueError('snapshot entity index required')
        if value['class'] not in PROP_CLASSES:
            raise ValueError('canary accepts physics props only')
        result.update(model=identifier(value['model'], model=True), pos=position(value['pos']))
    elif value['outcome'] != 'no_valid_prop':
        raise ValueError('explicit negative outcome required')
    return result


def descriptor_from_eye(eye):
    if not isinstance(eye, dict):
        raise ValueError('explicit eye report required')
    result = {k: eye.get(k) for k in ('hit', 'hitWorld', 'hitEntityValid', 'hitPos')}
    positive = (result['hit'] is True and result['hitWorld'] is False and
                result['hitEntityValid'] is True and eye.get('hitClass') in PROP_CLASSES)
    result.update(schema_version=1, outcome='prop_observed' if positive else 'no_valid_prop')
    if positive:
        result.update(entIndex=eye.get('entIndex'), model=eye.get('model'),
                      **{'class': eye.get('hitClass'), 'pos': eye.get('entityPos')})
    return validate_descriptor(result)
