"""Count-supported diagnostics for saved, unrounded forecast probabilities."""
import math

import numpy as np

from premonition_fc.models import ORDER, outcome, validate_probabilities


def score(predictions, targets):
    lookup = {r['fixture_id']: r for r in targets}
    if len(lookup) != len(targets) or not predictions:
        raise ValueError('Scoring requires unique targets and nonempty forecasts')
    models = sorted({r['model'] for r in predictions})
    seen = set()
    result = []
    for row in predictions:
        key = (row['model'], row['fixture_id'])
        if key in seen or row['fixture_id'] not in lookup:
            raise ValueError('Scoring requires one-to-one fixture joins')
        seen.add(key)
        target = lookup[row['fixture_id']]
        hg, ag = target['home_goals'], target['away_goals']
        if any(type(g) is not int or g < 0 for g in (hg, ag)):
            raise ValueError('Missing or invalid scores cannot become draws')
        p = validate_probabilities([row['probabilities']])[0]
        actual = outcome(hg, ag)
        predicted = ORDER[int(np.argmax(p))]
        result.append(dict(row, actual_home_goals=hg, actual_away_goals=ag,
                           actual_result=actual, predicted_result=predicted,
                           result_correct=actual == predicted,
                           log_loss=-math.log(max(float(p[ORDER.index(actual)]), 1e-15))))
    if seen != {(m, f) for m in models for f in lookup}:
        raise ValueError('All models must cover exactly the target cohort')
    return result


def summary(rows):
    if not rows or len({r['fixture_id'] for r in rows}) != len(rows):
        raise ValueError('A diagnostic group requires one forecast per fixture')
    p = validate_probabilities([r['probabilities'] for r in rows])
    y = np.array([ORDER.index(r['actual_result']) for r in rows])
    picks = p.argmax(axis=1)
    onehot = np.eye(3)[y]
    confusion = [[int(np.sum((y == i) & (picks == j))) for j in range(3)] for i in range(3)]
    reliability = {}
    for j, label in enumerate(ORDER):
        bins = []
        for k in range(5):
            mask = (p[:, j] >= k / 5) & ((p[:, j] < (k + 1) / 5) if k < 4 else (p[:, j] <= 1))
            bins.append({'lower': k / 5, 'upper': (k + 1) / 5, 'count': int(mask.sum()),
                         'mean_probability': float(p[mask, j].mean()) if mask.any() else None,
                         'observed_frequency': float((y[mask] == j).mean()) if mask.any() else None})
        reliability[label] = bins
    classes = {}
    for j, label in enumerate(ORDER):
        mask = y == j
        n, predicted_n = int(mask.sum()), int((picks == j).sum())
        classes[label] = {'actual_count': n, 'predicted_count': predicted_n,
                          'recall': confusion[j][j] / n if n else None,
                          'precision': confusion[j][j] / predicted_n if predicted_n else None,
                          'log_loss': float(-np.log(np.maximum(p[mask, j], 1e-15)).mean()) if n else None}
    exact = None
    if all('scorelines' in r for r in rows):
        hits = []
        for r in rows:
            actual = (r['actual_home_goals'], r['actual_away_goals'])
            scores = [(s['home_goals'], s['away_goals']) for s in r['scorelines']]
            hits.append((actual == scores[0], actual in scores[:3]))
        exact = {'first_hits': sum(h[0] for h in hits), 'top_three_hits': sum(h[1] for h in hits),
                 'first_coverage': sum(h[0] for h in hits) / len(rows),
                 'top_three_coverage': sum(h[1] for h in hits) / len(rows),
                 'by_class': {label: {'count': classes[label]['actual_count'],
                     'first_hits': sum(h[0] for r, h in zip(rows, hits) if r['actual_result'] == label),
                     'top_three_hits': sum(h[1] for r, h in zip(rows, hits) if r['actual_result'] == label)} for label in ORDER}}
    return {'fixtures': len(rows), 'log_loss': float(-np.log(np.maximum(p[np.arange(len(y)), y], 1e-15)).mean()),
            'accuracy': float((picks == y).mean()), 'confusion_order': list(ORDER),
            'confusion_actual_rows_predicted_columns': confusion, 'classes': classes,
            'draw_top_picks': int((picks == 1).sum()), 'mean_draw_probability': float(p[:, 1].mean()),
            'observed_draw_rate': float((y == 1).mean()),
            'mean_draw_probability_on_draws': float(p[y == 1, 1].mean()) if (y == 1).any() else None,
            'class_brier': {label: float(((p[:, j] - onehot[:, j]) ** 2).mean()) for j, label in enumerate(ORDER)},
            'reliability': reliability, 'exact_score': exact}


def diagnose(rows):
    return {model: {'pooled': summary([r for r in rows if r['model'] == model]),
                    'seasons': {season: summary([r for r in rows if r['model'] == model and r['season'] == season])
                                for season in sorted({r['season'] for r in rows if r['model'] == model})}}
            for model in sorted({r['model'] for r in rows})}
