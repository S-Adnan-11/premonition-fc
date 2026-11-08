from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from premonition_fc.storage import read_json, write_json
from prospective_trial import workflow
from prospective_trial.contracts import instant, live_gates, slate
from prospective_trial.protocol import MODELS
from prospective_trial.store import transaction
from fictional import envelope, fixture_slates, history_snapshot, settlement_snapshot


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root/'trial.sqlite'
        self.history = self.root/'history.json'
        write_json(self.history, history_snapshot())
        workflow.freeze(self.ledger, self.history, '2026-11-09T12:00:00Z', 'synthetic', '2026-11-09T12:00:00Z')
        self.slates = fixture_slates(3)
        self.fixtures = self.root/'fixtures.json'
        write_json(self.fixtures, self.slates[0])

    def issue(self):
        return workflow.issue(self.ledger, self.fixtures, self.history, '2026-11-09T13:00:00Z')

    def events(self):
        with transaction(self.ledger) as (_, events):
            return events

    def test_same_pair_cutoff_neutral_and_no_target_reads(self):
        original = workflow.read_snapshot
        opened = []
        def guarded(path):
            opened.append(Path(path).name)
            if 'settlement' in str(path):
                raise AssertionError('Issue read settlement scores')
            return original(path)
        with patch.object(workflow, 'read_snapshot', side_effect=guarded):
            issued = self.issue()
        self.assertEqual(opened, ['fixtures.json','history.json'])
        forecasts = issued['forecasts']
        self.assertEqual({r['model'] for r in forecasts}, set(MODELS))
        for model in MODELS:
            self.assertEqual({r['fixture_id'] for r in forecasts if r['model']==model}, set(self.slates[0]['expected_fixture_ids'])-{self.slates[0]['omissions'][0]['fixture_id']})
        self.assertTrue(all(r['issue_date_london']=='2026-11-09' for r in forecasts))
        self.assertTrue(all(r['away_neutral_fallback'] for r in forecasts if r['model']=='team_strength_poisson'))
        self.assertTrue(all(t['prior_latest_date']<'2026-11-09' for t in issued['feature_traces']))
        self.assertEqual(issued, self.issue())
        self.assertEqual(len(self.events()), 2)

    def test_changed_duplicate_missing_time_and_past_kickoff_rejected(self):
        for mutation in (lambda s:s['fixtures'][0].update(kickoff_at_utc='2026-11-13T15:00:00'),
                         lambda s:s['fixtures'][0].update(kickoff_at_utc='2026-11-08T15:00:00Z'),
                         lambda s:s['fixtures'][0].update(home='changed'),
                         lambda s:s['fixtures'].append(deepcopy(s['fixtures'][0])),
                         lambda s:s['fixtures'][0].update(home_goals=0),
                         lambda s:s['expected_fixture_ids'].append('unknown')):
            source = deepcopy(self.slates[0])
            mutation(source)
            write_json(self.fixtures, source)
            with self.assertRaises(ValueError):
                self.issue()
            self.assertEqual(len(self.events()), 1)

    def test_stale_or_future_observation_and_issue_before_fit(self):
        for observed in ('2026-11-01T12:00:00Z','2026-11-09T14:00:00Z'):
            source=deepcopy(self.slates[0]);source['observed_at_utc']=observed
            write_json(self.fixtures,source)
            with self.assertRaises(ValueError):
                self.issue()
        write_json(self.fixtures,self.slates[0])
        with self.assertRaisesRegex(ValueError,'precedes'):
            workflow.issue(self.ledger,self.fixtures,self.history,'2026-11-09T11:00:00Z')

    def test_changed_issued_request_and_duplicate_in_other_slate_fail(self):
        self.issue()
        source=deepcopy(self.slates[0])
        source['fixtures'][0]['kickoff_at_utc']='2026-11-13T16:00:00Z'
        write_json(self.fixtures,source)
        with self.assertRaisesRegex(ValueError,'cannot be replaced'):
            self.issue()
        source['slate_id']='2026-27:2026-11-17'
        for row in source['fixtures']:
            row['kickoff_at_utc']='2026-11-20T15:00:00Z'
        source['earliest_verified_kickoff_at_utc']='2026-11-20T15:00:00Z'
        write_json(self.fixtures,source)
        with self.assertRaisesRegex(ValueError,'already issued'):
            self.issue()

    def test_changed_history_and_future_scores_fail_without_write(self):
        source=history_snapshot()
        source['results'][0]['home_goals']=9
        write_json(self.history,source)
        with self.assertRaisesRegex(ValueError,'missing or changed'):
            self.issue()
        source=history_snapshot()
        source['results'][0].update(availability_basis='confirmed_time',available_at_utc='2026-11-10T00:00:00Z')
        write_json(self.history,source)
        with self.assertRaises(ValueError):
            self.issue()
        self.assertEqual(len(self.events()),1)

    def test_concurrent_identical_issues_have_one_record(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first,second=list(pool.map(lambda _:self.issue(),range(2)))
        self.assertEqual(first,second)
        self.assertEqual(len(self.events()),2)

    def test_interrupted_issue_is_atomic_and_retryable(self):
        append=workflow.append
        def interrupted(*args):
            append(*args)
            raise RuntimeError('simulated process interruption')
        with patch.object(workflow,'append',side_effect=interrupted),self.assertRaises(RuntimeError):
            self.issue()
        self.assertEqual(len(self.events()),1)
        self.issue()
        self.assertEqual(len(self.events()),2)

    def test_postponed_void_zero_draw_and_repeat_settlement(self):
        original=self.issue()
        source=settlement_snapshot(self.slates)
        path=self.root/'settlement.json'
        write_json(path,source)
        at=source['observed_at_utc']
        value=workflow.settle(self.ledger,path,at)
        self.assertEqual((value['settled'],value['pending'],value['void'],value['omitted']),(1,1,1,1))
        self.assertEqual(value,workflow.settle(self.ledger,path,at))
        n=len(self.events())
        reissue=workflow.display_reissue(self.ledger,self.slates[0]['fixtures'][0]['fixture_id'],'2026-11-15T15:00:00Z',at)
        self.assertTrue(reissue['display_only'])
        source=settlement_snapshot(self.slates,True)
        write_json(path,source)
        value=workflow.settle(self.ledger,path,source['observed_at_utc'])
        self.assertEqual((value['settled'],value['pending'],value['void']),(2,0,1))
        self.assertEqual(original,next(e['payload'] for e in self.events() if e['kind']=='issue'))
        result=next(e['payload']['result'] for e in self.events() if e['kind']=='settled' and e['payload']['fixture_id']==self.slates[0]['fixtures'][0]['fixture_id'])
        self.assertEqual((result['home_goals'],result['away_goals']),(0,0))
        self.assertGreater(len(self.events()),n)

    def test_changed_duplicate_partial_or_early_settlement_rejected(self):
        self.issue()
        path=self.root/'settlement.json'
        valid=settlement_snapshot(self.slates)
        for mutation in (lambda s:s['updates'].append(deepcopy(s['updates'][0])),
                         lambda s:s['updates'].pop(),
                         lambda s:s['updates'][1].update(completed_at_utc='2026-11-09T12:00:00Z'),
                         lambda s:s['updates'][1].update(home_goals=None)):
            source=deepcopy(valid);mutation(source);write_json(path,source)
            with self.assertRaises(ValueError):
                workflow.settle(self.ledger,path,source['observed_at_utc'])
            self.assertEqual(len(self.events()),2)
        write_json(path,valid);workflow.settle(self.ledger,path,valid['observed_at_utc'])
        valid['updates'][1]['home_goals']=99
        write_json(path,valid)
        with self.assertRaisesRegex(ValueError,'cannot be revised'):
            workflow.settle(self.ledger,path,valid['observed_at_utc'])

    def test_no_interim_review_or_overwritten_export(self):
        self.issue()
        with self.assertRaisesRegex(ValueError,'100'):
            workflow.review(self.ledger,'2026-11-09T13:00:00Z')
        result=workflow.export(self.ledger,self.root/'report')
        self.assertIsNone(result['review'])
        with self.assertRaises(ValueError):
            workflow.export(self.ledger,self.root/'report')

    def test_interrupted_settlement_rolls_back_every_terminal(self):
        self.issue()
        path=self.root/'settlement.json'
        source=settlement_snapshot(self.slates,True);write_json(path,source)
        append=workflow.append
        def interrupted(*args):
            append(*args)
            raise RuntimeError('simulated process interruption')
        with patch.object(workflow,'append',side_effect=interrupted),self.assertRaises(RuntimeError):
            workflow.settle(self.ledger,path,source['observed_at_utc'])
        self.assertEqual(len(self.events()),2)
        self.assertEqual(workflow.settle(self.ledger,path,source['observed_at_utc'])['settled'],2)


    def test_form_can_update_while_both_fits_stay_fixed(self):
        from prospective_trial.contracts import history
        from prospective_trial.models import forecast_pair
        fit=self.events()[0]['payload']['fit']
        original=history_snapshot()
        before,_=history(original,'synthetic',instant('2026-11-09T13:00:00Z'))
        changed=deepcopy(original)
        changed['results'].append({'fixture_id':'2026-27:fictional-00:harbour-athletic','season':'2026-27',
            'home':'fictional-00','away':'harbour-athletic','played_date':'2026-11-10','status':'completed',
            'home_goals':0,'away_goals':8,'availability_basis':'confirmed_time','available_at_utc':'2026-11-10T20:00:00Z'})
        changed['observed_at_utc']='2026-11-12T12:00:00Z'
        changed['coverage']['checked_at_utc']=changed['observed_at_utc']
        after,_=history(changed,'synthetic',instant('2026-11-12T13:00:00Z'))
        target=dict(self.slates[0]['fixtures'][0],played_date='2026-11-13')
        old,_=forecast_pair(fit,[target],before,'2026-11-12')
        new,_=forecast_pair(fit,[target],after,'2026-11-12')
        self.assertNotEqual(old[0]['home_mean'],new[0]['home_mean'])
        self.assertEqual(old[1],new[1])

    def test_omitted_verified_kickoff_bounds_the_entire_slate(self):
        source=deepcopy(self.slates[0])
        source['omissions'][0].update(kickoff_at_utc='2026-11-13T14:00:00Z',verified_at_utc='2026-11-09T12:30:00Z')
        write_json(self.fixtures,source)
        with self.assertRaisesRegex(ValueError,'includes omitted'):
            self.issue()
        source['earliest_verified_kickoff_at_utc']='2026-11-13T14:00:00Z'
        write_json(self.fixtures,source)
        self.assertEqual(self.issue()['fixture_snapshot']['earliest_verified_kickoff_at_utc'],'2026-11-13T14:00:00Z')


class ReviewAndGateTests(unittest.TestCase):
    def test_full_100_gate_and_deterministic_metrics(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);history=root/'history.json';write_json(history,history_snapshot())
            ledger=root/'trial.sqlite'
            workflow.freeze(ledger,history,'2026-11-09T12:00:00Z','synthetic','2026-11-09T12:00:00Z')
            slates=fixture_slates()
            for i,source in enumerate(slates):
                path=root/f'slate-{i}.json';write_json(path,source)
                workflow.issue(ledger,path,history,'2026-11-09T13:00:00Z')
            first=settlement_snapshot(slates);path=root/'settlement.json';write_json(path,first)
            self.assertEqual(workflow.settle(ledger,path,first['observed_at_utc'])['settled'],99)
            with self.assertRaisesRegex(ValueError,'100'):
                workflow.review(ledger,first['observed_at_utc'])
            second=settlement_snapshot(slates,True);write_json(path,second)
            self.assertEqual(workflow.settle(ledger,path,second['observed_at_utc'])['settled'],100)
            review=workflow.review(ledger,second['observed_at_utc'])
            self.assertEqual(review,workflow.review(ledger,second['observed_at_utc']))
            self.assertEqual(len(review['cohort_fixture_ids']),100)
            self.assertEqual(review['uncertainty']['blocks'],17)
            self.assertIsNotNone(review['uncertainty']['lower'])
            self.assertEqual({r['pooled']['fixtures'] for r in review['metrics'].values()},{100})
            for model in MODELS:
                for bins in review['metrics'][model]['pooled']['reliability'].values():
                    self.assertEqual(sum(b['count'] for b in bins),100)
            first_export=workflow.export(ledger,root/'first')
            self.assertEqual(first_export,workflow.export(ledger,root/'second'))
            for name in ('summary.json','events.json','fits.json','provenance.json','REPORT.md'):
                self.assertEqual((root/'first'/name).read_bytes(),(root/'second'/name).read_bytes())

    def test_real_gates_require_project_scope_and_independent_evidence(self):
        at=instant('2026-11-09T12:00:00Z')
        gate={'status':'PASS','evidence_sha256':'a'*64}
        approval={'project':'Premonition-FC','source_id':'approved-local','platform':'direct','product':'Football','plan':'Basic',
                  'reviewed_at_utc':'2026-11-09T10:00:00Z','expires_at_utc':'2026-11-10T00:00:00Z',
                  'access':dict(gate,quota_observed_at_utc='2026-11-09T10:00:00Z',quota_reset_at_utc='2026-11-10T00:00:00Z',remaining=10,shared_reserve=4,project_allowance=6),
                  'freshness':dict(gate),'model_input_and_display':dict(gate),'retention':dict(gate)}
        self.assertEqual(live_gates(approval,'real',at),approval)
        for name in ('access','freshness','model_input_and_display','retention'):
            blocked=deepcopy(approval);blocked[name]['status']='BLOCKED'
            with self.assertRaises(ValueError):
                live_gates(blocked,'real',at)
        for mutate in (lambda a:a.update(project='different'),lambda a:a['access'].update(remaining=9),
                       lambda a:a['access'].update(project_allowance=7),lambda a:a.update(expires_at_utc='2026-11-08T00:00:00Z')):
            blocked=deepcopy(approval);mutate(blocked)
            with self.assertRaises(ValueError):
                live_gates(blocked,'real',at)


if __name__=='__main__':
    unittest.main()
