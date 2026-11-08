"""Fixed trial settings; no retrospective search in the prospective workflow."""
from premonition_fc.storage import code_fingerprint, digest, object_digest
from model_iteration.protocol import source_fingerprint
from pathlib import Path

MODELS = ('form_poisson', 'team_strength_poisson')
RULES = {
    'version': 1, 'models': list(MODELS), 'team_settings': {'alpha': .01, 'half_life_days': 365.25},
    'form_alpha': .1, 'cohort_size': 100, 'outcome_order': ['H', 'D', 'A'],
    'log_floor': 1e-15, 'snapshot_max_age_hours': 24,
    'cohort_order': 'completion UTC then canonical fixture ID; first 100 eligible unique complete pairs',
    'postponed': 'preserve original issued pair pending; score original on completion',
    'cancelled': 'void outside settled denominators', 'reissues': 'display only; never replace trial pair',
    'primary': 'mean paired log loss: team minus form',
    'secondary': ['draw Brier', 'H/D/A recall and reliability with bin counts', 'first/top-three exact-score hit rates'],
    'uncertainty': {'unit': 'issue slate', 'method': 'paired percentile block bootstrap',
                    'resamples': 2000, 'seed': 1729, 'interval': .95},
    'decision': {'maximum_log_loss_difference': -.005, 'maximum_draw_brier_increase': .005},
    'review': 'only after 100 settled eligible pairs; freeze review cohort once; no optional stopping',
    'history': 'completed, available at cutoff, played London date strictly before cutoff London date',
    'fits': 'freeze both once; form inputs alone update from permitted results at each issue',
}


def fingerprints():
    return {'historical': code_fingerprint(), 'iteration': source_fingerprint(),
            'prospective': object_digest({p.name: digest(p) for p in sorted(Path(__file__).parent.glob('*.py'))})}
