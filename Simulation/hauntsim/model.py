"""Portable, JSON-compatible project model and geometric helpers."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, field, asdict
import math
import random
import uuid

EVENTS = ['simulation_started', 'haunt_entered', 'room_entered', 'room_completed',
          'room_exited', 'sensor_crossed', 'location_reached', 'path_entered',
          'path_exited', 'door_opening', 'door_opened', 'door_closing', 'door_closed',
          'haunt_exited', 'custom_signal']
ACTIONS = ['admit', 'open_door', 'close_door', 'enable', 'disable', 'signal']
CONDITIONS = ['always', 'room_available', 'room_empty', 'room_occupied',
              'path_clear', 'door_open', 'door_closed', 'enabled', 'disabled']


def uid():
    return uuid.uuid4().hex[:12]


def timing(typical=20., minimum=None, maximum=None):
    return {'min': typical if minimum is None else minimum, 'typical': typical,
            'max': typical if maximum is None else maximum}


def sample(value, rng: random.Random):
    lo, mode, hi = (float(value[k]) for k in ('min', 'typical', 'max'))
    return lo if lo == hi else rng.triangular(lo, hi, mode)


def length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def interpolate(points, fraction):
    if not points:
        return (0., 0.)
    remaining = length(points) * max(0., min(1., fraction))
    for a, b in zip(points, points[1:]):
        distance = math.dist(a, b)
        if distance and remaining <= distance:
            return tuple(a[i] + (b[i] - a[i]) * remaining / distance for i in (0, 1))
        remaining -= distance
    return tuple(points[-1])


def nearest_fraction(points, point):
    total = length(points)
    traversed, best_distance, best_fraction = 0., float('inf'), 0.
    for a,b in zip(points,points[1:]):
        vector = [b[i]-a[i] for i in (0,1)]
        squared = sum(v*v for v in vector)
        ratio = max(0.,min(1.,sum((point[i]-a[i])*vector[i] for i in (0,1))/squared)) if squared else 0.
        projection = [a[i]+ratio*vector[i] for i in (0,1)]
        distance = math.dist(point,projection)
        segment = math.sqrt(squared)
        if distance < best_distance:
            best_distance, best_fraction = distance, (traversed+ratio*segment)/max(total,.000001)
        traversed += segment
    return best_fraction


def door_path_fraction(path, door):
    """Return where the closed door leaf intersects a route, or its nearest point."""
    angle=math.radians(door.get('angle',0.))
    hinge=[door['x'],door['y']]
    tip=[hinge[0]+door.get('width',0.)*math.cos(angle),
         hinge[1]+door.get('width',0.)*math.sin(angle)]
    total=length(path['points'])
    traversed=0.
    for a,b in zip(path['points'],path['points'][1:]):
        route=[b[i]-a[i] for i in (0,1)]
        leaf=[tip[i]-hinge[i] for i in (0,1)]
        cross=route[0]*leaf[1]-route[1]*leaf[0]
        segment=math.dist(a,b)
        if abs(cross)>1e-9:
            offset=[hinge[i]-a[i] for i in (0,1)]
            along=(offset[0]*leaf[1]-offset[1]*leaf[0])/cross
            across=(offset[0]*route[1]-offset[1]*route[0])/cross
            if -1e-9<=along<=1+1e-9 and -1e-9<=across<=1+1e-9:
                return (traversed+max(0.,min(1.,along))*segment)/max(total,.000001)
        traversed+=segment
    midpoint=[(hinge[i]+tip[i])/2 for i in (0,1)]
    return nearest_fraction(path['points'],midpoint)


def travel(path, project, speed):
    if path['seconds'] > 0:
        return path['seconds']
    return length(path['points']) / project.settings['pixels_per_unit'] / speed


def new_object(kind, x=100., y=100., points=None):
    obj = dict(id=uid(), kind=kind, name=kind.title(), enabled=True, x=x, y=y, notes='')
    if kind == 'room':
        obj.update(width=130., height=85., duration=timing(20), preferred=20.,
                   acceptable_min=10., acceptable_max=40., capacity=1)
    elif kind == 'path':
        obj.update(source='', target='', points=points or [[x, y], [x+100, y]],
                   seconds=5., weight=1., spacing=2.)
    elif kind == 'door':
        obj.update(style='swing', angle=0., open_angle=90., width=35., slide_x=35.,
                   slide_y=0., opening=2., closing=2., hold=3., automatic=True, path='')
    elif kind == 'sensor':
        obj.update(path='', fraction=.5, cooldown=0.)
    return obj


@dataclass
class Project:
    name: str = 'Untitled haunt'
    version: int = 1
    objects: list = field(default_factory=list)
    rules: list = field(default_factory=list)
    settings: dict = field(default_factory=lambda: dict(
        units='feet', pixels_per_unit=0., group_size=timing(4), speed=timing(3.),
        seed=42, random_seed=False, duration=3600., stop='time', limit=100,
        exterior_groups=0, initial_release=True))
    scenarios: dict = field(default_factory=dict)
    results: list = field(default_factory=list)
    background: bytes = field(default=b'', repr=False)

    def data(self):
        data = asdict(self)
        del data['background']
        data['results'] = data['results'][-20:]
        return data

    @classmethod
    def from_data(cls, data, background=b''):
        if not isinstance(data,dict):
            raise ValueError('Project data must be an object')
        if type(data.get('version')) is not int or data.get('version') != 1:
            raise ValueError(f"Unsupported project version {data.get('version')}; supported: 1")
        result = cls(**deepcopy(data))
        result.background = background
        check_structure(result)
        result.migrate_legacy_doors()
        for name in result.scenarios:
            check_structure(result.scenario(name))
        return result

    def migrate_legacy_doors(self):
        """Move version-1 path door references onto door objects in memory."""
        objects=self.by_id()
        for path in self.objects:
            if path.get('kind')!='path':
                continue
            did=path.pop('door','')
            door=objects.get(did)
            if did and door and door.get('kind')=='door' and not door.get('path'):
                door['path']=path['id']
        for door in self.objects:
            if door.get('kind')=='door':
                door.setdefault('path','')
        for rule in self.rules:
            # Older projects retain their original check-once behavior until the
            # user enables remembered conditions in the rule editor.
            rule.setdefault('wait_for_condition',False)

    def by_id(self):
        return {o['id']: o for o in self.objects}

    def scenario(self, name='Base'):
        result = deepcopy(self)
        overrides = self.scenarios.get(name, {})
        for obj in result.objects:
            obj.update(deepcopy(overrides.get('objects', {}).get(obj['id'], {})))
        result.settings.update(deepcopy(overrides.get('settings', {})))
        if 'rules' in overrides:
            result.rules = deepcopy(overrides['rules'])
        objects=result.by_id()
        for sensor in result.objects:
            if sensor['kind']=='sensor' and objects.get(sensor['path'],{}).get('kind')=='path':
                sensor['x'],sensor['y']=interpolate(objects[sensor['path']]['points'],sensor['fraction'])
        return result


def check_structure(project):
    """Reject malformed portable data while still allowing unfinished editable layouts."""
    def finite(value,label):
        if isinstance(value,float) and not math.isfinite(value):
            raise ValueError(f'{label}: numbers must be finite')
        if isinstance(value,dict):
            for key,item in value.items():
                finite(item,f'{label}.{key}')
        elif isinstance(value,list):
            for item in value:
                finite(item,label)
    finite(project.data(),'Project')
    def fields(value,template,label):
        if not isinstance(value,dict):
            raise ValueError(f'{label}: expected an object')
        for key,default in template.items():
            if key not in value:
                raise ValueError(f'{label}: missing {key}')
            item=value[key]
            if isinstance(default,bool):
                valid=isinstance(item,bool)
            elif isinstance(default,(int,float)):
                valid=isinstance(item,(int,float)) and not isinstance(item,bool)
            else:
                valid=isinstance(item,type(default))
            if not valid:
                raise ValueError(f'{label}: invalid {key} type')
            if isinstance(default,dict):
                fields(item,default,label+'.'+key)
    if not isinstance(project.name,str) or not isinstance(project.objects,list) or not isinstance(project.rules,list):
        raise ValueError('Project name, objects, or rules have invalid types')
    if not isinstance(project.scenarios,dict) or not isinstance(project.results,list):
        raise ValueError('Project scenarios or history have invalid types')
    fields(project.settings,Project().settings,'Run settings')
    for obj in project.objects:
        if not isinstance(obj,dict) or obj.get('kind') not in ('room','path','door','sensor','entrance','exit'):
            raise ValueError('Unknown or malformed layout object')
        template=new_object(obj['kind'])
        if obj['kind']=='door':
            template.pop('path')  # Legacy projects migrate this field after structural checks.
        fields(obj,template,obj.get('name','Object'))
        if not obj['id']:
            raise ValueError('Objects must have nonempty IDs')
        if obj['kind']=='path':
            for point in obj['points']:
                if not isinstance(point,(list,tuple)) or len(point)!=2 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) for v in point):
                    raise ValueError(f"{obj['name']}: path coordinates must be numeric pairs")
    rule_template=dict(id='',name='',enabled=True,event='',source='',action='',target='',delay=0.)
    for rule in project.rules:
        fields(rule,rule_template,'Rule')
        fields(rule,{k:v for k,v in dict(condition='always',condition_target='',wait_for_condition=False).items() if k in rule},'Rule')
        if not rule['id']:
            raise ValueError('Rules must have nonempty IDs')
    for name,override in project.scenarios.items():
        if not isinstance(name,str) or not isinstance(override,dict):
            raise ValueError('Malformed scenario')
        if not isinstance(override.get('objects',{}),dict) or not isinstance(override.get('settings',{}),dict) or not isinstance(override.get('rules',[]),list):
            raise ValueError(f'{name}: malformed scenario overrides')


def example():
    p = Project(name='Example • three scenes')
    nodes = [new_object(k, 70+i*220, 200) for i, k in enumerate(
        ['entrance', 'room', 'room', 'room', 'exit'])]
    for i, n in enumerate(nodes[1:4]):
        n['name'] = f'Room {chr(65+i)}'
        n['duration'] = timing([20, 27, 18][i])
        n['preferred'] = n['duration']['typical']
    paths = []
    for a, b in zip(nodes, nodes[1:]):
        path = new_object('path', points=[[a['x'], a['y']], [b['x'], b['y']]])
        path.update(name=f"{a['name']} → {b['name']}", source=a['id'], target=b['id'])
        paths.append(path)
    sensor = new_object('sensor', 420, 200)
    sensor.update(path=paths[1]['id'], name='First scene exit', fraction=.6)
    door = new_object('door', 475, 200)
    door['path'] = paths[1]['id']
    p.objects = nodes + paths + [sensor, door]
    p.rules = [dict(id=uid(), name='Release next group', enabled=True,
                    event='sensor_crossed', source=sensor['id'], condition='always',
                    condition_target='', wait_for_condition=True,
                    action='admit', target=nodes[0]['id'], delay=0.)]
    return p
