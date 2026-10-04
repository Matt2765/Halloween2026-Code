"""Preflight validation shared by GUI and headless runners."""
import math
from .model import EVENTS, ACTIONS, CONDITIONS, length, check_structure


def validate(p):
    errors, warnings = [], []
    try:
        check_structure(p)
    except (ValueError,TypeError,KeyError,AttributeError) as exc:
        return [str(exc)],warnings
    objects = p.by_id()
    ids = [o['id'] for o in p.objects] + [r['id'] for r in p.rules]
    if len(ids) != len(set(ids)):
        errors.append('Duplicate object/rule IDs')
    enabled = [o for o in p.objects if o['enabled']]
    entrances = [o for o in enabled if o['kind'] == 'entrance']
    exits = [o['id'] for o in enabled if o['kind'] == 'exit']
    if len(entrances) != 1:
        errors.append('Exactly one enabled entrance is required')
    if not exits:
        errors.append('Missing exit')
    graph = {o['id']: [] for o in enabled if o['kind'] in ('room', 'entrance', 'exit')}

    def check_range(value, label, positive=False):
        try:
            a, b, c = [float(value[k]) for k in ('min', 'typical', 'max')]
            if not all(math.isfinite(v) for v in (a,b,c)) or not 0 <= a <= b <= c or (positive and a <= 0):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            errors.append(f'{label}: invalid minimum / typical / maximum')

    check_range(p.settings['group_size'], 'Group size', True)
    check_range(p.settings['speed'], 'Walking speed', True)
    if p.settings['duration'] <= 0 or p.settings['limit'] <= 0:
        errors.append('Run duration and completion limit must be positive')
    if p.settings['stop'] not in ('time','groups','guests','manual'):
        errors.append('Unknown run stop condition')
    for key in ('limit','exterior_groups','seed'):
        if p.settings[key]<0 or int(p.settings[key])!=p.settings[key]:
            errors.append(f'{key}: must be a nonnegative integer')
    if p.settings['pixels_per_unit']<0:
        errors.append('Scale cannot be negative')
    for o in enabled:
        k, label = o['kind'], o['name']
        if k == 'room':
            check_range(o['duration'], label)
            if o['capacity'] < 1 or int(o['capacity'])!=o['capacity'] or not 0 <= o['acceptable_min'] <= o['preferred'] <= o['acceptable_max']:
                errors.append(f'{label}: invalid capacity or acceptable timing bounds')
            if min(o['width'],o['height'])<=0:
                errors.append(f'{label}: room dimensions must be positive')
        elif k == 'path':
            if o['source'] not in graph or o['target'] not in graph:
                errors.append(f'{label}: connect both ends to enabled rooms/entrance/exit')
            else:
                graph[o['source']].append(o['target'])
                if objects[o['source']]['kind'] not in ('entrance','room') or objects[o['target']]['kind'] not in ('room','exit'):
                    errors.append(f'{label}: routes must lead from entrance/room to room/exit')
            if len(o['points']) < 2 or length(o['points']) <= 0:
                errors.append(f'{label}: path needs two distinct points')
            if o['seconds'] <= 0 and p.settings['pixels_per_unit'] <= 0:
                errors.append(f'{label}: set a travel-time override or calibrate scale')
            if o['weight'] <= 0:
                errors.append(f'{label}: branch weight must be positive')
            if o['seconds']<0 or o['spacing']<0:
                errors.append(f'{label}: travel time and spacing cannot be negative')
        elif k == 'sensor':
            if o['path'] not in objects or objects[o['path']]['kind'] != 'path':
                errors.append(f'{label}: sensor must reference a path')
            if not 0 <= o['fraction'] <= 1 or o['cooldown'] < 0:
                errors.append(f'{label}: invalid sensor position/cooldown')
        elif k == 'door':
            if min(o['opening'], o['closing'], o['hold']) < 0:
                errors.append(f'{label}: door durations cannot be negative')
            if o['style'] not in ('swing','slide','passage') or o['width']<=0:
                errors.append(f'{label}: invalid door style/width')
            if not o.get('path'):
                warnings.append(f'{label}: door is not connected to a path')
            elif o['path'] not in objects or objects[o['path']]['kind']!='path':
                errors.append(f'{label}: associated path is missing')
    def reachable(start):
        seen, todo = set(), [start]
        while todo:
            n = todo.pop()
            if n not in seen:
                seen.add(n)
                todo.extend(graph.get(n, []))
        return seen
    if entrances:
        reached = reachable(entrances[0]['id'])
        for n in graph:
            if n not in reached:
                errors.append(f"{objects[n]['name']}: unreachable from entrance")
            if not set(exits) & reachable(n):
                errors.append(f"{objects[n]['name']}: no route to an exit")
    valid_ids = set(ids)
    signals = {}
    for r in p.rules:
        if r['event'] not in EVENTS or r['action'] not in ACTIONS:
            errors.append(f"{r['name']}: unknown event/action")
        if r.get('source') and r['source'] not in valid_ids and r['event']!='custom_signal':
            errors.append(f"{r['name']}: deleted source reference")
        condition=r.get('condition','always')
        ctarget=r.get('condition_target','')
        if condition not in CONDITIONS:
            errors.append(f"{r['name']}: unknown condition")
        elif condition!='always':
            if ctarget not in valid_ids:
                errors.append(f"{r['name']}: deleted condition target reference")
            expected=('room' if condition.startswith('room_') else 'path' if condition=='path_clear'
                      else 'door' if condition.startswith('door_') else '')
            if expected and objects.get(ctarget,{}).get('kind')!=expected:
                errors.append(f"{r['name']}: {condition} requires a {expected} target")
        if r['action'] not in ('signal', 'admit') and r['target'] not in valid_ids:
            errors.append(f"{r['name']}: missing action target")
        if r['action'] in ('open_door','close_door') and objects.get(r['target'],{}).get('kind') != 'door':
            errors.append(f"{r['name']}: action target must be a door")
        if r['delay'] < 0:
            errors.append(f"{r['name']}: negative action delay")
        if r['event'] == 'custom_signal' and r['action'] == 'signal' and r['source'] == r['target'] and r['delay'] == 0:
            errors.append(f"{r['name']}: immediate signal cycle")
        if r['enabled'] and r['event']=='custom_signal' and r['action']=='signal':
            signals.setdefault(r['source'],[]).append(r['target'])
    def cycle(node,stack,visited):
        if node in stack:
            return True
        if node in visited:
            return False
        visited.add(node)
        return any(cycle(target,stack|{node},visited) for target in signals.get(node,[]))
    if any(cycle(node,set(),set()) for node in signals):
        errors.append('Cyclic custom-signal rules can generate runaway events')
    admissions = [r for r in p.rules if r['enabled'] and r['action']=='admit']
    if not admissions:
        errors.append('Configure an event rule to admit subsequent groups')
    if not p.settings['initial_release'] and not any(r['event']=='simulation_started' for r in admissions):
        warnings.append('First group requires the Manual release button or a start signal')
    if not p.background:
        warnings.append('No background image; simulation can still use the drawn graph')
    return errors, warnings
