"""Search and decision rules declared before challenger evaluation."""
from pathlib import Path

from premonition_fc.storage import digest, object_digest

PROTOCOL = {
    'version': 1,
    'validation_seasons': ['2021-22', '2022-23', '2023-24', '2024-25'],
    'excluded_from_fitting_and_tuning': '2025-26',
    'comparison_label': 'previously seen historical comparison',
    'candidates': [{'alpha': alpha, 'half_life_days': half_life}
                   for alpha in (.01, .1) for half_life in (None, 365.25)],
    'strength_selection': 'minimum pooled independent-model development log loss; candidate order breaks exact ties',
    'dc_fit': 'weighted training likelihood of low-score tau only; strengths identical to independent fit',
    'rho_cap': [-.2, .2], 'rho_positivity_margin': .999,
    'optimizer': {'method': 'L-BFGS-B', 'maxiter': 1000, 'ftol': 1e-12, 'gtol': 1e-8,
                  'intercept_bounds': [-4, 3], 'home_advantage_bounds': [-1.5, 1.5],
                  'raw_team_bounds': [-2, 2]},
    'penalty': 'alpha/2 times sum of centered attack and defensive-weakness squared; weighted mean per-match likelihood',
    'recency_anchor': 'latest training played date; weights 2**(-age_days/half_life_days)',
    'fallback': 'zero attack and defence for clubs absent from latest training season, including returning promoted clubs',
    'refitting': 'one fit per fold; validation-season scores never update strengths',
    'advance_rule': {'minimum_baseline_log_loss_improvement': .005,
                     'minimum_season_improvements': 3, 'maximum_draw_brier_increase': .005,
                     'tie_order': ['team_strength_poisson', 'team_strength_dc'],
                     'otherwise': 'retain baseline_poisson'},
    'scoring': {'order': ['H', 'D', 'A'], 'log_floor': 1e-15,
                'result_ties': 'H,D,A', 'score_ties': 'probability descending, home then away goals ascending',
                'reliability_edges': [0, .2, .4, .6, .8, 1], 'tail_tolerance': 1e-12},
    'prospective_trial': {'cohort': 'first 100 complete, permitted Premier League fixtures after a new issue-time freeze; no optional stopping',
                          'comparison': 'paired frozen baseline and selected challenger on identical slates',
                          'primary': 'mean paired natural-log-loss difference, challenger minus baseline',
                          'secondary': ['draw Brier', 'H/D/A recall and reliability with counts', 'first and top-three exact-score coverage'],
                          'decision': 'review after 100; advance only with log-loss improvement >=.005 and draw Brier increase <=.005; report uncertainty and no proof of superiority',
                          'freeze': 'code, fit, inputs, model choice, scoring and cohort before first eligible future kickoff; do not refit within trial',
                          'gates': 'access, freshness, retention/public-use permission and issue-time snapshots must pass first'},
    'provider_requests': 0,
}


def source_fingerprint():
    return object_digest({p.name: digest(p) for p in sorted(Path(__file__).parent.glob('*.py'))})


def check_protocol(value):
    if value['rules'] != PROTOCOL or value['rules_sha256'] != object_digest(PROTOCOL):
        raise ValueError('Protocol differs from the predeclared search')
