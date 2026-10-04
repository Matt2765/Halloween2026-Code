"""Cancellable repeated runs and bounded coordinate-search timing advice."""
from copy import deepcopy
from collections import Counter
from statistics import mean, median
import math
from .engine import Engine
from .analytics import summarize


def percentile(values, q):
    values = sorted(values)
    if not 0<=q<=1:
        raise ValueError('Percentile must be between zero and one')
    if not values:
        return 0
    at=(len(values)-1)*q
    low,high=math.floor(at),math.ceil(at)
    return values[low]+(values[high]-values[low])*(at-low)


def repeated(project, count, cancel=lambda:False, progress=lambda n,t:None):
    results = []
    for i in range(count):
        if cancel():
            break
        e = Engine(project, seed=project.settings['seed']+i).run(cancel)
        if cancel():
            break
        results.append(summarize(e))
        progress(i+1,count)
    if not results:
        return dict(runs=0)
    gph = [r['metrics']['groups_per_hour'] for r in results]
    vph = [r['metrics']['guests_per_hour'] for r in results]
    causes = Counter(v['cause'] for r in results for v in r['failures'])
    return dict(runs=len(results), first_seed=project.settings['seed'],
        mean_groups_per_hour=mean(gph), median_groups_per_hour=median(gph),
        p05_groups_per_hour=percentile(gph,.05), p95_groups_per_hour=percentile(gph,.95),
        mean_guests_per_hour=mean(vph), p05_guests_per_hour=percentile(vph,.05), p95_guests_per_hour=percentile(vph,.95),
        failure_probability=mean(r['metrics']['interior_failures']>0 for r in results),
        average_blockages=mean(r['metrics']['interior_failures'] for r in results),
        recurring_causes=dict(causes.most_common(5)),
        room_utilization={rid:dict(mean=mean(r['rooms'][rid]['utilization'] for r in results),
                            p05=percentile([r['rooms'][rid]['utilization'] for r in results],.05),
                            p95=percentile([r['rooms'][rid]['utilization'] for r in results],.95)) for rid in results[0]['rooms']})


def advise(project, cancel=lambda:False, progress=lambda n,t:None):
    working = deepcopy(project)
    rooms = [o for o in working.objects if o['kind']=='room' and o['enabled']]
    def evaluate(p):
        runs = [summarize(Engine(p, seed=p.settings['seed']+i).run(cancel)) for i in range(3) if not cancel()]
        if not runs:
            return None, None
        metrics = {k:mean(r['metrics'][k] for r in runs) for k in runs[0]['metrics']}
        deviation = sum(abs(o['duration']['typical']-o['preferred'])/max(1,o['preferred']) for o in p.objects if o['kind']=='room')
        # Safety dominates; throughput receives a show-quality penalty, avoiding minimum-everywhere advice.
        score = (metrics['interior_failures'], metrics['interior_blocked_seconds'],
                 -metrics['guests_per_hour']/(1+.35*deviation) + .02*metrics['overstay_seconds'])
        return score, metrics
    best, base = evaluate(working)
    baseline = deepcopy(base)
    tested = 0
    for sweep in range(2):
        for room in rooms:
            original = deepcopy(room['duration'])
            selected = original
            candidates = sorted(set([room['acceptable_min'], room['preferred'], room['acceptable_max'],
                max(room['acceptable_min'],original['typical']-2), min(room['acceptable_max'],original['typical']+2)]))
            for value in candidates:
                if cancel():
                    break
                delta = value-original['typical']
                room['duration'] = {k:max(room['acceptable_min'],min(room['acceptable_max'],v+delta)) for k,v in original.items()}
                score, metrics = evaluate(working)
                tested += 1
                progress(tested,max(tested,len(rooms)*10))
                if score is not None and score < best:
                    best, base, selected = score, metrics, deepcopy(room['duration'])
            room['duration'] = selected
            if cancel():
                break
        if cancel():
            break
    return dict(baseline=baseline, suggested=base, tested=tested,
        overrides={o['id']:dict(duration=o['duration']) for o in rooms},
        explanation='Bounded coordinate search using three common seeds per candidate. Interior failures and blocked time '
                    'take priority; throughput is discounted for deviation from preferred scene lengths. '
                    'This is a local recommendation, not a proof of a global optimum. Validate with repeated runs.')
