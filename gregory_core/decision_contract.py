"""Turn-local choices and constrained output. No dispatch, memory or global alias map."""
from copy import deepcopy
import json

class SchemaViolation(ValueError):pass

def validate(value,schema,path='$'):
    """Validate the small JSON-Schema subset emitted here; never execute schema text."""
    if 'anyOf' in schema:
        for branch in schema['anyOf']:
            try:validate(value,branch,path);return
            except SchemaViolation:pass
        raise SchemaViolation('decision schema branch mismatch at '+path)
    if 'enum' in schema and (type(value) not in (str,int,float,bool,type(None)) or value not in schema['enum']):
        raise SchemaViolation('decision schema enum mismatch at '+path)
    kind=schema.get('type')
    good={'object':type(value) is dict,'array':type(value) is list,'string':type(value) is str,
          'integer':type(value) is int,'number':type(value) in (int,float),'null':value is None,'boolean':type(value) is bool}
    if kind and not good.get(kind,False):raise SchemaViolation('decision schema type mismatch at '+path)
    if kind=='object':
        props=schema.get('properties',{})
        if set(schema.get('required',[]))-set(value):raise SchemaViolation('decision schema missing key at '+path)
        if schema.get('additionalProperties') is False and set(value)-set(props):raise SchemaViolation('decision schema extra key at '+path)
        for key,row in value.items():
            if key in props:validate(row,props[key],path+'.'+key)
    elif kind=='array':
        if len(value)<schema.get('minItems',0) or len(value)>schema.get('maxItems',100000):raise SchemaViolation('decision schema array bounds at '+path)
        for row in value:validate(row,schema.get('items',{}),path+'[]')
    elif kind=='string':
        if len(value)<schema.get('minLength',0) or len(value)>schema.get('maxLength',100000):raise SchemaViolation('decision schema text bounds at '+path)
    elif kind in {'integer','number'}:
        import math
        if not math.isfinite(value) or value<schema.get('minimum',-float('inf')) or value>schema.get('maximum',float('inf')):
            raise SchemaViolation('decision schema number bounds at '+path)

def obj(properties,required=None):
    return dict(type='object',properties=properties,required=list(properties) if required is None else required,additionalProperties=False)
def text(limit):return dict(type='string',maxLength=limit)
def enum(values):return dict(type='string',enum=list(values))
def envelope(intents,memory_ids=()):
    item=enum(memory_ids) if memory_ids else dict(type='string')
    return obj(dict(say=dict(type='string',minLength=1,maxLength=1200),intent=dict(anyOf=intents),
                    used_memory_ids=dict(type='array',items=item,maxItems=min(3,len(memory_ids)))))

def generate(provider,profile,prompt,*,images=None,response_schema=None):
    if response_schema is not None:
        method=getattr(provider,'generate_constrained',None)
        if method is None:raise SchemaViolation('provider lacks constrained decision support')
        result=method(profile,prompt,images=images,response_schema=response_schema)
        validate(result,response_schema)
        return result
    return provider.generate(profile,prompt,images=images) if images else provider.generate(profile,prompt)

def without_inspection(schema):
    if schema is None:return None
    result=deepcopy(schema)
    choices=result['properties']['intent']['anyOf']
    result['properties']['intent']['anyOf']=[b for b in choices if
        (b.get('properties',{}).get('action',{}).get('enum') or [])!=['inspect_screen']]
    return result

def activity_intents(offered):
    choices=[obj(dict(action=enum(['game_activity']),choice=obj(dict(activity=enum(['rest']))))),
             obj(dict(action=enum(['game_activity']),choice=obj(dict(activity=enum(['browse']),query=text(300),kind=text(300)))))]
    if offered.get('autonomous_rest_available') is False:choices.pop(0)
    if offered.get('navigation_available'):
        choices.append(obj(dict(action=enum(['game_activity']),choice=obj(dict(activity=enum(['explore']))))))
        names=[e['name'] for e in offered.get('landmarks',[]) if isinstance(e.get('name'),str)]
        if names:choices.append(obj(dict(action=enum(['game_activity']),choice=obj(dict(activity=enum(['tour']),landmark=enum(names))))))
    ids=[e['id'] for e in offered.get('spawn_choices',[]) if isinstance(e.get('id'),str)]
    if ids:choices.append(obj(dict(action=enum(['game_activity']),choice=obj(dict(activity=enum(['spawn']),id=enum(ids))))))
    return choices

