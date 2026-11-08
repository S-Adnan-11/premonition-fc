from argparse import Namespace
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from scipy.optimize import check_grad
from scipy.stats import poisson

from model_iteration import experiment
from model_iteration.models import corrected_distribution, fit_strengths, objective, predict, rates, rho_bounds, tau_values
from model_iteration.protocol import PROTOCOL, check_protocol
from premonition_fc.models import poisson_distribution
from premonition_fc.storage import object_digest, read_json, write_json


def training():
    teams = ['alpha', 'beta', 'gamma', 'old']
    rows, targets = [], []
    for i in range(48):
        season = '2023-24' if i < 24 else '2024-25'
        pool = teams if i < 24 else teams[:3]
        home, away = pool[i % len(pool)], pool[(i+1) % len(pool)]
        rows.append({'fixture_id': str(i), 'season': season, 'home': home, 'away': away,
                     'played_date': '2024-01-01' if i < 24 else '2025-01-01',
                     'issue_date_london': '2024-01-01' if i < 24 else '2025-01-01'})
        targets.append({'fixture_id': str(i), 'home_goals': (2, 0, 1, 3)[i % 4], 'away_goals': (0, 0, 1, 2)[i % 4]})
    return rows, targets


def upcoming():
    return [{'fixture_id': 'future', 'season': '2025-26', 'home': 'alpha', 'away': 'promoted',
             'played_date': '2025-08-15', 'issue_date_london': '2025-08-15'}]


class StrengthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.targets = training()
        cls.fit = fit_strengths(cls.rows, cls.targets, PROTOCOL['candidates'][1])

    def test_analytic_gradient(self):
        rng = np.random.default_rng(1729)
        theta = rng.normal(0, .1, 10)
        hi, ai = np.array([0, 1, 2, 3]), np.array([2, 3, 0, 1])
        args = (hi, ai, np.array([2, 0, 1, 3]), np.array([0, 0, 1, 2]), np.ones(4)/4, .1)
        error = check_grad(lambda x: objective(x, *args)[0], lambda x: objective(x, *args)[1], theta)
        self.assertLess(error, 2e-6)

    def test_fit_is_deterministic_and_centered(self):
        repeated = fit_strengths(self.rows, self.targets, PROTOCOL['candidates'][1])
        self.assertEqual(self.fit, repeated)
        self.assertAlmostEqual(sum(self.fit['attack']), 0, places=13)
        self.assertAlmostEqual(sum(self.fit['defence']), 0, places=13)
        self.assertEqual(len(self.fit['training_fixture_ids']), 48)
        self.assertEqual(self.fit['recency_anchor'], '2025-01-01')

    def test_promoted_unseen_and_returning_clubs_are_neutral(self):
        unseen = rates(self.fit, 'alpha', 'promoted')
        returning = rates(self.fit, 'alpha', 'old')
        self.assertEqual(unseen, returning)
        self.assertEqual(unseen[2:], (False, True))
        self.assertEqual(rates(self.fit, 'new', 'other')[2:], (True, True))
        changed = deepcopy(self.fit)
        old = changed['teams'].index('old')
        changed['attack'][old], changed['defence'][old] = 99., 99.
        self.assertEqual(returning, rates(changed, 'alpha', 'old'))

    def test_missing_inputs_do_not_become_neutral(self):
        for name in (None, '', 1):
            with self.assertRaises(ValueError):
                rates(self.fit, 'alpha', name)
        rows, targets = training()
        targets[0]['home_goals'] = None
        with self.assertRaises(ValueError):
            fit_strengths(rows, targets, PROTOCOL['candidates'][0])
        rows[0]['home'] = ''
        with self.assertRaises(ValueError):
            fit_strengths(rows, self.targets, PROTOCOL['candidates'][0])

    def test_holdout_and_target_join_rejected(self):
        rows, targets = training()
        rows[0]['season'] = '2025-26'
        with self.assertRaisesRegex(ValueError, 'development'):
            fit_strengths(rows, targets, PROTOCOL['candidates'][0])
        with self.assertRaises(ValueError):
            fit_strengths(self.rows, self.targets[:-1], PROTOCOL['candidates'][0])

    def test_strict_cutoff_and_no_fitted_fixture_reuse(self):
        rows = upcoming()
        rows[0]['issue_date_london'] = '2025-01-01'
        with self.assertRaisesRegex(ValueError, 'strictly precede'):
            predict(self.fit, rows, 'test')
        rows[0] = dict(upcoming()[0], fixture_id=self.rows[0]['fixture_id'])
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            predict(self.fit, rows, 'test')

    def test_predictions_ignore_scores_and_form_and_match_pair_rates(self):
        rows = upcoming()
        before = predict(self.fit, rows, 'test')
        rows[0].update(home_goals=999, away_goals=0, features={'home_gf': 999})
        self.assertEqual(before, predict(self.fit, rows, 'test'))
        self.assertEqual(before[0]['home_mean'], before[1]['home_mean'])
        self.assertEqual(before[0]['away_mean'], before[1]['away_mean'])

    def test_rho_bounds_cover_all_training_and_neutral_pairs(self):
        lower, upper = rho_bounds(self.fit)
        for a, d in zip(self.fit['attack']+[0.], self.fit['defence']+[0.]):
            for aa, dd in zip(self.fit['attack']+[0.], self.fit['defence']+[0.]):
                h = np.exp(self.fit['intercept']+self.fit['home_advantage']+a+dd)
                away = np.exp(self.fit['intercept']+aa+d)
                for rho in (lower, upper, self.fit['rho']):
                    self.assertTrue((tau_values(h, away, rho) > 0).all())


