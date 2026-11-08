"""Regularized team rates and a matched, conditional Dixon-Coles correction."""
from datetime import date
import math

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import gammaln
from scipy.stats import poisson
from threadpoolctl import threadpool_limits

from premonition_fc.models import joined_targets, poisson_distribution, validate_probabilities

from .protocol import PROTOCOL

HOLDOUT = '2025-26'


def validate_rows(rows, *, training=False):
    ids = set()
    if not rows:
        raise ValueError('Empty fixture cohort')
    for r in rows:
        if any(not isinstance(r.get(k), str) or not r[k] for k in
               ('fixture_id', 'season', 'played_date', 'issue_date_london', 'home', 'away')):
            raise ValueError('Missing fixture identity, team or date')
        if r['fixture_id'] in ids or r['home'] == r['away']:
            raise ValueError('Duplicate fixture or identical teams')
        ids.add(r['fixture_id'])
        played, issue = date.fromisoformat(r['played_date']), date.fromisoformat(r['issue_date_london'])
        if issue > played:
            raise ValueError('Issue date follows played date')
        if training and r['season'] >= HOLDOUT:
            raise ValueError('Fitting accepts development seasons only')


def objective(theta, hi, ai, hg, ag, weights, alpha):
    """Mean per-match negative log likelihood; centered, identifiable effects."""
    n = (len(theta) - 2) // 2
    attack = theta[2:2+n] - theta[2:2+n].mean()
    defence = theta[2+n:] - theta[2+n:].mean()
    lh = theta[0] + theta[1] + attack[hi] + defence[ai]
    la = theta[0] + attack[ai] + defence[hi]
    hm, am = np.exp(lh), np.exp(la)
    value = np.dot(weights, hm - hg*lh + gammaln(hg+1) + am - ag*la + gammaln(ag+1))
    value += alpha / 2 * (attack @ attack + defence @ defence)
    eh, ea = weights*(hm-hg), weights*(am-ag)
    ga = np.bincount(hi, eh, minlength=n) + np.bincount(ai, ea, minlength=n) + alpha*attack
    gd = np.bincount(ai, eh, minlength=n) + np.bincount(hi, ea, minlength=n) + alpha*defence
    gradient = np.r_[eh.sum()+ea.sum(), eh.sum(), ga-ga.mean(), gd-gd.mean()]
    return float(value), gradient


def tau_values(hm, am, rho):
    if not np.isfinite([hm, am, rho]).all() or min(hm, am) < 0:
        raise ValueError('Nonfinite or negative rates/correction')
    values = np.array([1-hm*am*rho, 1+hm*rho, 1+am*rho, 1-rho])
    if (values <= 0).any():
        raise ValueError('Dixon-Coles low-score probabilities must be strictly positive')
    return values


def rho_bounds(fit):
    # Every fitted team and the neutral fallback, in every pairing, including
    # conservative self-pairings. Covers inactive historic teams as well.
    effects = list(zip(fit['attack'], fit['defence'])) + [(0., 0.)]
    hm, am = [], []
    for ah, dh in effects:
        for aa, da in effects:
            hm.append(math.exp(fit['intercept']+fit['home_advantage']+ah+da))
            am.append(math.exp(fit['intercept']+aa+dh))
    hm, am = np.array(hm), np.array(am)
    margin = PROTOCOL['rho_positivity_margin']
    lower = max(PROTOCOL['rho_cap'][0], float(max((-1/hm).max(), (-1/am).max()))*margin)
    upper = min(PROTOCOL['rho_cap'][1], float(min(1., (1/(hm*am)).min()))*margin)
    return lower, upper


