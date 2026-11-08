"""Separate the launch fit, immutable issue record, and settlement ledger."""
import json
import hashlib
from pathlib import Path

from premonition_fc.storage import digest, external_directory, object_digest, write_json

from .contracts import LONDON, clock, fields, history, identity, instant, live_gates, slate, snapshot, stamp
from .models import fit_pair, forecast_pair
from .protocol import MODELS, RULES, fingerprints, runtime
from .store import append, transaction


def read_snapshot(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Nonfinite JSON number')
    raw = Path(path).read_bytes()
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=invalid), hashlib.sha256(raw).hexdigest()


def read_input(path):
    return read_snapshot(path)[0]


def frozen(events):
    if not events or events[0]['kind'] != 'freeze':
        raise ValueError('Missing trial freeze')
    value = events[0]['payload']
    if value['rules'] != RULES or value['code_fingerprints'] != fingerprints() or value['fit_sha256'] != object_digest(value['fit']) or value['runtime'] != runtime():
        raise ValueError('Frozen code, fit, runtime or rules changed')
    return value


def approve(path, mode, at, source_id):
    value = read_input(path) if path is not None else None
    checked = live_gates(value, mode, at)
    if mode == 'real' and checked['source_id'] != source_id:
        raise ValueError('Approval does not cover snapshot source')
    return checked


def freeze(ledger, history_path, cutoff, mode, controlled=None, approval_path=None):
    at = clock(mode, controlled)
    cutoff_time = instant(cutoff)
    if cutoff_time > at:
        raise ValueError('Fit cutoff is in the future')
    source, source_sha = read_snapshot(history_path)
    gates = approve(approval_path, mode, at, source['source_id'])
    eligible, excluded = history(source, mode, cutoff_time)
    request = {'history_sha256': source_sha, 'cutoff_at_utc': stamp(cutoff_time),
               'mode': mode, 'rules': RULES, 'code_fingerprints': fingerprints(), 'runtime': runtime()}
    with transaction(ledger, create=True) as (connection, events):
        if events:
            original = frozen(events)
            if original['request'] != request:
                raise ValueError('A trial freeze cannot be replaced')
            return original
        fit = fit_pair(eligible)
        completed = clock(mode, controlled)
        gates = approve(approval_path, mode, completed, source['source_id'])
        payload = {'request': request, 'mode': mode, 'label': 'Synthetic dry run' if mode == 'synthetic' else 'Prospective trial',
                   'frozen_at_utc': stamp(completed), 'cutoff_at_utc': stamp(cutoff_time), 'source_id': source['source_id'],
                   'source_snapshot': source, 'source_snapshot_sha256': source_sha, 'gates': gates,
                   'eligible_history': eligible, 'excluded_history': excluded, 'fit': fit, 'fit_sha256': object_digest(fit),
                   'rules': RULES, 'rules_sha256': object_digest(RULES), 'code_fingerprints': fingerprints(), 'runtime': runtime()}
        append(connection, events, 'freeze', 'freeze', payload)
        return payload