class CorrectionTests(unittest.TestCase):
    def test_zero_is_exact_independence(self):
        for h, a in ((0, 0), (0, 2), (1.8, .7), (12, 20)):
            self.assertEqual(corrected_distribution(h, a, 0), poisson_distribution(h, a))

    def test_mass_marginals_outcomes_and_top_three_against_large_grid(self):
        for h, a, rho in ((1.4, 1.1, -.1), (2.3, .5, .1), (.01, 5., -.05), (12, 20, -.01)):
            with self.subTest(rates=(h, a, rho)):
                value = corrected_distribution(h, a, rho)
                grid = np.outer(poisson.pmf(np.arange(100), h), poisson.pmf(np.arange(100), a))
                grid[0, 0] *= 1-h*a*rho
                grid[0, 1] *= 1+h*rho
                grid[1, 0] *= 1+a*rho
                grid[1, 1] *= 1-rho
                self.assertTrue((grid >= 0).all())
                self.assertAlmostEqual(grid.sum(), 1, places=12)
                np.testing.assert_allclose(grid.sum(axis=1), poisson.pmf(np.arange(100), h), atol=2e-13, rtol=0)
                np.testing.assert_allclose(grid.sum(axis=0), poisson.pmf(np.arange(100), a), atol=2e-13, rtol=0)
                expected = [np.tril(grid, -1).sum(), np.trace(grid), np.triu(grid, 1).sum()]
                np.testing.assert_allclose(value['probabilities'], expected, atol=2e-12, rtol=0)
                ranked = sorted(((float(grid[i, j]), i, j) for i in range(100) for j in range(100)), key=lambda v: (-v[0], v[1], v[2]))[:3]
                self.assertEqual([(s['probability'], s['home_goals'], s['away_goals']) for s in value['scorelines']], ranked)
                self.assertLessEqual(value['tail_mass_bound'], 1e-12)
                self.assertTrue(value['top_three_certified'])

    def test_invalid_correction_fails_and_negative_rho_boosts_draws(self):
        for rho in (-2., 2., float('nan')):
            with self.assertRaises(ValueError):
                corrected_distribution(1.5, 1.2, rho)
        self.assertGreater(corrected_distribution(1.5, 1.2, -.1)['probabilities'][1], poisson_distribution(1.5, 1.2)['probabilities'][1])


class StageBoundaryTests(unittest.TestCase):
    def test_protocol_mutation_rejected(self):
        check_protocol({'rules': PROTOCOL, 'rules_sha256': object_digest(PROTOCOL)})
        modified = deepcopy(PROTOCOL)
        modified['candidates'].append({'alpha': 1, 'half_life_days': None})
        with self.assertRaises(ValueError):
            check_protocol({'rules': modified, 'rules_sha256': object_digest(modified)})

    def test_forecast_opens_no_scoring_targets(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            rows = [dict(upcoming()[0], fixture_id=str(i)) for i in range(380)]
            write_json(root/'holdout_features.json', rows)
            from premonition_fc.storage import digest
            files = {'holdout_features.json': digest(root/'holdout_features.json'), 'holdout_targets.json': 'sealed'}
            opened = []
            def guarded(path):
                opened.append(Path(path).name)
                if 'targets' in str(path):
                    raise AssertionError('Forecast opened scoring targets')
                return read_json(path)
            with patch.object(experiment, 'checked_fit', return_value=({}, {'prepared_files': files})), \
                 patch.object(experiment, 'check_prepared', return_value=(root, {'files': files})), \
                 patch.object(experiment, 'read_json', side_effect=guarded), \
                 patch.object(experiment, 'predict', return_value=[{'synthetic': True}]):
                write_json(root/'freeze.json', {})
                experiment.forecast(Namespace(frozen=root, prepared=root, output=root/'forecasts'))
            self.assertEqual(opened, ['holdout_features.json'])

    def test_decision_uses_declared_season_stability(self):
        def metric(loss, brier, seasons):
            return {'pooled': {'log_loss': loss, 'class_brier': {'D': brier}},
                    'seasons': {s: {'log_loss': v} for s, v in zip(PROTOCOL['validation_seasons'], seasons)}}
        metrics = {'baseline_poisson': metric(1, .2, [1]*4),
                   'team_strength_poisson': metric(.98, .201, [.9, .9, 1.1, 1.1]),
                   'team_strength_dc': metric(.99, .199, [.99]*4)}
        self.assertEqual(experiment.recommend(metrics)['model'], 'team_strength_dc')
        metrics['team_strength_dc']['pooled']['class_brier']['D'] = .21
        self.assertEqual(experiment.recommend(metrics)['model'], 'baseline_poisson')


if __name__ == '__main__':
    unittest.main()
