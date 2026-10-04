"""Deterministic discrete-event flow engine. No Qt, IO, or hardware dependencies."""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
import heapq
import math
import random
import secrets
from .model import sample, travel, interpolate, door_path_fraction, length
from .validation import validate


@dataclass
class Group:
    id: int
    guests: int
    speed: float
    admitted: float
    location: str
    state: str = 'walking'
    start: float = 0.
    end: float = 0.
    completed: float | None = None
    scene_start: float = 0.
    intended: float = 0.
    ready: float = 0.
    chosen: str = ''
    blocked_since: float | None = None
    cause: str = ''
    walking: float = 0.
    scenes: float = 0.
    blocked: float = 0.
    path_entered_at: float = 0.
    path_fraction: float = 0.
    path_from: float = 0.
    path_to: float = 0.
    movement_token: int = 0
    passed_doors: set = field(default_factory=set)
    passed_sensors: set = field(default_factory=set)


class Engine:
    def __init__(self, project, seed=None, check=True):
        if check:
            errors, _ = validate(project)
            if errors:
                raise ValueError('\n'.join(errors))
        self.project = deepcopy(project)
        self.project.migrate_legacy_doors()
        self.objects = self.project.by_id()
        self.seed = seed if seed is not None else (secrets.randbits(32) if project.settings['random_seed'] else project.settings['seed'])
        self.rng = random.Random(self.seed)
        self.now = 0.
        self.queue, self.serial, self.groups = [], 0, {}
        self.log, self.failures, self.overstays, self.spacing, self.latencies = [], [], [], [], []
        self.room_visits, self.path_visits = [], []
        self.occupants = defaultdict(set)
        self.paths = defaultdict(set)
        self.sensor_last = defaultdict(lambda: -float('inf'))
        self.sensor_counts, self.door_cycles = defaultdict(int), defaultdict(int)
        self.doors = {o['id']: dict(state='closed', start=0., end=0., fraction=0., target=0., token=0, active=0.)
                      for o in project.objects if o['kind']=='door'}
        self.series = []
        self.pending = None
        self.pending_rules = {}
        self.signals = self.blocked_signals = self.coalesced_signals = 0
        self.max_groups = self.max_guests = 0
        self.stopped = False
        self.reason = ''
        self.entrance = next(o['id'] for o in project.objects if o['kind']=='entrance' and o['enabled'])
        self.schedule(0, 'start')

    def schedule(self, delay, kind, *args):
        self.serial += 1
        heapq.heappush(self.queue, (self.now + max(0., delay), self.serial, kind, args))

    def emit(self, event, source='', group=0, detail=''):
        if len(self.log) < 100_000:
            self.log.append(dict(time=self.now, event=event, source=source, group=group, detail=detail))
        for rule in self.project.rules:
            if not rule['enabled'] or rule['event'] != event or (rule['source'] and rule['source'] != source):
                continue
            if self.condition_met(rule):
                self.schedule(rule['delay'], 'action', rule['action'], rule['target'], group)
            elif rule.get('wait_for_condition',False) and rule.get('condition','always')!='always':
                if rule['id'] not in self.pending_rules:
                    self.pending_rules[rule['id']]=dict(rule=rule,group=group,event=event,
                                                        source=source,started=self.now)
                    self.log_rule('rule_waiting',rule,group,
                                  f"Waiting for {rule['condition']} on {rule.get('condition_target','')}")
                else:
                    self.log_rule('rule_wait_coalesced',rule,group,'A condition wait is already pending')

    def condition_met(self,rule):
        kind=rule.get('condition','always')
        target=rule.get('condition_target','')
        obj=self.objects.get(target)
        if kind=='always':
            return True
        if kind in ('room_available','room_empty','room_occupied'):
            if not obj or obj['kind']!='room' or not obj['enabled']:
                return False
            count=len(self.occupants[target])
            return (count<obj['capacity'] if kind=='room_available' else
                    count==0 if kind=='room_empty' else count>0)
        if kind=='path_clear':
            return bool(obj and obj['kind']=='path' and obj['enabled'] and not self.paths[target])
        if kind in ('door_open','door_closed'):
            expected='open' if kind=='door_open' else 'closed'
            return bool(obj and obj['kind']=='door' and obj['enabled'] and
                        self.doors.get(target,{}).get('state')==expected)
        if kind in ('enabled','disabled'):
            entity=obj or next((r for r in self.project.rules if r['id']==target),None)
            return bool(entity and bool(entity['enabled'])==(kind=='enabled'))
        return False

    def log_rule(self,event,rule,group,detail):
        if len(self.log)<100_000:
            self.log.append(dict(time=self.now,event=event,source=rule['id'],group=group,detail=detail))

    def reevaluate_pending_rules(self):
        """Resolve remembered events after state changes, without timer polling."""
        for rid,pending in list(self.pending_rules.items()):
            rule=pending['rule']
            if not rule['enabled']:
                del self.pending_rules[rid]
            elif self.condition_met(rule):
                del self.pending_rules[rid]
                self.log_rule('rule_condition_met',rule,pending['group'],
                              f"Condition became true after {self.now-pending['started']:.3f}s")
                self.schedule(rule['delay'],'action',rule['action'],rule['target'],pending['group'])

    def release(self):
        if self.stopped:
            return
        self.signals += 1
        if self.pending is not None:
            self.coalesced_signals += 1
            self.blocked_signals += 1
            self.emit('release_coalesced', self.entrance, detail='One release is already pending')
        else:
            self.pending = self.now
            if not self.admit():
                self.blocked_signals += 1

    def choose_path(self, node):
        options = [o for o in self.objects.values() if o['kind']=='path' and o['enabled'] and o['source']==node]
        return self.rng.choices(options, weights=[o['weight'] for o in options])[0] if options else None

    def admit(self):
        if self.pending is None:
            return False
        maximum = self.project.settings['exterior_groups']
        if maximum and len(self.groups) >= maximum:
            self.pending = None
            return False
        # Keep a chosen branch stable while waiting, avoiding random re-routing.
        if not hasattr(self, 'entry_path') or self.entry_path is None:
            self.entry_path = self.choose_path(self.entrance)
        path = self.entry_path
        if not path or self.paths[path['id']]:
            return False
        # A door drawn directly on the entrance threshold still gates admission.
        for door,fraction in self.path_doors(path):
            if fraction<=.001 and not self.door_available(door['id']):
                return False
        gid = len(self.groups)+1
        g = Group(gid, max(1, int(sample(self.project.settings['group_size'], self.rng)+.5)),
                  sample(self.project.settings['speed'], self.rng), self.now, self.entrance)
        self.groups[gid] = g
        self.latencies.append(dict(signal=self.pending, admission=self.now, latency=self.now-self.pending))
        self.pending = None
        self.entry_path = None
        self.emit('haunt_entered', self.entrance, gid)
        self.enter_path(g, path)
        return True

    def door_available(self, did):
        obj = self.objects[did]
        if obj['style']=='passage':
            return True
        if not obj['enabled']:
            return False
        state = self.doors[did]['state']
        if state == 'open':
            return True
        if obj['automatic'] and state == 'closed':
            self.door(did, True)
        return False

    def door_fraction(self, did, at=None):
        d = self.doors[did]
        at = self.now if at is None else at
        ratio = 1 if d['end'] <= d['start'] else min(1., max(0., (at-d['start'])/(d['end']-d['start'])))
        return d['fraction'] + (d['target']-d['fraction'])*ratio

    def path_doors(self,path):
        result=[]
        for door in self.objects.values():
            if door['kind']=='door' and door.get('path')==path['id']:
                result.append((door,door_path_fraction(path,door)))
        return sorted(result,key=lambda row:(row[1],row[0]['id']))

    def door(self, did, opening):
        if did not in self.doors or not self.objects[did]['enabled']:
            return
        d, obj = self.doors[did], self.objects[did]
        state = 'opening' if opening else 'closing'
        if d['state'] in ((state, 'open') if opening else (state, 'closed')):
            return
        fraction = self.door_fraction(did)
        duration = obj['opening' if opening else 'closing'] * abs((1 if opening else 0)-fraction)
        if d['state'] != 'closed':
            d['active'] += self.now - d['start']
        d.update(state=state, start=self.now, end=self.now+duration, fraction=fraction,
                 target=1. if opening else 0., token=d['token']+1)
        if opening:
            self.door_cycles[did] += 1
        self.emit('door_'+state, did)
        self.schedule(duration, 'door_done', did, opening, d['token'])

    def enter_path(self, g, path):
        self.clear_block(g)
        g.location, g.state = path['id'], 'walking'
        g.path_entered_at=self.now
        g.path_fraction=g.path_from=g.path_to=0.
        g.passed_doors=set()
        g.passed_sensors=set()
        g.chosen = ''
        self.paths[path['id']].add(g.id)
        self.emit('path_entered', path['id'], g.id)
        self.continue_path(g)

    def continue_path(self,g):
        path=self.objects[g.location]
        current=g.path_fraction
        sensors=[(s['fraction'],s['id'],'sensor') for s in self.objects.values()
                 if s['kind']=='sensor' and s['enabled'] and s['path']==path['id'] and
                 s['id'] not in g.passed_sensors and s['fraction']>=current-1e-9]
        doors=[(fraction,d['id'],'door') for d,fraction in self.path_doors(path)
               if d['id'] not in g.passed_doors and fraction>=current-1e-9]
        fraction=min([v[0] for v in sensors+doors]+[1.])
        duration=travel(path,self.project,g.speed)*max(0.,fraction-current)
        g.path_from,g.path_to=current,fraction
        g.state,g.start,g.end='walking',self.now,self.now+duration
        g.movement_token+=1
        self.check_spacing(g,path)
        self.schedule(duration,'path_milestone',g.id,g.movement_token)

    def path_milestone(self,g):
        path=self.objects[g.location]
        g.walking+=max(0.,self.now-g.start)
        g.path_fraction=g.path_to
        for sensor in self.objects.values():
            if (sensor['kind']=='sensor' and sensor['enabled'] and sensor['path']==path['id'] and
                    sensor['id'] not in g.passed_sensors and abs(sensor['fraction']-g.path_fraction)<1e-7):
                g.passed_sensors.add(sensor['id'])
                if self.now-self.sensor_last[sensor['id']] >= sensor['cooldown']:
                    self.sensor_last[sensor['id']]=self.now
                    self.sensor_counts[sensor['id']]+=1
                    self.emit('sensor_crossed',sensor['id'],g.id)
        blocked=None
        for door,fraction in self.path_doors(path):
            if door['id'] not in g.passed_doors and abs(fraction-g.path_fraction)<1e-7:
                if self.door_available(door['id']):
                    g.passed_doors.add(door['id'])
                else:
                    blocked=door['id']
                    break
        if blocked:
            g.end=self.now
            self.block(g,blocked)
        elif g.path_fraction>=1.-1e-9:
            self.arrive(g)
        else:
            self.continue_path(g)

    def check_spacing(self, g, path):
        """Exact closest approach of piecewise-linear trajectories on shared map geometry.

        Each path has one moving group at a time; crossing or overlapping distinct
        paths can still produce unsafe spacing. No corrective navigation is invented.
        """
        for other in self.groups.values():
            if other.id==g.id or other.state not in ('walking','blocked'):
                continue
            route=self.objects[other.location]
            if route['kind']!='path':
                continue
            threshold=max(path['spacing'],route['spacing'])
            lo,hi=self.now,(g.end if other.state=='blocked' else min(g.end,other.end))
            if hi<=lo or threshold<=0:
                continue
            # Split at every route corner: velocity is constant only between corners.
            breaks={lo,hi}
            for moving,route_obj in ((g,path),(other,route)):
                if moving.state!='walking' or moving.path_to<=moving.path_from:
                    continue
                total=length(route_obj['points'])
                traversed=0.
                for a,b in zip(route_obj['points'],route_obj['points'][1:]):
                    traversed+=math.dist(a,b)
                    fraction=traversed/total
                    at=moving.start+(moving.end-moving.start)*(fraction-moving.path_from)/(moving.path_to-moving.path_from)
                    if lo<at<hi:
                        breaks.add(at)
            closest=(float('inf'),lo)
            ordered=sorted(breaks)
            for start,end in zip(ordered,ordered[1:]):
                a,b=self.position(g,start),self.position(other,start)
                c,d=self.position(g,end),self.position(other,end)
                delta=(a[0]-b[0],a[1]-b[1])
                velocity=(c[0]-d[0]-delta[0],c[1]-d[1]-delta[1])
                norm=sum(v*v for v in velocity)
                ratio=max(0.,min(1.,-sum(delta[i]*velocity[i] for i in (0,1))/norm)) if norm else 0
                distance=sum((delta[i]+velocity[i]*ratio)**2 for i in (0,1))**.5
                closest=min(closest,(distance,start+(end-start)*ratio))
            distance,at=closest
            if distance<threshold:
                self.spacing.append(dict(group=g.id,other=other.id,location=path['id'],
                    time=at,distance=distance))
                self.emit('spacing_conflict',path['id'],g.id,f'Predicted proximity to group {other.id}: {distance:.2f} pixels')

    def block(self, g, cause, room=False):
        if g.blocked_since is None:
            g.blocked_since = self.now
            g.cause = cause
            g.state = 'overstay' if room else 'blocked'
            self.emit('room_overstay' if room else 'flow_failure', g.location, g.id, cause)

    def clear_block(self, g):
        if g.blocked_since is None:
            return
        duration = self.now-g.blocked_since
        record = dict(group=g.id, location=g.location, start=g.blocked_since, end=self.now,
                      duration=duration, cause=g.cause)
        (self.overstays if g.state=='overstay' else self.failures).append(record)
        g.blocked += duration
        g.blocked_since = None
        g.cause = ''

    def leave_room(self, g):
        room = self.objects[g.location]
        if not g.chosen:
            path = self.choose_path(room['id'])
            if not path:
                self.block(g, 'No enabled outgoing path', True)
                return False
            g.chosen = path['id']
        path = self.objects[g.chosen]
        if not path['enabled'] or self.paths[path['id']]:
            self.block(g, path['id'], True)
            return False
        self.clear_block(g)
        self.room_visits.append(dict(group=g.id, room=room['id'], start=g.scene_start,
                                     end=self.now, intended=g.intended, actual=self.now-g.scene_start))
        self.occupants[room['id']].discard(g.id)
        self.emit('room_exited', room['id'], g.id)
        self.enter_path(g, path)
        return True

    def arrive(self, g):
        path = self.objects[g.location]
        target = self.objects[path['target']]
        if not target['enabled'] or (target['kind']=='room' and len(self.occupants[target['id']]) >= target['capacity']):
            self.block(g, target['id'])
            return False
        self.clear_block(g)
        self.path_visits.append(dict(group=g.id,path=path['id'],travel=travel(path,self.project,g.speed),
                                     actual=self.now-g.path_entered_at))
        self.paths[path['id']].discard(g.id)
        self.emit('path_exited', path['id'], g.id)
        self.emit('location_reached', target['id'], g.id)
        g.location = target['id']
        if target['kind']=='exit':
            g.state, g.completed = 'completed', self.now
            self.emit('haunt_exited', target['id'], g.id)
        else:
            self.occupants[target['id']].add(g.id)
            g.state, g.scene_start = 'scene', self.now
            g.intended = sample(target['duration'], self.rng)
            g.ready = self.now+g.intended
            self.emit('room_entered', target['id'], g.id)
            self.schedule(g.intended, 'room_done', g.id)
        return True

    def retry(self):
        # State changes, rather than polling timers, wake blocked groups in FIFO order.
        changed=True
        while changed:
            changed=False
            for g in self.groups.values():
                if g.state=='blocked':
                    if self.objects[g.location]['kind']=='path' and g.cause in self.doors:
                        # Resume only when the door that stopped this group is fully open.
                        # Other events must not repeatedly clear/recreate the same failure.
                        if g.cause in self.doors and self.door_available(g.cause):
                            self.clear_block(g)
                            self.continue_path(g)
                            changed=True
                    else:
                        changed=self.arrive(g) or changed
                elif g.state=='overstay':
                    changed=self.leave_room(g) or changed
        self.admit()

    def step(self):
        if self.stopped:
            return False
        settings=self.project.settings
        if not self.queue:
            if settings['stop']=='time':
                self.now=settings['duration']
                self.stopped,self.reason=True,'Duration reached (no pending events)'
            return False
        if settings['stop']=='time' and self.queue[0][0]>settings['duration']:
            self.now=settings['duration']
            self.stopped,self.reason=True,'Duration reached'
            return False
        at, _, kind, args = heapq.heappop(self.queue)
        self.now = at
        if kind=='start':
            self.emit('simulation_started')
            if self.project.settings['initial_release']:
                self.release()
        elif kind=='action':
            action, target, gid = args
            if action=='admit':
                self.release()
            elif action in ('open_door', 'close_door'):
                self.door(target, action=='open_door')
            elif action in ('enable', 'disable'):
                for obj in list(self.objects.values())+self.project.rules:
                    if obj['id']==target:
                        obj['enabled'] = action=='enable'
            elif action=='signal':
                self.emit('custom_signal', target, gid)
        elif kind=='path_milestone':
            gid,token=args
            g=self.groups[gid]
            if token==g.movement_token and g.state=='walking':
                self.path_milestone(g)
        elif kind=='arrive':
            self.arrive(self.groups[args[0]])
        elif kind=='room_done':
            g = self.groups[args[0]]
            g.scenes += g.intended
            self.emit('room_completed', g.location, g.id)
            self.leave_room(g)
        elif kind=='door_done':
            did, opening, token = args
            d, obj = self.doors[did], self.objects[did]
            if token==d['token']:
                d['active'] += self.now-d['start']
                d.update(state='open' if opening else 'closed', start=self.now,
                         end=self.now, fraction=float(opening), target=float(opening))
                self.emit('door_opened' if opening else 'door_closed', did)
                if opening and obj['automatic']:
                    self.schedule(max(.001, obj['hold']), 'auto_close', did, token)
        elif kind=='auto_close':
            did, token = args
            if self.doors[did]['token']==token:
                self.door(did, False)
        self.retry()
        self.reevaluate_pending_rules()
        active = [g for g in self.groups.values() if g.completed is None]
        guests = sum(g.guests for g in active)
        completed = [g for g in self.groups.values() if g.completed is not None]
        self.max_groups, self.max_guests = max(self.max_groups,len(active)), max(self.max_guests,guests)
        point = [self.now, len(active), guests, len(completed), sum(g.guests for g in completed)]
        if not self.series or self.series[-1][1:] != point[1:]:
            self.series.append(point)
        settings = self.project.settings
        if settings['stop']=='groups' and len(completed)>=settings['limit'] or settings['stop']=='guests' and point[4]>=settings['limit']:
            self.stopped, self.reason = True, 'Completion target reached'
        return True

    def advance(self, until, budget=20000):
        if not math.isfinite(until) or until<self.now:
            raise ValueError('Simulation time must be finite and cannot move backwards')
        settings=self.project.settings
        if settings['stop']=='time':
            until=min(until,settings['duration'])
        count = 0
        while self.queue and self.queue[0][0] <= until and not self.stopped and count < budget:
            self.step()
            count += 1
        if count < budget and not self.stopped:
            self.now = until
            if settings['stop']=='time' and self.now>=settings['duration']:
                self.stopped,self.reason=True,'Duration reached'
        if count == budget and self.queue and self.queue[0][0] <= self.now:
            raise ValueError('Runaway simultaneous events: inspect signal cycles / zero durations')
        return count

    def run(self, cancel=lambda: False):
        settings = self.project.settings
        horizon = settings['duration']
        events = 0
        same_time, last = 0, -1
        while self.queue and not self.stopped and not cancel():
            if settings['stop']=='time' and self.queue[0][0] > horizon:
                self.now = horizon
                break
            self.step()
            events += 1
            same_time = same_time+1 if self.now==last else 0
            last = self.now
            if same_time > 10000:
                raise ValueError('Runaway signal cycle at one simulated instant')
            if events > 2_000_000:
                raise ValueError('Event limit reached; use a shorter run or inspect control rules')
        if cancel():
            self.reason = 'Cancelled'
        elif not self.queue and not self.stopped:
            self.reason = 'No pending events: exterior exhausted, waiting for manual release, or deadlock'
            if settings['stop']=='time':
                self.now = horizon
        else:
            self.reason = self.reason or 'Duration reached'
        self.stopped=True
        return self

    def position(self, g, at=None):
        at = self.now if at is None else at
        obj = self.objects[g.location]
        if obj['kind']=='path':
            if g.state=='walking':
                ratio=1 if g.end<=g.start else max(0.,min(1.,(at-g.start)/(g.end-g.start)))
                fraction=g.path_from+(g.path_to-g.path_from)*ratio
            else:
                fraction=g.path_fraction
            return interpolate(obj['points'],fraction)
        return obj['x'], obj['y']