def issue(ledger, fixture_path, history_path, controlled=None, approval_path=None):
    source, fixture_sha = read_snapshot(fixture_path)
    past, history_sha = read_snapshot(history_path)
    request = {'fixture_snapshot_sha256': fixture_sha, 'history_snapshot_sha256': history_sha}
    with transaction(ledger) as (connection, events):
        freeze_meta = frozen(events)
        mode = freeze_meta['mode']
        at = clock(mode, controlled)
        key = 'issue:'+str(source.get('slate_id'))
        previous = next((e for e in events if e['key'] == key), None)
        if previous:
            if previous['payload']['request'] != request:
                raise ValueError('An issued slate cannot be replaced')
            return previous['payload']
        gates = approve(approval_path, mode, at, source['source_id'])
        if source['source_id'] != past['source_id'] or source['source_id'] != freeze_meta['source_id']:
            raise ValueError('Snapshot source changed')
        if at <= instant(freeze_meta['frozen_at_utc']):
            raise ValueError('Issue precedes frozen fit')
        targets, omissions = slate(source, mode, at)
        eligible, excluded = history(past, mode, at)
        known = {r['fixture_id']: r for r in eligible}
        if any(known.get(r['fixture_id']) != r for r in freeze_meta['eligible_history']):
            raise ValueError('Previously frozen results are missing or changed')
        issued = {r['fixture_id'] for e in events if e['kind'] == 'issue' for r in e['payload']['fixtures']}
        ids = {r['fixture_id'] for r in targets}
        if ids & issued or (ids | {r['fixture_id'] for r in omissions}) & set(known):
            raise ValueError('Fixture is already issued or has a known target result')
        predictions, traces = forecast_pair(freeze_meta['fit'], targets, eligible, at.astimezone(LONDON).date().isoformat())
        completed = clock(mode, controlled)
        if completed.astimezone(LONDON).date() != at.astimezone(LONDON).date():
            raise ValueError('London cutoff date changed during issuance')
        if source['earliest_verified_kickoff_at_utc'] is not None and completed >= instant(source['earliest_verified_kickoff_at_utc']):
            raise ValueError('Kickoff passed before the pair was saved')
        gates = approve(approval_path, mode, completed, source['source_id'])
        payload = {'request': request, 'mode': mode, 'label': freeze_meta['label'], 'slate_id': source['slate_id'],
                   'issued_at_utc': stamp(completed), 'data_cutoff_at_utc': stamp(at),
                   'shared_london_cutoff_date': at.astimezone(LONDON).date().isoformat(),
                   'frozen_event_hash': events[0]['event_hash'], 'fit_sha256': freeze_meta['fit_sha256'],
                   'fixture_snapshot': source, 'history_snapshot': past, 'gates': gates,
                   'fixtures': targets, 'omissions': omissions, 'excluded_history': excluded,
                   'forecasts': predictions, 'feature_traces': traces}
        append(connection, events, key, 'issue', payload)
        return payload


def progress(events):
    eligible = {r['fixture_id'] for e in events if e['kind'] == 'issue' for r in e['payload']['fixtures']}
    settled = {e['payload']['fixture_id'] for e in events if e['kind'] == 'settled'}
    void = {e['payload']['fixture_id'] for e in events if e['kind'] == 'void'}
    return {'eligible': len(eligible), 'settled': len(settled), 'pending': len(eligible-settled-void), 'void': len(void),
            'omitted': len({r['fixture_id'] for e in events if e['kind'] == 'issue' for r in e['payload']['omissions']}),
            'review_required_count': RULES['cohort_size'], 'review_ready': len(settled) >= RULES['cohort_size'],
            'review_frozen': any(e['kind'] == 'review' for e in events)}


def settle(ledger, snapshot_path, controlled=None):
    source, source_sha = read_snapshot(snapshot_path)
    with transaction(ledger) as (connection, events):
        meta = frozen(events)
        at = clock(meta['mode'], controlled)
        if any(e['key'] == 'settlement:'+source_sha for e in events):
            return progress(events)
        observed = snapshot(source, 'updates', meta['mode'], at)
        if source['source_id'] != meta['source_id']:
            raise ValueError('Settlement source changed')
        earlier = [instant(e['payload']['snapshot']['observed_at_utc']) for e in events if e['kind'] == 'settlement_snapshot']
        if earlier and observed < max(earlier):
            raise ValueError('Settlement observations cannot go backward')
        issued = {r['fixture_id']: (r, e) for e in events if e['kind'] == 'issue' for r in e['payload']['fixtures']}
        updates = {}
        existing = {e['payload']['fixture_id']: e for e in events if e['kind'] in ('settled', 'void')}
        for row in source['updates']:
            fields(row, ('fixture_id','season','home','away','status'), ('home_goals','away_goals','completed_at_utc'))
            key = identity(row)
            if key in updates or key not in issued:
                raise ValueError('Unknown or duplicate settlement fixture')
            original, issued_event = issued[key]
            if any(row[k] != original[k] for k in ('season', 'home', 'away')) or observed < instant(issued_event['payload']['issued_at_utc']):
                raise ValueError('Settlement identity/time differs from issue')
            status = row['status']
            if status == 'completed':
                fields(row, ('fixture_id','season','home','away','status','home_goals','away_goals','completed_at_utc'))
                completed = instant(row['completed_at_utc'])
                if any(type(row[g]) is not int or row[g] < 0 for g in ('home_goals','away_goals')) or not instant(original['kickoff_at_utc']) < completed <= observed:
                    raise ValueError('Missing/invalid score or completion chronology')
                review = next((e for e in events if e['kind'] == 'review'), None)
                if review and key not in existing and completed <= instant(review['payload']['cohort_last_completed_at_utc']):
                    raise ValueError('Late result contradicts the frozen review cohort; investigate source evidence')
            elif status in ('scheduled','postponed','cancelled'):
                fields(row, ('fixture_id','season','home','away','status'))
            else:
                raise ValueError('Unresolved fixture status')
            if key in existing:
                if existing[key]['payload']['result'] != row:
                    raise ValueError('A settled or void fixture cannot be revised or scored twice')
            updates[key] = row
        if set(updates) != set(issued) or not issued:
            raise ValueError('Settlement must cover every issued fixture, including pending/void')
        for key, row in sorted(updates.items()):
            if key not in existing and row['status'] in ('completed', 'cancelled'):
                kind = 'settled' if row['status'] == 'completed' else 'void'
                append(connection, events, 'terminal:'+key, kind, {'fixture_id': key, 'result': row,
                    'issue_event_hash': issued[key][1]['event_hash'], 'settlement_snapshot_sha256': source_sha})
        append(connection, events, 'settlement:'+source_sha, 'settlement_snapshot',
               {'snapshot_sha256': source_sha, 'snapshot': source, 'recorded_at_utc': stamp(at)})
        return progress(events)


