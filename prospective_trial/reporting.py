"""Fixed-size paired review and slate block-bootstrap uncertainty."""
import numpy as np

from model_iteration.diagnostics import diagnose, score
from .protocol import MODELS, RULES


def review_metrics(events, cohort):
    ids = [e['payload']['fixture_id'] for e in cohort]
    selected = set(ids)
    targets = [e['payload']['result'] for e in cohort]
    forecasts, slates = [], {}
    for event in events:
        if event['kind'] == 'issue':
            for prediction in event['payload']['forecasts']:
                if prediction['fixture_id'] in selected:
                    forecasts.append(prediction)
                    slates[prediction['fixture_id']] = event['payload']['slate_id']
    scored = score(forecasts, targets)
    metrics = diagnose(scored)
    by_model = {model: {r['fixture_id']: r for r in scored if r['model'] == model} for model in MODELS}
    groups = {}
    for fixture_id in ids:
        delta = by_model[MODELS[1]][fixture_id]['log_loss']-by_model[MODELS[0]][fixture_id]['log_loss']
        groups.setdefault(slates[fixture_id], []).append(delta)
    blocks = [groups[key] for key in sorted(groups)]
    uncertainty = {'method': RULES['uncertainty'], 'blocks': len(blocks), 'lower': None, 'upper': None}
    if len(blocks) >= 2:
        sums = np.array([sum(b) for b in blocks])
        counts = np.array([len(b) for b in blocks])
        rng = np.random.default_rng(RULES['uncertainty']['seed'])
        indices = rng.integers(0, len(blocks), size=(RULES['uncertainty']['resamples'], len(blocks)))
        bootstrap = sums[indices].sum(axis=1)/counts[indices].sum(axis=1)
        uncertainty.update(lower=float(np.quantile(bootstrap, .025)), upper=float(np.quantile(bootstrap, .975)))
    difference = metrics[MODELS[1]]['pooled']['log_loss']-metrics[MODELS[0]]['pooled']['log_loss']
    brier = metrics[MODELS[1]]['pooled']['class_brier']['D']-metrics[MODELS[0]]['pooled']['class_brier']['D']
    return {'cohort_fixture_ids': ids, 'fixtures': len(ids), 'metrics': metrics,
            'paired_log_loss_difference': difference, 'draw_brier_difference': brier, 'uncertainty': uncertainty,
            'advance_criterion_met': difference <= RULES['decision']['maximum_log_loss_difference'] and brier <= RULES['decision']['maximum_draw_brier_increase'],
            'limitation': 'Small paired cohort; slate bootstrap reflects sampling uncertainty, not proof of general superiority.'}


def render_report(data):
    progress = data['progress']
    lines = ['# '+data['label'], '',
             f"Eligible {progress['eligible']}; settled {progress['settled']}; pending {progress['pending']}; void {progress['void']}; omitted {progress['omitted']}.", '',
             'The original paired forecasts remain immutable. Postponed fixtures stay pending; cancelled fixtures are void. Display reissues are separate.', '']
    if data['review'] is None:
        lines.append('Decision review is not available until 100 eligible pairs settle and the review command freezes that cohort. No interim model comparison is generated.')
    else:
        review = data['review']
        lines += [f"Fixed review: {review['fixtures']} fixtures. Mean paired log-loss difference (team minus form): {review['paired_log_loss_difference']:.6f}.", '',
                  f"Paired 95% slate-bootstrap interval: {review['uncertainty']['lower']} to {review['uncertainty']['upper']}; {review['uncertainty']['blocks']} slates.", '',
                  '| Model | Log loss | Accuracy | Draw Brier | First score | Top three |', '| --- | --- | --- | --- | --- | --- |']
        for model in MODELS:
            value = review['metrics'][model]['pooled']
            lines.append(f"| {model} | {value['log_loss']:.6f} | {value['accuracy']:.4%} | {value['class_brier']['D']:.6f} | {value['exact_score']['first_coverage']:.4%} | {value['exact_score']['top_three_coverage']:.4%} |")
        lines += ['', '| Model | Class | n | Recall | Bin | Bin n | Mean p | Observed |', '| --- | --- | --- | --- | --- | --- | --- | --- |']
        for model in MODELS:
            value = review['metrics'][model]['pooled']
            for label in ('H','D','A'):
                for b in value['reliability'][label]:
                    lines.append(f"| {model} | {label} | {value['classes'][label]['actual_count']} | {value['classes'][label]['recall']} | {b['lower']}–{b['upper']} | {b['count']} | {b['mean_probability']} | {b['observed_frequency']} |")
        lines += ['', review['limitation'], '', 'Synthetic results exercise the workflow and do not establish real model performance.' if data['mode'] == 'synthetic' else 'Read the fixed cohort, probability and scoring rules alongside this review.']
    return '\n'.join(lines)+'\n'