class TurnChoices:
    """Owns one immutable native offer and its private model-facing labels."""
    hint="Use this turn's D/P targets and T1 task label exactly. "
    def __init__(self,view):
        self.native=deepcopy(view);self.view=deepcopy(view);self.destinations={};self.players={}
        for field,prefix,table in [('destinations','D',self.destinations),('players','P',self.players)]:
            for i,row in enumerate(self.view.get(field,[]),1):
                label=prefix+str(i);table[label]=row['id'];row['id']=label
        task=self.view.get('current_task') or {}
        self.task_id=(view.get('current_task') or {}).get('id')
        if self.task_id:task['id']='T1'
        target=task.get('target')
        if isinstance(target,dict) and target.get('id'):
            table=self.players if task.get('kind') in {'follow','approach'} else self.destinations
            label=next((key for key,value in table.items() if value==target['id']),None)
            if label is None and task.get('kind')=='visit':
                label='D'+str(len(self.destinations)+1);table[label]=target['id']
            target['id']=label or 'current_target'
        refusal=self.view.get('last_refusal') or {}
        if refusal.get('target'):
            refusal['target']=next((k for k,v in {**self.destinations,**self.players}.items() if v==refusal['target']),'previous_unavailable')

    def schema(self,visible,offered,*,memory_ids=(),internal=False,screen=False,listen=False):
        from greg_game_tasks import GameTasks
        task=visible.get('current_task') or {}
        kinds=GameTasks.allowed_kinds(bool(visible.get('navigation_available')),task,bool(visible.get('players')),visible.get('heading') is not None)
        destinations=[e['id'] for e in visible.get('destinations',[])]
        previous=(task.get('target') or {}).get('id')
        if task.get('kind')=='visit' and previous in self.destinations and previous not in destinations:destinations.append(previous)
        players=[e['id'] for e in visible.get('players',[])]
        choices=[dict(type='null')]
        for kind in kinds:
            if internal and (task.get('final_review') or task.get('attempts',0)>=3) and kind not in {'continue','settle','cancel'}:continue
            if internal and not self.task_id and kind!='continue':continue
            props=dict(action=enum(['game_task']),kind=enum([kind]));required=['action','kind']
            if kind in {'visit','hide','follow','approach'}:
                targets=players if kind in {'follow','approach'} else destinations
                if not targets:continue
                props['target']=enum(targets);required.append('target')
            if kind in {'visit','hide','follow','approach','move','hold'}:
                props['objective']=text(240)
            if kind in {'visit','hide','follow','approach','move'}:
                props['budget_seconds']=dict(type='integer',minimum=30,maximum=600)
            if kind in {'visit','hide','hold','settle'}:
                props['stay_seconds']=dict(type='integer',minimum=1 if kind=='hold' else 0,maximum=300)
            if kind=='visit':props['completion']=enum(['arrival','observe_cover'])
            if kind=='move':
                props.update(direction=enum(['forward','backward','left','right']),distance=dict(type='number',minimum=64,maximum=1024));required.append('direction')
            if kind!='continue' and self.task_id:
                exhausted=(kind in {'visit','hide','move','follow','approach'} and task.get('attempts',0)>=3) or (kind=='hold' and (task.get('final_review') or (task.get('completion')=='observe_cover' and task.get('attempts',0)>=3)))
                if exhausted and internal:continue
                if not exhausted:props['task_id']=enum(['T1'])
                if internal or kind=='settle':required.append('task_id')
            if kind=='settle' and not self.task_id:continue
            choices.append(obj(props,required))
        if not internal:choices.extend(activity_intents(offered))
        if screen:choices.append(obj(dict(action=enum(['inspect_screen']))))
        if listen:choices.append(obj(dict(action=enum(['voice_turn']),kind=enum(['listen']))))
        return envelope(choices,memory_ids)

    def decode(self,intent,schema):
        # Validate first, including exact enums. No fuzzy match or raw-ID fallback.
        validate(intent,schema['properties']['intent'])
        result=deepcopy(intent)
        if not isinstance(result,dict) or result.get('action')!='game_task':return result
        if 'target' in result:
            table=self.players if result['kind'] in {'follow','approach'} else self.destinations
            result['target']=table[result['target']]
        if 'task_id' in result:result['task_id']=self.task_id
        return result