def display_reissue(ledger, fixture_id, kickoff, controlled=None):
    with transaction(ledger) as (connection, events):
        meta = frozen(events)
        at = clock(meta['mode'], controlled)
        if instant(kickoff) <= at:
            raise ValueError('A display reissue requires a confirmed future kickoff')
        original = next((e for e in events if e['kind'] == 'issue' and any(r['fixture_id'] == fixture_id for r in e['payload']['fixtures'])), None)
        if original is None or any(e['kind'] in ('settled','void') and e['payload']['fixture_id'] == fixture_id for e in events):
            raise ValueError('Only an original pending pair can have a display reissue')
        if at < instant(original['payload']['issued_at_utc']):
            raise ValueError('Display annotation precedes original issue')
        payload = {'fixture_id': fixture_id, 'kickoff_at_utc': stamp(instant(kickoff)),
                   'original_issue_hash': original['event_hash'], 'display_only': True}
        return append(connection, events, 'display:'+fixture_id+':'+payload['kickoff_at_utc'], 'display_reissue', payload)['payload']


def review(ledger, controlled=None):
    from .reporting import review_metrics
    with transaction(ledger) as (connection, events):
        meta = frozen(events)
        at = clock(meta['mode'], controlled)
        original = next((e for e in events if e['kind'] == 'review'), None)
        if original:
            return original['payload']
        if not progress(events)['review_ready']:
            raise ValueError('Review requires 100 settled eligible fixture pairs')
        settled = sorted((e for e in events if e['kind'] == 'settled'),
                         key=lambda e: (instant(e['payload']['result']['completed_at_utc']), e['payload']['fixture_id']))[:RULES['cohort_size']]
        if at < max(instant(e['payload']['result']['completed_at_utc']) for e in settled):
            raise ValueError('Review precedes completed cohort')
        payload = review_metrics(events, settled)
        payload.update(mode=meta['mode'], label=meta['label'], reviewed_at_utc=stamp(at),
                       cohort_last_completed_at_utc=settled[-1]['payload']['result']['completed_at_utc'])
        append(connection, events, 'review', 'review', payload)
        return payload


def export(ledger, output):
    from .reporting import render_report
    with transaction(ledger) as (_, events):
        meta = frozen(events)
        destination = external_directory(output, fresh=True)
        reviewed = next((e['payload'] for e in events if e['kind'] == 'review'), None)
        data = {'mode': meta['mode'], 'label': meta['label'], 'progress': progress(events), 'review': reviewed}
        write_json(destination/'summary.json', data)
        write_json(destination/'events.json', events)
        write_json(destination/'fits.json', meta['fit'])
        write_json(destination/'provenance.json', {'label': meta['label'], 'mode': meta['mode'],
                   'ledger_head': events[-1]['event_hash'], 'code_fingerprints': meta['code_fingerprints'], 'runtime': meta['runtime'],
                   'fit_sha256': meta['fit_sha256'], 'rules': meta['rules'],
                   'frozen_snapshot_sha256': meta['source_snapshot_sha256'],
                   'issued_snapshot_hashes': [e['payload']['request'] for e in events if e['kind'] == 'issue'],
                   'provider_requests': 0, 'transport': 'not implemented'})
        (destination/'REPORT.md').write_text(render_report(data), encoding='utf-8')
        return data
