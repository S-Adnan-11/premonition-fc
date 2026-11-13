from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from premonition_fc.storage import write_json
from prospective_trial import workflow
from prospective_trial.contracts import instant
from prospective_trial.qualification import QualificationPaused, qualify
from prospective_trial.store import transaction
from fictional import fixture_slates, history_snapshot
from qualification_fixtures import reference_bundle, reschedule


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.history = history_snapshot()
        self.slate = fixture_slates(3)[0]
        self.slate['omissions'] = []
        self.slate['expected_fixture_ids'] = [r['fixture_id'] for r in self.slate['fixtures']]
        self.reference = reference_bundle(self.root, self.history, self.slate)
        self.hpath, self.fpath, self.rpath = [self.root/n for n in ('history.json', 'slate.json', 'reference.json')]
        self.ledger, self.decisions = self.root/'trial.sqlite', self.root/'decisions.sqlite'
        self.save()

    def save(self):
        for path, value in ((self.hpath, self.history), (self.fpath, self.slate), (self.rpath, self.reference)):
            write_json(path, value)

    def freeze(self):
        return workflow.freeze(self.ledger, self.hpath, '2026-11-09T12:00:00Z', 'synthetic',
                               '2026-11-09T12:00:00Z', reference_path=self.rpath, decisions_path=self.decisions)

    def issue(self, at='2026-11-09T13:00:00Z'):
        return workflow.issue(self.ledger, self.fpath, self.hpath, at,
                              reference_path=self.rpath, decisions_path=self.decisions)

    def events(self, path):
        with transaction(path) as (_, events):
            return events

    def assert_pause(self, code):
        with self.assertRaisesRegex(QualificationPaused, code):
            self.issue()
        self.assertEqual(len(self.events(self.ledger)), 1)
        decision = self.events(self.decisions)[-1]['payload']
        self.assertEqual((decision['status'], decision['reason_code']), ('PAUSED', code))
        self.assertTrue(decision['recorded_before_known_kickoff'])

    def test_complete_history_required_before_fit(self):
        self.history['results'].pop()
        self.save()
        with self.assertRaisesRegex(QualificationPaused, 'RECENT_RESULTS_UNRECONCILED'):
            self.freeze()
        self.assertFalse(self.ledger.exists())
        self.assertEqual(self.events(self.decisions)[-1]['payload']['status'], 'PAUSED')

    def test_missing_fixture_cannot_shrink_expected_or_be_an_omission(self):
        self.freeze()
        missing = self.slate['fixtures'].pop()
        self.slate['expected_fixture_ids'].remove(missing['fixture_id'])
        self.save()
        self.assert_pause('EXPECTED_FIXTURE_MISSING')
        self.slate['expected_fixture_ids'].append(missing['fixture_id'])
        self.slate['omissions'] = [{k: missing[k] for k in ('fixture_id', 'season', 'home', 'away')} | {'reason': 'Missing provider row'}]
        self.save()
        self.assert_pause('EXPECTED_FIXTURE_MISSING')

    def test_changed_provider_kickoff_pauses_then_documented_reschedule_succeeds(self):
        frozen = self.freeze()
        fixture = self.slate['fixtures'][0]
        fixture['kickoff_at_utc'] = '2026-11-13T16:00:00Z'
        self.save()
        self.assert_pause('KICKOFF_UNVERIFIED')
        row = next(r for r in self.reference['fixtures'] if r['fixture_id'] == fixture['fixture_id'])
        reschedule(self.reference, fixture, fixture['kickoff_at_utc'])
        self.save()
        issued = self.issue()
        self.assertEqual(issued['fit_sha256'], frozen['fit_sha256'])
        self.assertEqual(len(issued['forecasts']), 6)
        self.assertEqual(issued, self.issue())
        self.assertEqual(len(self.events(self.ledger)), 2)
        self.assertEqual(row['kickoff_at_utc'], '2026-11-13T16:00:00Z')
        self.assertEqual(issued['qualification']['decision']['reference']['season_audit']['status'], 'FAIL')

    def test_undocumented_reference_change_and_removed_register_row_pause(self):
        self.freeze()
        fixture = self.slate['fixtures'][0]
        row = next(r for r in self.reference['fixtures'] if r['fixture_id'] == fixture['fixture_id'])
        row['kickoff_at_utc'] = fixture['kickoff_at_utc'] = '2026-11-13T16:00:00Z'
        self.save()
        self.assert_pause('KICKOFF_UNVERIFIED')
        self.reference['fixtures'].remove(row)
        self.save()
        self.assert_pause('REFERENCE_INCOMPLETE')

    def test_missing_or_changed_recent_result_pauses(self):
        self.freeze()
        original = deepcopy(self.history)
        for change in ('missing', 'changed', 'unresolved'):
            self.history = deepcopy(original)
            if change == 'missing':
                self.history['results'].pop()
            else:
                self.history['results'][-1]['home_goals'] = 9 if change == 'changed' else None
            self.save()
            self.assert_pause('RECENT_RESULTS_UNRECONCILED')

    def test_stale_reference_and_altered_document_pause(self):
        self.freeze()
        self.reference['observed_at_utc'] = '2026-11-01T12:00:00Z'
        self.save()
        self.assert_pause('EVIDENCE_STALE')
        self.reference['observed_at_utc'] = '2026-11-09T12:00:00Z'
        self.save()
        (self.root/'schedule.txt').write_text('changed', encoding='utf-8')
        self.assert_pause('EVIDENCE_CHANGED')

    def test_qualified_fit_cannot_issue_without_reference(self):
        self.freeze()
        with self.assertRaisesRegex(QualificationPaused, 'QUALIFICATION_REQUIRED'):
            workflow.issue(self.ledger, self.fpath, self.hpath, '2026-11-09T13:00:00Z')
        self.assertEqual(len(self.events(self.ledger)), 1)

    def test_real_fit_requires_reference_even_with_access_gates(self):
        self.history['mode'] = 'real'
        self.save()
        with patch.object(workflow, 'approve', return_value={}), patch.object(workflow, 'clock', return_value=instant('2026-11-09T12:00:00Z')):
            with self.assertRaisesRegex(QualificationPaused, 'QUALIFICATION_REQUIRED'):
                workflow.freeze(self.ledger, self.hpath, '2026-11-09T12:00:00Z', 'real')
        self.assertFalse(self.ledger.exists())

    def test_late_attempt_record_is_not_claimed_to_be_pre_result(self):
        self.freeze()
        self.history['observed_at_utc'] = '2026-11-13T16:00:00Z'
        self.history['coverage']['checked_at_utc'] = self.history['observed_at_utc']
        self.reference.update(observed_at_utc=self.history['observed_at_utc'], history_through_london_date='2026-11-13')
        self.save()
        with self.assertRaises(QualificationPaused):
            self.issue('2026-11-13T16:00:00Z')
        self.assertFalse(self.events(self.decisions)[-1]['payload']['recorded_before_known_kickoff'])
        self.assertEqual(len(self.events(self.ledger)), 1)

    def test_reference_changed_while_predicting_rolls_back_issue(self):
        self.freeze()
        original = workflow.forecast_pair
        def changed(*args):
            result = original(*args)
            self.reference['amendments'].append({'reason': 'changed during prediction'})
            self.save()
            return result
        with patch.object(workflow, 'forecast_pair', side_effect=changed):
            self.assert_pause('EVIDENCE_CHANGED')

    def test_unverified_kickoff_and_reference_json_failure_are_recorded(self):
        self.freeze()
        row = next(r for r in self.reference['fixtures'] if r['fixture_id'] == self.slate['fixtures'][0]['fixture_id'])
        row['kickoff_at_utc'] = None
        self.save()
        self.assert_pause('KICKOFF_UNVERIFIED')
        self.rpath.write_text('{invalid', encoding='utf-8')
        self.assert_pause('REFERENCE_INVALID')

    def test_kickoff_reached_while_predicting_records_pause_without_issue(self):
        self.freeze()
        observed = '2026-11-13T14:00:00Z'
        self.history['observed_at_utc'] = self.history['coverage']['checked_at_utc'] = observed
        self.slate['observed_at_utc'] = self.slate['coverage']['checked_at_utc'] = observed
        for row in self.slate['fixtures']:
            row['verified_at_utc'] = observed
        self.reference.update(observed_at_utc=observed, history_through_london_date='2026-11-13')
        self.save()
        with patch.object(workflow, 'clock', side_effect=[instant(observed), instant('2026-11-13T15:00:00Z')]):
            with self.assertRaisesRegex(QualificationPaused, 'SLATE_STARTED'):
                self.issue()
        self.assertEqual(len(self.events(self.ledger)), 1)
        last = self.events(self.decisions)[-1]['payload']
        self.assertEqual(last['reason_code'], 'SLATE_STARTED')
        self.assertFalse(last['recorded_before_known_kickoff'])


if __name__ == '__main__':
    unittest.main()
