"""Independent arithmetic, boundary, geometry and generated-state audit checks."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import random
import tempfile
import unittest
from hauntsim.model import Project, new_object, uid, timing, example
from hauntsim.engine import Engine, Group
from hauntsim.analytics import summarize
from hauntsim.validation import validate
from hauntsim.analysis_jobs import percentile


def simple(duration=60):
    p=Project(name='Hand calculated')
    entry=new_object('entrance',0,0)
    room=new_object('room',10,0)
    room['duration']=timing(10)
    exit=new_object('exit',20,0)
    paths=[]
    for a,b in ((entry,room),(room,exit)):
        path=new_object('path',points=[[a['x'],0],[b['x'],0]])
        path.update(source=a['id'],target=b['id'],seconds=0)
        paths.append(path)
    p.objects=[entry,room,exit]+paths
    p.settings.update(duration=duration,pixels_per_unit=1,speed=timing(2),exterior_groups=1)
    p.rules=[dict(id=uid(),name='Later release',enabled=True,event='haunt_entered',source=entry['id'],
                  action='admit',target=entry['id'],delay=1000)]
    return p


class AccuracyAudit(unittest.TestCase):
    def test_percentiles_interpolate_small_samples(self):
        self.assertEqual(percentile([0,100],.05),5)
        self.assertEqual(percentile([0,100],.95),95)
        self.assertEqual(percentile([10],.95),10)
        self.assertEqual(percentile([0,50,100],.5),50)

    def test_hand_calculated_complete_journey(self):
        e=Engine(simple()).run()
        r=summarize(e)
        m=r['metrics']
        self.assertEqual((m['duration'],m['groups_completed'],m['guests_completed']),(60,1,4))
        self.assertEqual((m['walking_seconds'],m['scene_seconds'],m['blocked_seconds']),(10,10,0))
        self.assertEqual(m['traversal_average'],20)
        self.assertEqual(m['groups_per_hour'],60)
        self.assertEqual(m['guests_per_hour'],240)
        self.assertAlmostEqual(next(iter(r['rooms'].values()))['utilization'],1/6)

    def test_hand_calculated_partial_journey(self):
        r=summarize(Engine(simple(8)).run())
        self.assertEqual(r['metrics']['groups_completed'],0)
        self.assertEqual(r['metrics']['walking_seconds'],5)
        self.assertEqual(r['metrics']['scene_seconds'],3)
        self.assertAlmostEqual(next(iter(r['rooms'].values()))['utilization'],3/8)

    def test_hand_calculated_saturated_pipeline(self):
        p=simple(60)
        p.settings['exterior_groups']=0
        room=next(o for o in p.objects if o['kind']=='room')
        p.rules[0].update(event='room_completed',source=room['id'],delay=0)
        e=Engine(p).run()
        self.assertEqual([g.completed for g in e.groups.values() if g.completed is not None],[20,35,50])
        m=summarize(e)['metrics']
        self.assertEqual((m['groups_admitted'],m['groups_completed'],m['groups_per_hour']),(5,3,180))
        self.assertEqual((m['walking_seconds'],m['scene_seconds'],m['blocked_seconds']),(35,40,0))

    def test_hand_calculated_downstream_blockage(self):
        p=simple(40)
        p.settings['exterior_groups']=2
        p.rules[0]['delay']=5
        e=Engine(p).run()
        m=summarize(e)['metrics']
        self.assertEqual([g.completed for g in e.groups.values()],[20,30])
        self.assertEqual((m['walking_seconds'],m['scene_seconds'],m['blocked_seconds']),(20,20,5))
        self.assertEqual(m['interior_failures'],1)
        self.assertEqual(m['longest_blockage'],5)

    def test_all_run_modes_respect_time_boundary(self):
        p=simple(8)
        fast=Engine(p).run()
        visual=Engine(p)
        visual.advance(100)
        stepped=Engine(p)
        while stepped.step():
            pass
        self.assertEqual(fast.now,8)
        self.assertEqual(visual.now,8)
        self.assertEqual(stepped.now,8)
        self.assertEqual(fast.log,visual.log)
        self.assertEqual(fast.log,stepped.log)
        for e in (fast,visual,stepped):
            count=len(e.groups)
            e.release()
            self.assertEqual(len(e.groups),count)

    def test_time_cannot_move_backwards(self):
        e=Engine(simple())
        e.advance(8)
        with self.assertRaises(ValueError):
            e.advance(4)

    def test_final_completion_belongs_to_final_window(self):
        p=simple(300)
        next(o for o in p.objects if o['kind']=='room')['duration']=timing(290)
        r=summarize(Engine(p).run())
        self.assertEqual(r['metrics']['groups_completed'],1)
        self.assertEqual(r['windows']['5'],[dict(start=0,end=300,groups=1,guests=4)])
        self.assertEqual(r['series'][-1][0],300)

    def test_report_does_not_alias_engine_state(self):
        e=Engine(simple()).run()
        r=summarize(e)
        r['settings']['duration']=999
        r['series'][0][1]=999
        self.assertEqual(e.project.settings['duration'],60)
        self.assertNotEqual(e.series[0][1],999)

    def spacing_case(self,stationary):
        p=simple()
        routes=[o for o in p.objects if o['kind']=='path']
        routes[0].update(points=[[0,0],[0,10],[10,10]],seconds=20,spacing=.5)
        routes[1].update(points=[stationary,[stationary[0]+1,stationary[1]]],seconds=20,spacing=.5)
        e=Engine(p)
        a=Group(1,4,2,0,routes[0]['id'])
        b=Group(2,4,2,0,routes[1]['id'],state='blocked')
        e.groups={1:a,2:b}
        e.enter_path(a,e.objects[routes[0]['id']])
        return e

    def test_bent_path_detects_real_corner_collision(self):
        e=self.spacing_case([0,10])
        self.assertEqual(len(e.spacing),1)
        self.assertAlmostEqual(e.spacing[0]['time'],10)
        self.assertAlmostEqual(e.spacing[0]['distance'],0)

    def test_bent_path_avoids_false_diagonal_collision(self):
        self.assertEqual(self.spacing_case([5,5]).spacing,[])

    def test_invalid_numbers_and_routes_are_rejected(self):
        for field,value in [('duration',float('nan')),('duration',float('inf')),('stop','unknown'),
                            ('exterior_groups',1.5),('limit',2.5)]:
            p=simple()
            p.settings[field]=value
            self.assertTrue(validate(p)[0],(field,value))
            with self.assertRaises(ValueError):
                Engine(p)
        p=simple()
        path=next(o for o in p.objects if o['kind']=='path')
        path['target']=path['source']
        self.assertTrue(any('routes must lead' in e for e in validate(p)[0]))

    def test_malformed_project_is_rejected_before_display(self):
        for mutate in (lambda d:d['objects'][0].pop('id'),
                       lambda d:d['objects'][0].update(x=float('nan')),
                       lambda d:d['settings'].update(speed='bad')):
            data=simple().data()
            mutate(data)
            with self.assertRaises(ValueError):
                Project.from_data(data)

    def test_disabled_chosen_route_holds_group_in_room(self):
        e=Engine(simple())
        e.advance(10)
        g=e.groups[1]
        path=next(o for o in e.objects.values() if o['kind']=='path' and o['source']==g.location)
        g.chosen=path['id']
        path['enabled']=False
        e.advance(15)
        self.assertEqual(g.state,'overstay')
        path['enabled']=True
        e.retry()
        self.assertEqual(g.state,'walking')

    def test_generated_runs_conserve_people_time_and_capacity(self):
        rng=random.Random(20261004)
        for seed in range(100):
            p=example()
            p.settings.update(seed=seed,duration=rng.randint(50,500),exterior_groups=rng.randint(2,15),pixels_per_unit=40)
            p.settings['speed']=timing(3,1,5)
            for o in p.objects:
                if o['kind']=='room':
                    typical=rng.randint(0,40)
                    o['duration']=timing(typical,0,typical+10)
                    o['capacity']=rng.randint(1,3)
                elif o['kind']=='path':
                    o['seconds']=rng.uniform(.1,10) if seed%2 else 0
            e=Engine(p)
            while e.queue and e.queue[0][0]<=p.settings['duration']:
                e.step()
                self.assertTrue(all(len(e.occupants[o['id']])<=o['capacity'] for o in e.objects.values() if o['kind']=='room'))
                self.assertTrue(all(len(ids)<=1 for ids in e.paths.values()))
            e.advance(p.settings['duration'])
            r=summarize(e)
            m=r['metrics']
            self.assertEqual(m['groups_admitted'],m['groups_completed']+m['current_groups'])
            self.assertEqual(m['guests_admitted'],m['guests_completed']+m['current_guests'])
            elapsed=sum((g.completed if g.completed is not None else e.now)-g.admitted for g in e.groups.values())
            self.assertAlmostEqual(m['walking_seconds']+m['scene_seconds']+m['blocked_seconds'],elapsed,places=6)
            self.assertTrue(all(0<=room['utilization']<=1.000001 for room in r['rooms'].values()))
            self.assertEqual(sum(w['groups'] for w in r['windows']['5']),m['groups_completed'])
            self.assertTrue(all(0<=row['time']<=e.now for row in e.log))


if __name__=='__main__':
    unittest.main()
