"""Chronological development, a sealed final fit, then a separate seen-year score."""
from datetime import datetime, timezone
import importlib.metadata
from pathlib import Path
import platform

from premonition_fc.cli import check_prepared, development_inputs, frozen_manifest
from premonition_fc.models import joined_targets
from premonition_fc.storage import code_fingerprint, digest, external_directory, object_digest, read_json, write_json

from .diagnostics import diagnose, score
from .models import HOLDOUT, fit_strengths, predict, validate_rows
from .protocol import PROTOCOL, check_protocol, source_fingerprint


def now():
    return datetime.now(timezone.utc).isoformat()


def paired_baseline(path, rows, targets):
    original = read_json(path)
    expected = {r['fixture_id']: r for r in rows}
    fields = ('season', 'home', 'away', 'played_date', 'issue_date_london')
    forecasts = []
    for r in original:
        reference = expected.get(r['fixture_id'])
        if reference is None or any(r[k] != reference[k] for k in fields):
            raise ValueError('Baseline fixture cohort or issue cutoff differs')
        clean = {k: v for k, v in r.items() if k not in
                 ('actual_home_goals', 'actual_away_goals', 'actual_result', 'predicted_result',
                  'result_correct', 'log_loss', 'top_score_correct')}
        clean['model'] = 'baseline_poisson' if r['model'] == 'poisson' else r['model']
        forecasts.append(clean)
    if {r['model'] for r in forecasts} != {'baseline_poisson', 'forest', 'frequencies'}:
        raise ValueError('Saved reference models differ')
    return score(forecasts, targets)


def recommend(metrics):
    base = metrics['baseline_poisson']
    rule = PROTOCOL['advance_rule']
    eligible = []
    evidence = {}
    for name in rule['tie_order']:
        candidate = metrics[name]
        improvement = base['pooled']['log_loss'] - candidate['pooled']['log_loss']
        season_wins = sum(candidate['seasons'][s]['log_loss'] < base['seasons'][s]['log_loss'] for s in PROTOCOL['validation_seasons'])
        brier_increase = candidate['pooled']['class_brier']['D'] - base['pooled']['class_brier']['D']
        passed = (improvement >= rule['minimum_baseline_log_loss_improvement'] and
                  season_wins >= rule['minimum_season_improvements'] and brier_increase <= rule['maximum_draw_brier_increase'])
        evidence[name] = {'baseline_log_loss_improvement': improvement, 'season_improvements': season_wins,
                          'draw_brier_increase': brier_increase, 'eligible': passed}
        if passed:
            eligible.append(name)
    winner = min(eligible, key=lambda m: metrics[m]['pooled']['log_loss']) if eligible else 'baseline_poisson'
    return {'model': winner, 'development_only': True, 'evidence': evidence, 'rules': rule}


def develop(args):
    protocol = read_json(args.protocol)
    check_protocol(protocol)
    rows, targets, metadata = development_inputs(args.prepared)
    validate_rows(rows, training=True)
    frozen_manifest(Path(args.baseline)/'frozen')
    if len(rows) != 1892:
        raise ValueError('Expected the original 1,892 development rows')
    output = external_directory(args.output, fresh=True)
    candidates = []
    for ci, settings in enumerate(PROTOCOL['candidates']):
        scored, folds = [], []
        for season in PROTOCOL['validation_seasons']:
            training = [r for r in rows if r['season'] < season]
            validation = [r for r in rows if r['season'] == season]
            if len(validation) != 380:
                raise ValueError('Development validation season is incomplete')
            fit = fit_strengths(training, joined_targets(training, [t for t in targets if t['fixture_id'] in {r['fixture_id'] for r in training}]), settings)
            forecasts = predict(fit, validation, 'development-validation')
            validation_targets = [t for t in targets if t['fixture_id'] in {r['fixture_id'] for r in validation}]
            scored.extend(score(forecasts, validation_targets))
            folds.append({'season': season, 'training': len(training), 'validation': len(validation),
                          'training_latest_date': fit['training_last_date'],
                          'first_issue_date': min(r['issue_date_london'] for r in validation),
                          'fit_sha256': object_digest(fit), 'rho': fit['rho'],
                          'rho_bounds': fit['rho_bounds'], 'optimizer': fit['optimizer'],
                          'fallback_fixture_count': sum(r['home_neutral_fallback'] or r['away_neutral_fallback'] for r in forecasts if r['model'] == 'team_strength_poisson')})
            write_json(output/f'candidate-{ci}'/f'{season}-fit.json', fit)
        metrics = diagnose(scored)
        write_json(output/f'candidate-{ci}'/'scored_validation.json', scored)
        write_json(output/f'candidate-{ci}'/'metrics.json', metrics)
        candidates.append({'index': ci, 'settings': settings, 'metrics': metrics, 'folds': folds})
        print('Completed candidate', ci, settings, flush=True)
    selected = min(candidates, key=lambda c: c['metrics']['team_strength_poisson']['pooled']['log_loss'])
    validation_rows = [r for r in rows if r['season'] in PROTOCOL['validation_seasons']]
    validation_targets = [t for t in targets if t['fixture_id'] in {r['fixture_id'] for r in validation_rows}]
    baseline_path = Path(args.baseline)/'development/scored_validation.json'
    baseline_scores = paired_baseline(baseline_path, validation_rows, validation_targets)
    chosen_scores = read_json(output/f"candidate-{selected['index']}"/'scored_validation.json')
    comparison = diagnose(baseline_scores + chosen_scores)
    selection = {'selected_index': selected['index'], 'settings': selected['settings'], 'candidates': candidates,
                 'recommendation': recommend(comparison), 'protocol_sha256': digest(args.protocol),
                 'rules_sha256': object_digest(PROTOCOL), 'code_fingerprint': source_fingerprint(),
                 'baseline_code_fingerprint': code_fingerprint(),
                 'development_features_sha256': metadata['files']['development_features.json'],
                 'development_targets_sha256': metadata['files']['development_targets.json'],
                 'baseline_validation_sha256': digest(baseline_path)}
    write_json(output/'selection.json', selection)
    write_json(output/'comparison_metrics.json', comparison)
    write_json(output/'paired_scored_validation.json', baseline_scores+chosen_scores)
    write_json(output/'run.json', {'completed_at_utc': now(), 'protocol_declared_at_utc': protocol['declared_at_utc'],
                                 'holdout_targets_opened': False, 'provider_requests': 0})
    print('Development selected:', selected['settings'], 'Trial recommendation:', selection['recommendation']['model'])


