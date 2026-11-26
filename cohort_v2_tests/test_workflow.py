"""Version boundaries, fit reuse, fixed closure, attribution and atomic recovery."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from premonition_fc.storage import digest, object_digest, read_json, write_json
from prospective_trial import workflow as legacy
from prospective_trial.contracts import instant
from prospective_trial.store import transaction, append
from prospective_trial.protocol import fingerprints, RULES as V1_RULES
from prospective_v2 import workflow
from prospective_v2.protocol import RULES, RULES_SHA256, fingerprint
from cohort_v2_tests.fictional import scenario, fact_snapshot, reconcile_parents


class V2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent_temp = TemporaryDirectory(prefix='premonition-v2-parent-')
        cls.parent_root = Path(cls.parent_temp.name)
        scenario(cls.parent_root, 3)
        cls.parent_ledger = cls.parent_root/'v1.sqlite'
        legacy.freeze(cls.parent_ledger, cls.parent_root/'history.json', '2026-11-09T12:00:00Z',
                      'synthetic', '2026-11-09T12:00:00Z')
        legacy.export(cls.parent_ledger, cls.parent_root/'export')
        cls.parent = cls.parent_root/'export/events.json'; cls.parent_pin = digest(cls.parent)
        cls.legacy_fingerprints = fingerprints()

    @classmethod
    def tearDownClass(cls):
        cls.parent_temp.cleanup()

    def setUp(self):
        self.temp = TemporaryDirectory(prefix='premonition-v2-test-'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.past, self.slates, self.reference, self.paths = scenario(self.root)
        self.history = self.root/'history.json'; self.ref = self.root/'reference.json'
        self.proposal = workflow.draft(self.parent, self.parent_pin, 'synthetic', '2026-11-09T12:40:00Z')
        self.draft = self.root/'draft.json'; write_json(self.draft, self.proposal)
        self.ledger = self.root/'v2.sqlite'

    def register(self):
        return workflow.register(self.ledger, self.draft, self.parent, self.parent_pin,
            self.paths[0], self.history, self.ref, '2026-11-09T12:45:00Z')

    def issue_all(self, count=None):
        self.register()
        for path in self.paths[:count]:
            workflow.issue(self.ledger, path, self.history, self.ref, '2026-11-09T13:00:00Z')

    def events(self):
        with transaction(self.ledger) as (_, events): return deepcopy(events)

    def facts(self, source):
        path = self.root/'facts.json'; write_json(path, source)
        return workflow.settle(self.ledger, path, source['reviewed_at_utc'])

    def final(self, **kwargs):
        return fact_snapshot(self.root, self.slates, **kwargs)

    def test_rules_keep_exact_numerical_specifications_and_legacy_fingerprints(self):
        changed = {'version', 'cohort_order', 'cohort_closure', 'registration', 'cancelled',
                   'postponed', 'corrections', 'completion_evidence', 'source_policy'}
        self.assertEqual({k: v for k, v in RULES.items() if k not in changed},
                         {k: v for k, v in V1_RULES.items() if k not in changed})
        self.assertEqual(fingerprints(), self.legacy_fingerprints)
        self.assertEqual(V1_RULES['version'], 1)
        self.assertEqual(self.proposal['state'], 'unactivated'); self.assertFalse(self.ledger.exists())

    def test_registration_copies_original_fit_without_refitting_and_is_idempotent(self):
        with patch('prospective_trial.models.fit_pair', side_effect=AssertionError('No refit')):
            first = self.register(); second = self.register()
        self.assertEqual(first, second)
        self.assertEqual(len(self.events()), 1)
        parent = read_json(self.parent)[0]['payload']
        self.assertEqual(first['fit'], parent['fit'])
        self.assertEqual(object_digest(first['fit']), first['parent']['fit_sha256'])
        self.assertEqual(first['parent']['parent_rules_sha256'], parent['rules_sha256'])
        self.assertEqual(first['state'], 'active')

    def test_mixed_draft_version_rules_or_parent_pin_are_rejected(self):
        for key, value in (('protocol_version', 1), ('rules_sha256', 'a'*64), ('state', 'active'), ('v2_code_sha256', 'a'*64)):
            source = deepcopy(self.proposal); source[key] = value; write_json(self.draft, source)
            with self.subTest(key=key), self.assertRaises(ValueError): self.register()
            self.assertFalse(self.ledger.exists())
        write_json(self.draft, self.proposal)
        with self.assertRaises(ValueError): workflow.draft(self.parent, 'a'*64, 'synthetic', '2026-11-09T12:40:00Z')

    def test_legacy_replay_stays_legacy_and_each_version_rejects_the_other_ledger(self):
        old_hash = digest(self.parent_ledger)
        first = legacy.export(self.parent_ledger, self.root/'legacy-first')
        second = legacy.export(self.parent_ledger, self.root/'legacy-second')
        self.assertEqual(first, second); self.assertEqual(digest(self.parent_ledger), old_hash)
        self.assertNotIn('protocol_version', read_json(self.root/'legacy-first/events.json')[0]['payload'])
        with transaction(self.parent_ledger) as (_, events), self.assertRaises(ValueError): workflow.metadata(events)
        self.register()
        with self.assertRaises(ValueError): legacy.export(self.ledger, self.root/'wrong')

    def test_legacy_database_is_rejected_by_immutable_preflight_before_transaction(self):
        before = digest(self.parent_ledger)
        with patch.object(workflow, 'transaction', side_effect=AssertionError('Mutating open forbidden')):
            with self.assertRaises(ValueError): workflow.export(self.parent_ledger, self.root/'wrong')
            with self.assertRaises(ValueError): workflow.review(self.parent_ledger, '2026-11-09T13:00:00Z')
        self.assertEqual(digest(self.parent_ledger), before)

    def test_raced_in_legacy_registration_target_is_rejected_before_writable_open(self):
        actual_transaction = workflow.transaction
        def checked_transaction(path, **kwargs):
            if Path(path) == self.ledger: raise AssertionError('Legacy writable open forbidden')
            return actual_transaction(path, **kwargs)
        def raced_link(candidate, target):
            shutil.copyfile(self.parent_ledger, target)
            raise FileExistsError('Fictional concurrent legacy target')
        with patch.object(workflow.os, 'link', side_effect=raced_link), patch.object(workflow, 'transaction', side_effect=checked_transaction):
            with self.assertRaises(ValueError): self.register()
        self.assertEqual(digest(self.ledger), digest(self.parent_ledger))

    def test_previously_issued_v1_pairs_cannot_be_registered_into_v2(self):
        ledger = self.root/'parent-copy.sqlite'; shutil.copyfile(self.parent_ledger, ledger)
        legacy.issue(ledger, self.paths[0], self.history, '2026-11-09T13:00:00Z')
        legacy.export(ledger, self.root/'parent-with-issue')
        parent = self.root/'parent-with-issue/events.json'; pin = digest(parent)
        proposal = workflow.draft(parent, pin, 'synthetic', '2026-11-09T13:30:00Z')
        path = self.root/'later-draft.json'; write_json(path, proposal)
        with self.assertRaisesRegex(ValueError, 'v1 fixtures'):
            workflow.register(self.ledger, path, parent, pin, self.paths[0], self.history,
                              self.ref, '2026-11-09T13:45:00Z')
        self.assertFalse(self.ledger.exists())

    def test_registration_cannot_activate_after_kickoff_or_use_a_real_controlled_clock(self):
        with self.assertRaises(ValueError):
            workflow.register(self.ledger, self.draft, self.parent, self.parent_pin,
                self.paths[0], self.history, self.ref, '2026-11-13T16:00:00Z')
        with self.assertRaises(ValueError): workflow.draft(self.parent, self.parent_pin, 'real', '2026-11-09T12:40:00Z')

    def test_whole_slate_history_authority_and_initial_identity_are_checked(self):
        self.register()
        for kind in ('missing', 'known', 'history', 'first'):
            source = deepcopy(self.slates[0]); past = deepcopy(self.past)
            if kind == 'missing': source['fixtures'].pop()
            if kind == 'known': source['fixtures'][0]['fixture_id'] = past['results'][0]['fixture_id']
            if kind == 'history': past['results'][0]['home_goals'] = 99
            path = self.paths[1] if kind == 'first' else self.paths[0]
            if kind != 'first': write_json(path, source)
            write_json(self.history, past)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                workflow.issue(self.ledger, path, self.history, self.ref, '2026-11-09T13:00:00Z')
            self.assertEqual(len(self.events()), 1)
            write_json(self.paths[0], self.slates[0]); write_json(self.history, self.past)
        with self.assertRaises(ValueError): workflow._authority('https://example.test/unapproved', 'real')

    def test_issue_duplicate_delivery_and_simultaneous_retry_do_not_duplicate_pairs(self):
        self.register()
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _: workflow.issue(self.ledger, self.paths[0], self.history,
                                                          self.ref, '2026-11-09T13:00:00Z'), range(2)))
        self.assertEqual(values[0], values[1]); self.assertEqual(len(self.events()), 2)
        self.assertEqual(len(values[0]['forecasts']), 12)

    def test_interrupted_registration_issue_and_facts_are_atomic_and_retryable(self):
        actual = workflow.append
        def interrupted(*args): actual(*args); raise RuntimeError('Fictional interruption')
        with patch.object(workflow, 'append', side_effect=interrupted), self.assertRaises(RuntimeError): self.register()
        self.assertFalse(self.ledger.exists()); self.register()
        with patch.object(workflow, 'append', side_effect=interrupted), self.assertRaises(RuntimeError):
            workflow.issue(self.ledger, self.paths[0], self.history, self.ref, '2026-11-09T13:00:00Z')
        self.assertEqual(len(self.events()), 1)
        workflow.issue(self.ledger, self.paths[0], self.history, self.ref, '2026-11-09T13:00:00Z')
        source = fact_snapshot(self.root, self.slates[:1])
        with patch.object(workflow, 'append', side_effect=interrupted), self.assertRaises(RuntimeError): self.facts(source)
        self.assertEqual(len(self.events()), 2); self.assertEqual(self.facts(source)['settled'], 6)

    def test_tied_kickoffs_use_fixture_id_and_earlier_pending_blocks_100_later_results(self):
        self.issue_all(); original = self.events()
        positions = sorted(workflow._issued(original), key=lambda key: (
            workflow._issued(original)[key][1]['seq'], instant(workflow._issued(original)[key][0]['kickoff_at_utc']), key))
        source = self.final(pending_first=True)
        progress = self.facts(source)
        self.assertEqual(progress['settled'], 100); self.assertFalse(progress['review_ready'])
        self.assertEqual(progress['blocked_fixture_id'], positions[0])
        with self.assertRaisesRegex(ValueError, 'closed 100'): workflow.review(self.ledger, source['reviewed_at_utc'])
        source['updates'][0].update(status='completed', home_goals=0, away_goals=0,
            played_date=self.slates[0]['fixtures'][0]['kickoff_at_utc'][:10], available_at_utc=source['observed_at_utc'], basis='official_replay')
        reconcile_parents(source, self.events()); self.facts(source)
        result = workflow.review(self.ledger, source['reviewed_at_utc'])
        self.assertEqual(result['cohort_fixture_ids'], positions[:100])
        self.assertEqual(next(e for e in self.events() if e['kind'] == 'issue'), next(e for e in original if e['kind'] == 'issue'))

    def test_delivery_order_and_verified_replay_date_cannot_change_original_positions(self):
        for path, source in zip(self.paths, self.slates):
            source['fixtures'].reverse(); write_json(path, source)
        self.issue_all()
        before = self.events(); issued = workflow._issued(before)
        positions = sorted(issued, key=lambda key: (issued[key][1]['seq'], instant(issued[key][0]['kickoff_at_utc']), key))
        self.assertEqual(positions[:6], sorted(r['fixture_id'] for r in self.slates[0]['fixtures']))
        source = self.final(); source['updates'].reverse()
        first = next(r for r in source['updates'] if r['fixture_id'] == positions[0])
        first.update(played_date=source['observed_at_utc'][:10], available_at_utc=source['observed_at_utc'], basis='official_replay')
        self.facts(source)
        self.assertEqual(workflow.review(self.ledger, source['reviewed_at_utc'])['cohort_fixture_ids'], positions[:100])
        self.assertEqual(workflow._issued(self.events()), issued)

    def test_99_100_101_boundary_and_void_replacement_keep_exact_fixed_cohort(self):
        self.issue_all()
        source = self.final(pending_first=True, void_last=True)
        first = self.facts(source); self.assertEqual((first['settled'], first['void'], first['pending']), (99, 1, 1))
        self.assertFalse(first['review_ready'])
        complete = self.final(void_last=True, events=self.events())
        complete['updates'][0].update(home_goals=0, away_goals=0)
        reconcile_parents(complete, self.events())
        final = self.facts(complete); self.assertEqual((final['settled'], final['void'], final['pending']), (100, 1, 0))
        review = workflow.review(self.ledger, complete['reviewed_at_utc'])
        self.assertEqual(review, workflow.review(self.ledger, complete['reviewed_at_utc']))
        self.assertEqual(review['fixtures'], 100)
        self.assertEqual(set(review['metrics']), set(RULES['models']))
        self.assertEqual({m['pooled']['fixtures'] for m in review['metrics'].values()}, {100})
        first_export = workflow.export(self.ledger, self.root/'first')
        self.assertEqual(first_export, workflow.export(self.ledger, self.root/'second'))
        for path in (self.root/'first').iterdir(): self.assertEqual(path.read_bytes(), (self.root/'second'/path.name).read_bytes())
        with self.assertRaises(ValueError): workflow.export(self.ledger, self.root/'first')

    def test_pending_exceptional_and_awarded_dispositions_never_invent_scores(self):
        self.issue_all(1)
        source = fact_snapshot(self.root, self.slates[:1])
        for row, status in zip(source['updates'], ('scheduled', 'postponed', 'unresolved', 'suspended', 'abandoned', 'awarded')):
            row.update(status=status, home_goals=None, away_goals=None, played_date=None,
                       available_at_utc=None, basis='administrative_award' if status == 'awarded' else 'awaiting_review')
        state = self.facts(source); self.assertEqual((state['pending'], state['void'], state['settled']), (5, 1, 0))

    def test_duplicate_missing_unknown_identity_scores_authority_precision_and_version_fail(self):
        self.issue_all(1)
        original = fact_snapshot(self.root, self.slates[:1])
        changes = [lambda s: s['updates'].pop(), lambda s: s['updates'].append(deepcopy(s['updates'][0])),
            lambda s: s['updates'][0].update(fixture_id='2026-27:unknown:other', home='unknown', away='other'),
            lambda s: s['updates'][0].update(home_goals=True),
            lambda s: s['updates'][0].update(status='postponed'),
            lambda s: s['documents']['official'].update(authority='news_report'),
            lambda s: s['documents']['official'].update(precision=''),
            lambda s: s.update(protocol_version=1), lambda s: s.update(rules_sha256='f'*64)]
        for change in changes:
            source = deepcopy(original); change(source)
            with self.subTest(change=change), self.assertRaises(ValueError): self.facts(source)
            self.assertEqual(len(self.events()), 2)

    def test_factual_retry_and_changed_result_require_append_only_parent_and_reason(self):
        self.issue_all(1); source = fact_snapshot(self.root, self.slates[:1])
        first = self.facts(source); count = len(self.events())
        self.assertEqual(first, self.facts(source)); self.assertEqual(len(self.events()), count)
        source['updates'][0]['home_goals'] = 7
        with self.assertRaisesRegex(ValueError, 'parent hash'): self.facts(source)
        reconcile_parents(source, self.events()); self.facts(source)
        events = self.events(); self.assertEqual(len(events), count+1)
        facts = [e for e in events if e['kind'] == 'facts']
        self.assertEqual(facts[0]['payload']['facts'][0]['result']['home_goals'], 0)
        self.assertEqual(workflow._latest(events)[source['updates'][0]['fixture_id']]['result']['home_goals'], 7)
        self.assertTrue(facts[-1]['payload']['changes'])

    def test_evidence_hash_and_backdated_observation_fail_without_writes(self):
        self.issue_all(1); source = fact_snapshot(self.root, self.slates[:1]); self.facts(source)
        count = len(self.events())
        changed = deepcopy(source); changed['documents']['official']['sha256'] = 'a'*64
        with self.assertRaisesRegex(ValueError, 'evidence bytes'): self.facts(changed)
        changed = deepcopy(source); changed['observed_at_utc'] = '2026-11-09T13:30:00Z'
        with self.assertRaisesRegex(ValueError, 'backward'): self.facts(changed)
        self.assertEqual(len(self.events()), count)

    def test_final_evidence_after_issue_canonical_played_date_and_authority_kind(self):
        self.issue_all(1); source = fact_snapshot(self.root, self.slates[:1])
        bad = deepcopy(source); bad['documents']['official']['observed_at_utc'] = '2026-11-09T12:50:00Z'
        with self.assertRaisesRegex(ValueError, 'predates'): self.facts(bad)
        bad = deepcopy(source); bad['updates'][0]['played_date'] = '20261113'
        with self.assertRaisesRegex(ValueError, 'canonical ISO'): self.facts(bad)
        with self.assertRaisesRegex(ValueError, 'authority kind'):
            workflow._authority('https://www.premierleague.com/facts', 'real', 'official_club')
        with self.assertRaisesRegex(ValueError, 'authority kind'):
            workflow._authority('https://www.liverpoolfc.com/facts', 'real', 'official_league')
        self.assertEqual(len(self.events()), 2)

    def test_interrupted_review_rolls_back_and_retry_freezes_once(self):
        self.issue_all(); source = self.final(); self.facts(source)
        count = len(self.events()); actual = workflow.append
        def interrupted(*args): actual(*args); raise RuntimeError('Fictional review interruption')
        with patch.object(workflow, 'append', side_effect=interrupted), self.assertRaises(RuntimeError):
            workflow.review(self.ledger, source['reviewed_at_utc'])
        self.assertEqual(len(self.events()), count)
        first = workflow.review(self.ledger, source['reviewed_at_utc'])
        self.assertEqual(first, workflow.review(self.ledger, source['reviewed_at_utc']))
        self.assertEqual(len(self.events()), count+1)

    def test_post_review_correction_retains_original_and_corrected_analysis_same_cohort(self):
        self.issue_all(); source = self.final(); self.facts(source)
        original = workflow.review(self.ledger, source['reviewed_at_utc']); original_hash = object_digest(original)
        source['updates'][0]['home_goals'] = 7; reconcile_parents(source, self.events())
        state = self.facts(source); self.assertTrue(state['integrity_notices'])
        self.assertEqual(object_digest(workflow.review(self.ledger, source['reviewed_at_utc'])), original_hash)
        correction = workflow.corrected_review(self.ledger, 'Fictional official score correction', source['reviewed_at_utc'])
        self.assertEqual(correction['cohort_fixture_ids'], original['cohort_fixture_ids'])
        self.assertTrue(correction['cohort_unchanged'])
        self.assertNotEqual(correction['paired_log_loss_difference'], original['paired_log_loss_difference'])
        self.assertEqual(correction, workflow.corrected_review(self.ledger, 'Fictional official score correction', source['reviewed_at_utc']))

    def test_post_review_disposition_change_blocks_automatic_replacement(self):
        self.issue_all(); source = self.final(); self.facts(source)
        original = workflow.review(self.ledger, source['reviewed_at_utc'])
        source['updates'][0].update(status='cancelled', home_goals=None, away_goals=None, played_date=None,
            available_at_utc=None, basis='official_cancellation'); reconcile_parents(source, self.events())
        state = self.facts(source); self.assertTrue(state['integrity_notices'][0]['disposition_boundary_fixture_ids'])
        self.assertEqual(workflow.review(self.ledger, source['reviewed_at_utc']), original)
        with self.assertRaisesRegex(ValueError, 'separate amendment'):
            workflow.corrected_review(self.ledger, 'Fictional disposition correction', source['reviewed_at_utc'])

    def test_mixed_event_registration_or_rule_hash_rejected_on_replay(self):
        self.register()
        with transaction(self.ledger) as (connection, events):
            append(connection, events, 'foreign', 'issue', {'protocol_version': 1,
                'rules_sha256': RULES_SHA256, 'registration_hash': events[0]['event_hash']})
        with self.assertRaisesRegex(ValueError, 'Mixed'): workflow.export(self.ledger, self.root/'wrong')

    def test_cli_draft_is_unactivated_and_preserves_existing_output(self):
        path = self.root/'cli-draft.json'
        command = [sys.executable, '-B', '-m', 'prospective_v2', 'draft', '--parent', str(self.parent),
                   '--parent-sha256', self.parent_pin, '--mode', 'synthetic', '--clock', '2026-11-09T12:40:00Z', '--output', str(path)]
        result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr); original = path.read_bytes()
        self.assertEqual(read_json(path)['state'], 'unactivated'); self.assertFalse(self.ledger.exists())
        self.assertNotEqual(subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True).returncode, 0)
        self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__': unittest.main()