def fit_strengths(rows, targets, settings):
    validate_rows(rows, training=True)
    if settings not in PROTOCOL['candidates']:
        raise ValueError('Settings are outside the declared search')
    ordered = joined_targets(rows, targets)
    if any(type(t.get(k)) is not int or t[k] < 0 for t in ordered for k in ('home_goals', 'away_goals')):
        raise ValueError('Missing or invalid training scores')
    teams = sorted({r[s] for r in rows for s in ('home', 'away')})
    index = {t: i for i, t in enumerate(teams)}
    hi, ai = (np.array([index[r[s]] for r in rows]) for s in ('home', 'away'))
    hg, ag = (np.array([t[s] for t in ordered], dtype=float) for s in ('home_goals', 'away_goals'))
    anchor = max(r['played_date'] for r in rows)
    ages = np.array([(date.fromisoformat(anchor)-date.fromisoformat(r['played_date'])).days for r in rows])
    half_life = settings['half_life_days']
    weights = np.ones(len(rows)) if half_life is None else np.exp2(-ages/half_life)
    weights /= weights.sum()
    initial = np.zeros(2+2*len(teams))
    initial[0] = np.log(max(float(weights @ ag), .1))
    initial[1] = np.clip(np.log(max(float(weights @ hg), .1))-initial[0], -1.5, 1.5)
    options = PROTOCOL['optimizer']
    bounds = [options['intercept_bounds'], options['home_advantage_bounds']] + [options['raw_team_bounds']]*(2*len(teams))
    with threadpool_limits(limits=1):
        result = minimize(objective, initial, args=(hi, ai, hg, ag, weights, settings['alpha']), jac=True,
                          method=options['method'], bounds=bounds,
                          options={k: options[k] for k in ('maxiter', 'ftol', 'gtol')})
    if not result.success or not np.isfinite(result.fun) or not np.isfinite(result.x).all():
        raise ArithmeticError('Team-strength optimization did not converge')
    n = len(teams)
    attack = result.x[2:2+n] - result.x[2:2+n].mean()
    defence = result.x[2+n:] - result.x[2+n:].mean()
    latest_season = max(r['season'] for r in rows)
    fit = {'teams': teams, 'active_teams': sorted({r[s] for r in rows if r['season'] == latest_season for s in ('home', 'away')}),
           'intercept': float(result.x[0]), 'home_advantage': float(result.x[1]),
           'attack': attack.tolist(), 'defence': defence.tolist(), 'settings': dict(settings),
           'training_fixture_ids': [r['fixture_id'] for r in rows], 'training_last_date': anchor,
           'recency_anchor': anchor, 'latest_training_season': latest_season,
           'optimizer': {'success': True, 'iterations': int(result.nit), 'objective': float(result.fun),
                         'max_abs_gradient': float(abs(result.jac).max())}}
    hm = np.exp(fit['intercept']+fit['home_advantage']+attack[hi]+defence[ai])
    am = np.exp(fit['intercept']+attack[ai]+defence[hi])
    coefficients = np.zeros(len(rows))
    coefficients[(hg == 0) & (ag == 0)] = -(hm*am)[(hg == 0) & (ag == 0)]
    coefficients[(hg == 0) & (ag == 1)] = hm[(hg == 0) & (ag == 1)]
    coefficients[(hg == 1) & (ag == 0)] = am[(hg == 1) & (ag == 0)]
    coefficients[(hg == 1) & (ag == 1)] = -1
    lower, upper = rho_bounds(fit)
    def loss(rho):
        tau = 1+rho*coefficients
        return float(-np.dot(weights, np.log(tau))) if (tau > 0).all() else float('inf')
    adjustment = minimize_scalar(loss, bounds=(lower, upper), method='bounded', options={'xatol': 1e-12})
    if not adjustment.success or not np.isfinite(adjustment.fun):
        raise ArithmeticError('Low-score optimization did not converge')
    rho = float(adjustment.x) if adjustment.fun < loss(0.) else 0.
    fit.update(rho=rho, rho_bounds=[lower, upper], dc_optimizer_success=True,
               dc_training_log_likelihood_gain=-loss(rho), low_score_training_count=int(np.sum((hg <= 1) & (ag <= 1))))
    return fit


def rates(fit, home, away):
    if not isinstance(home, str) or not home or not isinstance(away, str) or not away or home == away:
        raise ValueError('Missing or invalid team input')
    index = {t: i for i, t in enumerate(fit['teams'])}
    active = set(fit['active_teams'])
    def effects(team):
        if team not in active:
            return 0., 0., True
        i = index[team]
        return fit['attack'][i], fit['defence'][i], False
    ah, dh, fh = effects(home)
    aa, da, fa = effects(away)
    return (math.exp(fit['intercept']+fit['home_advantage']+ah+da),
            math.exp(fit['intercept']+aa+dh), fh, fa)


def corrected_distribution(hm, am, rho):
    tau = tau_values(hm, am, rho)
    independent = poisson_distribution(hm, am)
    if rho == 0:
        return independent
    c = rho*hm*am*math.exp(-hm-am)
    probabilities = np.array(independent['probabilities']) + [c, -2*c, c]
    validate_probabilities([probabilities])
    limit = independent['grid_max_goals']
    grid = np.outer(poisson.pmf(np.arange(limit+1), hm), poisson.pmf(np.arange(limit+1), am))
    grid[0, 0] *= tau[0]
    grid[0, 1] *= tau[1]
    grid[1, 0] *= tau[2]
    grid[1, 1] *= tau[3]
    tail = independent['tail_mass_bound']
    if abs(grid.sum()-1) > tail+2e-12 or (grid < 0).any():
        raise ArithmeticError('Corrected grid mass failed')
    grouped = np.array([np.tril(grid, -1).sum(), np.trace(grid), np.triu(grid, 1).sum()])
    if max(abs(grouped-probabilities)) > tail+2e-12:
        raise ArithmeticError('Corrected outcome/grid reconciliation failed')
    ranked = sorted(((float(grid[h, a]), h, a) for h in range(limit+1) for a in range(limit+1)),
                    key=lambda v: (-v[0], v[1], v[2]))[:3]
    if not tail < ranked[2][0] and tail != 0:
        raise ArithmeticError('Corrected top-three tail certification failed')
    return dict(independent, probabilities=probabilities.tolist(),
                scorelines=[{'home_goals': h, 'away_goals': a, 'probability': p} for p, h, a in ranked])


def predict(fit, rows, partition):
    validate_rows(rows)
    training_ids = set(fit['training_fixture_ids'])
    if any(r['fixture_id'] in training_ids for r in rows):
        raise ValueError('Prediction overlaps fitted fixtures')
    if fit['training_last_date'] >= min(r['issue_date_london'] for r in rows):
        raise ValueError('Training must strictly precede every issue date')
    output = []
    for row in rows:
        hm, am, fh, fa = rates(fit, row['home'], row['away'])
        base = {k: row[k] for k in ('fixture_id', 'season', 'played_date', 'home', 'away', 'issue_date_london')}
        base.update(historical=True, partition=partition, probability_order=['H', 'D', 'A'],
                    home_neutral_fallback=fh, away_neutral_fallback=fa)
        for model, rho in [('team_strength_poisson', 0.), ('team_strength_dc', fit['rho'])]:
            output.append(dict(base, model=model, rho=rho, **corrected_distribution(hm, am, rho)))
    return output