def freeze(args):
    protocol = read_json(args.protocol)
    check_protocol(protocol)
    rows, targets, metadata = development_inputs(args.prepared)
    selection_path = Path(args.development)/'selection.json'
    selection = read_json(selection_path)
    if (selection['code_fingerprint'] != source_fingerprint() or selection['protocol_sha256'] != digest(args.protocol) or
        any(selection[k+'_sha256'] != metadata['files'][k+'.json'] for k in ('development_features', 'development_targets'))):
        raise ValueError('Selection code, protocol or development inputs changed')
    output = external_directory(args.output, fresh=True)
    fitted = fit_strengths(rows, targets, selection['settings'])
    write_json(output/'fit.json', fitted)
    write_json(output/'freeze.json', {'frozen_at_utc': now(), 'comparison_label': PROTOCOL['comparison_label'],
               'code_fingerprint': source_fingerprint(), 'baseline_code_fingerprint': code_fingerprint(),
               'fit_sha256': digest(output/'fit.json'), 'selection_sha256': digest(selection_path),
               'protocol_sha256': digest(args.protocol), 'rules': PROTOCOL,
               'prepared_files': metadata['files'], 'pins': metadata['pins'],
               'recommendation': selection['recommendation'], 'training_rows': len(rows),
               'holdout_targets_opened': False, 'python': platform.python_version(),
               'packages': {k: importlib.metadata.version(k) for k in ('numpy', 'scipy', 'scikit-learn', 'threadpoolctl')}})
    print('Frozen strengths and correction from', len(rows), 'development rows; scoring targets unopened.')


def checked_fit(path):
    path = Path(path)
    meta = read_json(path/'freeze.json')
    if (meta['code_fingerprint'] != source_fingerprint() or meta['baseline_code_fingerprint'] != code_fingerprint() or
        meta['fit_sha256'] != digest(path/'fit.json') or meta['rules'] != PROTOCOL):
        raise ValueError('Frozen code, fit or rules changed')
    return read_json(path/'fit.json'), meta


def forecast(args):
    fit, freeze_meta = checked_fit(args.frozen)
    prepared, metadata = check_prepared(args.prepared)
    if metadata['files'] != freeze_meta['prepared_files'] or digest(prepared/'holdout_features.json') != metadata['files']['holdout_features.json']:
        raise ValueError('Prepared inputs differ from frozen experiment')
    rows = read_json(prepared/'holdout_features.json')
    if len(rows) != 380 or any(r['season'] != HOLDOUT for r in rows):
        raise ValueError('Expected original 380 comparison fixtures')
    predictions = predict(fit, rows, PROTOCOL['comparison_label'])
    output = external_directory(args.output, fresh=True)
    write_json(output/'predictions.json', predictions)
    write_json(output/'forecast_manifest.json', {'saved_at_utc': now(), 'freeze_sha256': digest(Path(args.frozen)/'freeze.json'),
               'predictions_sha256': digest(output/'predictions.json'), 'holdout_targets_opened': False,
               'comparison_label': PROTOCOL['comparison_label'], 'provider_requests': 0})
    print('Saved 380 forecasts per challenger before opening scoring targets.')


def evaluate(args):
    _, freeze_meta = checked_fit(args.frozen)
    forecasts = Path(args.forecasts)
    forecast_meta = read_json(forecasts/'forecast_manifest.json')
    if (forecast_meta['freeze_sha256'] != digest(Path(args.frozen)/'freeze.json') or
        forecast_meta['predictions_sha256'] != digest(forecasts/'predictions.json') or
        digest(args.targets) != freeze_meta['prepared_files']['holdout_targets.json']):
        raise ValueError('Forecast or scoring input hash changed')
    predictions = read_json(forecasts/'predictions.json')
    targets = read_json(args.targets)
    baseline = Path(args.baseline)
    _, baseline_meta = frozen_manifest(baseline/'frozen')
    if baseline_meta['holdout_target_file_sha256'] != digest(args.targets):
        raise ValueError('Baseline and challenger scoring cohorts differ')
    rows = [r for r in predictions if r['model'] == 'team_strength_poisson']
    baseline_scores = paired_baseline(baseline/'forecasts/predictions.json', rows, targets)
    scored = score(predictions, targets)+baseline_scores
    output = external_directory(args.output, fresh=True)
    write_json(output/'paired_scored_comparison.json', scored)
    write_json(output/'metrics.json', diagnose(scored))
    write_json(output/'evaluation_manifest.json', {'scored_at_utc': now(), 'comparison_label': PROTOCOL['comparison_label'],
               'forecast_manifest_sha256': digest(forecasts/'forecast_manifest.json'), 'target_sha256': digest(args.targets),
               'baseline_forecasts_sha256': digest(baseline/'forecasts/predictions.json'),
               'recommendation_unchanged_from_development': freeze_meta['recommendation'], 'provider_requests': 0})
    print('Scored paired previously seen historical comparison; no retuning.')
