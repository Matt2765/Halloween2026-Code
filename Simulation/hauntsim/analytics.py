"""Run summaries, occupancy integration, CSV export, and cautious diagnostics."""
from collections import Counter
from datetime import datetime, timezone
from statistics import mean, median
import csv
import json


def average(values):
    return mean(values) if values else 0.


def summarize(e, scenario='Base'):
    done = [g for g in e.groups.values() if g.completed is not None]
    times = [g.completed-g.admitted for g in done]
    duration = max(e.now, .000001)
    spacing = [v for v in e.spacing if v['time'] <= e.now]
    failures, overstays = list(e.failures), list(e.overstays)
    visits = list(e.room_visits)
    for g in e.groups.values():
        if g.blocked_since is not None:
            record = dict(group=g.id, location=g.location, start=g.blocked_since, end=e.now,
                          duration=e.now-g.blocked_since, cause=g.cause, ongoing=True)
            (overstays if g.state=='overstay' else failures).append(record)
        if g.state in ('scene', 'overstay'):
            visits.append(dict(group=g.id, room=g.location, start=g.scene_start, end=e.now,
                               intended=g.intended, actual=e.now-g.scene_start, ongoing=True))
    rooms = {}
    explanations = []
    for obj in e.objects.values():
        if obj['kind']!='room':
            continue
        records = [v for v in visits if v['room']==obj['id']]
        delays = [v for v in overstays if v['location']==obj['id']]
        causes = [v for v in failures if v['cause']==obj['id']]
        utilization = sum(v['actual'] for v in records)/duration/obj['capacity']
        rooms[obj['id']] = dict(name=obj['name'], utilization=utilization,
            visits=len(records), intended=average([v['intended'] for v in records]),
            actual=average([v['actual'] for v in records]), overstays=len(delays),
            overstay_seconds=sum(v['duration'] for v in delays), caused_failures=len(causes))
        explanations.append(f"{obj['name']}: {utilization:.0%} capacity utilization; {len(causes)} blocks at its entrance, "
                            f"{len(delays)} overstays. " +
                            ('Low utilization may reflect upstream timing or insufficient admission.' if utilization < .5 else
                             'Review downstream availability and release timing together.' if delays or causes else
                             'No observed blockage attributed to this room.'))
    guests = sum(g.guests for g in done)
    metrics = dict(duration=e.now, groups_admitted=len(e.groups), groups_completed=len(done),
        guests_admitted=sum(g.guests for g in e.groups.values()), guests_completed=guests,
        groups_per_hour=len(done)*3600/duration, guests_per_hour=guests*3600/duration,
        traversal_average=average(times), traversal_median=median(times) if times else 0,
        traversal_min=min(times, default=0), traversal_max=max(times, default=0),
        current_groups=len(e.groups)-len(done), current_guests=sum(g.guests for g in e.groups.values() if g.completed is None),
        max_groups=e.max_groups, max_guests=e.max_guests,
        room_overstays=len(overstays), overstay_seconds=sum(v['duration'] for v in overstays),
        interior_failures=len(failures), interior_blocked_seconds=sum(v['duration'] for v in failures),
        longest_blockage=max((v['duration'] for v in failures), default=0), spacing_conflicts=len(spacing),
        release_signals=e.signals, blocked_signals=e.blocked_signals, coalesced_signals=e.coalesced_signals,
        release_latency=average([v['latency'] for v in e.latencies]),
        pending_release_seconds=e.now-e.pending if e.pending is not None else 0,
        walking_seconds=sum(g.walking + (max(0,min(e.now,g.end)-g.start) if g.state=='walking' else 0) for g in e.groups.values()),
        scene_seconds=sum(g.scenes + (min(e.now,g.ready)-g.scene_start if g.state=='scene' else 0) for g in e.groups.values()),
        blocked_seconds=sum(v['duration'] for v in failures+overstays))
    windows = {}
    for minutes in (5,10,15,30):
        width = minutes*60
        buckets = []
        for start in range(0, max(1,int(e.now)+1), width):
            rows = [g for g in done if start <= g.completed < start+width]
            buckets.append(dict(start=start, groups=len(rows), guests=sum(g.guests for g in rows)))
        windows[str(minutes)] = buckets
    if e.blocked_signals:
        explanations.append(f'{e.blocked_signals} release signals were entrance-constrained; '
                            f'{e.coalesced_signals} merged into the single pending release. '
                            f'Mean honored release latency: {metrics["release_latency"]:.1f}s.')
    if failures:
        for (location, cause), count in Counter((v['location'],v['cause']) for v in failures).most_common(5):
            total = sum(v['duration'] for v in failures if (v['location'],v['cause'])==(location,cause))
            explanations.append(f"{e.objects.get(location,{}).get('name',location)}: {count} flow failures, {total:.1f}s blocked by "
                                f"{e.objects.get(cause,{}).get('name',cause)}.")
    return dict(project=e.project.name, scenario=scenario, timestamp=datetime.now(timezone.utc).isoformat(),
        seed=e.seed, settings=e.project.settings, configuration=e.project.data() | {'results': [], 'scenarios': {}},
        metrics=metrics, rooms=rooms, failures=failures, overstays=overstays, spacing=spacing,
        doors={did: dict(cycles=e.door_cycles[did], utilization=(d['active']+(e.now-d['start'] if d['state']!='closed' else 0))/duration)
               for did,d in e.doors.items()}, sensors=dict(e.sensor_counts), windows=windows,
        latencies=e.latencies, paths=e.path_visits, series=e.series,
        explanations=explanations, termination=e.reason)


def compact(result):
    """Bound retained history; full results remain exportable for the current run."""
    return {k:v for k,v in result.items() if k not in ('configuration','failures','overstays','spacing','latencies','paths','series','windows')}


def export_csv(result, filename):
    with open(filename, 'w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['section', 'entity', 'metric', 'value'])
        for key in ('project','scenario','timestamp','seed','termination'):
            writer.writerow(['context','',key,result.get(key,'')])
        for key,value in result['metrics'].items():
            writer.writerow(['summary','',key,value])
        for section in ('rooms','doors','sensors','windows'):
            for entity, values in result.get(section,{}).items():
                if isinstance(values,dict):
                    for k,v in values.items():
                        writer.writerow([section,entity,k,v])
                else:
                    writer.writerow([section,entity,'data',json.dumps(values)])
        for section in ('failures','overstays','spacing','latencies','paths','series'):
            for i,row in enumerate(result.get(section,[])):
                writer.writerow([section,i,'record',json.dumps(row)])
