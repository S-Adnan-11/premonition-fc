from copy import deepcopy
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from model_iteration.models import fit_strengths
from premonition_fc.models import fit_models
from premonition_fc.features import matrix, prepare_features
from premonition_fc.storage import write_json
from prospective_trial.contracts import clock, history, instant, live_gates
from prospective_trial.models import fit_pair, fixtures
from prospective_trial.protocol import RULES
from prospective_trial.store import append, transaction
from prospective_trial.workflow import freeze, read_input
from fictional import history_snapshot


class FitTests(unittest.TestCase):
    def test_new_seasons_and_historical_guard(self):
        source = history_snapshot()
        eligible, _ = history(source, 'synthetic', instant('2026-11-09T12:00:00Z'))
        fit = fit_pair(eligible)
        self.assertTrue(all(key.startswith(('2025-26:', '2026-27:')) for key in fit['training_fixture_ids']))
        rows, _, _ = prepare_features(fixtures(eligible), fixtures(eligible))
        targets = [{k: r[k] for k in ('fixture_id','home_goals','away_goals')} for r in eligible if r['fixture_id'] in fit['training_fixture_ids']]
        with self.assertRaisesRegex(ValueError, 'development'):
            fit_strengths(rows, targets, RULES['team_settings'])

    def test_adapters_match_original_fits_on_old_seasons(self):
        eligible, _ = history(history_snapshot(2023), 'synthetic', instant('2023-11-09T12:00:00Z'))
        fit = fit_pair(eligible)
        rows, _, _ = prepare_features(fixtures(eligible), fixtures(eligible))
        targets = [{k: r[k] for k in ('fixture_id','home_goals','away_goals')} for r in eligible if r['fixture_id'] in fit['training_fixture_ids']]
        original = fit_strengths(rows, targets, RULES['team_settings'])
        for key in ('attack', 'defence', 'intercept', 'home_advantage', 'active_teams'):
            self.assertEqual(fit['strength'][key], original[key])
        models = fit_models(rows, targets, {'poisson': {'alpha': .1}, 'forest': {'min_samples_leaf': 15}})
        for side in ('home', 'away'):
            pipeline = getattr(models, side+'_poisson')
            state = fit['form'][side]
            x = matrix(rows)
            rates = np.exp(((x-state['mean'])/state['scale']) @ state['coefficients']+state['intercept'])
            np.testing.assert_allclose(rates, pipeline.predict(x), rtol=1e-14, atol=1e-14)

    def test_time_validation_and_conservative_midnight(self):
        with self.assertRaises(ValueError):
            instant('2026-10-25T01:30:00')
        with self.assertRaises(ValueError):
            clock('real', '2026-11-09T12:00:00Z')
        with self.assertRaises(ValueError):
            live_gates(None, 'real', instant('2026-11-09T12:00:00Z'))
        source = history_snapshot()
        source['results'][-1]['played_date'] = '2026-11-09'
        source['results'][-1]['availability_basis'] = 'confirmed_time'
        source['results'][-1]['available_at_utc'] = '2026-11-09T10:00:00Z'
        eligible, excluded = history(source, 'synthetic', instant('2026-11-09T12:00:00Z'))
        self.assertEqual(len(excluded), 1)
        self.assertNotIn(source['results'][-1]['fixture_id'], {r['fixture_id'] for r in eligible})
        source['results'][-1]['available_at_utc'] = '2026-11-09T13:00:00Z'
        with self.assertRaises(ValueError):
            history(source, 'synthetic', instant('2026-11-09T12:00:00Z'))

    def test_snapshot_and_score_validation(self):
        for mutate in (lambda s: s['results'].append(deepcopy(s['results'][0])),
                       lambda s: s['results'][0].update(home_goals=None),
                       lambda s: s['results'][0].update(home='changed'),
                       lambda s: s.update(observed_at_utc='2026-11-01T00:00:00Z'),
                       lambda s: s.update(version=True)):
            source = history_snapshot()
            mutate(source)
            with self.assertRaises(ValueError):
                history(source, 'synthetic', instant('2026-11-09T12:00:00Z'))

    def test_atomic_freeze_and_no_overwrite(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source, ledger = root/'history.json', root/'trial.sqlite'
            write_json(source, history_snapshot())
            args = (ledger, source, '2026-11-09T12:00:00Z', 'synthetic', '2026-11-09T12:00:00Z')
            first = freeze(*args)
            self.assertEqual(first, freeze(*args))
            with self.assertRaises(ValueError):
                freeze(ledger, source, '2026-11-09T11:00:00Z', 'synthetic', '2026-11-09T12:00:00Z')
            with transaction(ledger) as (connection, events):
                self.assertEqual(len(events), 1)
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute('DELETE FROM events')
            with self.assertRaises(RuntimeError):
                with transaction(ledger) as (connection, events):
                    append(connection, events, 'interrupted', 'test', {})
                    raise RuntimeError('simulated interruption')
            with transaction(ledger) as (_, events):
                self.assertEqual(len(events), 1)

    def test_json_ambiguity_rejected(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'bad.json'
            for content in ('{"a":1,"a":2}', '{"a":NaN}'):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    read_input(path)


if __name__ == '__main__':
    unittest.main()
