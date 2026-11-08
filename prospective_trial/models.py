"""As-of adapters reusing frozen historical probability and objective mathematics."""
from datetime import date
import warnings

import numpy as np
from scipy.optimize import minimize
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from premonition_fc.data import Fixture
from premonition_fc.features import FEATURES, matrix, prepare_features, trace
from premonition_fc.models import poisson_distribution
from model_iteration.models import objective, rates
from model_iteration.protocol import PROTOCOL

from .protocol import RULES


def fixtures(rows):
    return [Fixture(r['season'], r['played_date'], r['home'], r['away'], r['home_goals'], r['away_goals']) for r in rows]


def fit_pair(history):
    matches = fixtures(history)
    rows, _, excluded = prepare_features(matches, matches)
    if not rows:
        raise ValueError('No training rows remain after form warm-up')
    lookup = {r['fixture_id']: r for r in history}
    target = [lookup[r['fixture_id']] for r in rows]
    x = matrix(rows)
    form = {}
    with threadpool_limits(limits=1), warnings.catch_warnings():
        warnings.simplefilter('error', ConvergenceWarning)
        for side in ('home', 'away'):
            estimator = make_pipeline(StandardScaler(), PoissonRegressor(alpha=RULES['form_alpha'], max_iter=1000, tol=1e-10, solver='lbfgs'))
            estimator.fit(x, [r[side+'_goals'] for r in target])
            scaler, model = estimator.steps[0][1], estimator.steps[1][1]
            form[side] = {'mean': scaler.mean_.tolist(), 'scale': scaler.scale_.tolist(),
                          'coefficients': model.coef_.tolist(), 'intercept': float(model.intercept_)}
    teams = sorted({r[s] for r in rows for s in ('home', 'away')})
    index = {t: i for i, t in enumerate(teams)}
    hi, ai = (np.array([index[r[s]] for r in rows]) for s in ('home', 'away'))
    hg, ag = (np.array([r[s+'_goals'] for r in target], dtype=float) for s in ('home', 'away'))
    anchor = max(r['played_date'] for r in rows)
    ages = np.array([(date.fromisoformat(anchor)-date.fromisoformat(r['played_date'])).days for r in rows])
    weights = np.exp2(-ages/RULES['team_settings']['half_life_days'])
    weights /= weights.sum()
    initial = np.zeros(2+2*len(teams))
    initial[0] = np.log(max(float(weights @ ag), .1))
    initial[1] = np.clip(np.log(max(float(weights @ hg), .1))-initial[0], -1.5, 1.5)
    options = PROTOCOL['optimizer']
    bounds = [options['intercept_bounds'], options['home_advantage_bounds']]+[options['raw_team_bounds']]*(2*len(teams))
    with threadpool_limits(limits=1):
        result = minimize(objective, initial, args=(hi, ai, hg, ag, weights, RULES['team_settings']['alpha']),
                          jac=True, method=options['method'], bounds=bounds,
                          options={k: options[k] for k in ('maxiter', 'ftol', 'gtol')})
    if not result.success or not np.isfinite(result.x).all():
        raise ArithmeticError('Team-strength fit failed to converge')
    n = len(teams)
    latest = max(r['season'] for r in rows)
    strength = {'teams': teams, 'active_teams': sorted({r[s] for r in rows if r['season'] == latest for s in ('home', 'away')}),
                'intercept': float(result.x[0]), 'home_advantage': float(result.x[1]),
                'attack': (result.x[2:2+n]-result.x[2:2+n].mean()).tolist(),
                'defence': (result.x[2+n:]-result.x[2+n:].mean()).tolist(),
                'settings': RULES['team_settings'], 'training_last_date': anchor,
                'optimizer_success': True, 'optimizer_iterations': int(result.nit)}
    return {'form': form, 'strength': strength, 'training_fixture_ids': [r['fixture_id'] for r in rows],
            'eligible_history_ids': [r['fixture_id'] for r in history], 'warmup_exclusions': excluded,
            'feature_columns': list(FEATURES)}


def forecast_pair(fit, targets, history, issue_date):
    output, traces = [], []
    past = fixtures(history)
    for target in targets:
        kickoff_date = target['played_date']
        fixture = Fixture(target['season'], kickoff_date, target['home'], target['away'])
        detail = trace(past, fixture, issue_date)
        traces.append(detail)
        x = matrix([detail])[0]
        form_means = []
        for side in ('home', 'away'):
            state = fit['form'][side]
            form_means.append(float(np.exp(((x-np.array(state['mean']))/np.array(state['scale'])) @ np.array(state['coefficients'])+state['intercept'])))
        hm, am, fh, fa = rates(fit['strength'], target['home'], target['away'])
        base = {k: target[k] for k in ('fixture_id', 'season', 'home', 'away', 'played_date')}
        for name, h, a in [('form_poisson', *form_means), ('team_strength_poisson', hm, am)]:
            output.append(dict(base, model=name, probability_order=['H','D','A'], issue_date_london=issue_date,
                               home_neutral_fallback=fh if name == 'team_strength_poisson' else False,
                               away_neutral_fallback=fa if name == 'team_strength_poisson' else False,
                               **poisson_distribution(h, a)))
    return output, traces
