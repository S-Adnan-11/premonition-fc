"""Separate v2 registration, immutable issuance and attributed factual corrections."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import os
import json
import sqlite3
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from premonition_fc.storage import digest, external_directory, object_digest, write_json
from prospective_trial.contracts import (LONDON, clock, fields, history, identity, instant,
                                        live_gates, season_date, slate, stamp)
from prospective_trial.models import forecast_pair
from prospective_trial.protocol import fingerprints, runtime
from prospective_trial.qualification import reconcile
from prospective_trial.reporting import review_metrics
from prospective_trial.store import append, transaction
from prospective_trial.workflow import frozen, read_snapshot

from .protocol import IDENTITY, MODELS, OFFICIAL_HOSTS, RULES, RULES_SHA256, VERSION, fingerprint


def _hash(value):
    import re
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _outside(path):
    value = Path(path).resolve()
    if any((p/'.git').exists() for p in (value.parent, *value.parents)):
        raise ValueError('Cohort data belongs outside Git worktrees')
    return value


def parent_record(path, expected_sha256):
    """Authenticate the original v1 freeze without opening or rewriting its ledger."""
    path = _outside(path)
    events, actual = read_snapshot(path)
    if not _hash(expected_sha256) or actual != expected_sha256 or not isinstance(events, list):
        raise ValueError('Original parent export checksum differs')
    previous, seen = '0'*64, set()
    for seq, event in enumerate(events, 1):
        fields(event, ('seq', 'key', 'kind', 'payload', 'previous_hash', 'event_hash'))
        envelope = {k: v for k, v in event.items() if k != 'event_hash'}
        if type(event['seq']) is not int or event['seq'] != seq or event['previous_hash'] != previous or object_digest(envelope) != event['event_hash'] or event['key'] in seen:
            raise ValueError('Parent event chain failed')
        if event['payload'].get('protocol_version', 1) != 1:
            raise ValueError('Parent must be an unmixed legacy v1 record')
        previous = event['event_hash']; seen.add(event['key'])
    meta = frozen(events)  # Retain every native code, fit, runtime and rules check.
    if meta['rules']['version'] != 1 or meta['rules_sha256'] != object_digest(meta['rules']):
        raise ValueError('Parent rules identity failed')
    return events, meta


def _provenance(events, meta, checksum):
    return {'parent_export_sha256': checksum, 'parent_freeze_event_hash': events[0]['event_hash'],
            'parent_ledger_head': events[-1]['event_hash'], 'parent_rules_sha256': meta['rules_sha256'],
            'fit_sha256': meta['fit_sha256'], 'parent_code_fingerprints': meta['code_fingerprints'],
            'runtime': meta['runtime'], 'model_specifications': {key: meta['rules'][key]
                for key in ('models', 'form_alpha', 'team_settings', 'history', 'fits')}}


def draft(parent_path, parent_sha256, mode, controlled=None):
    """Prepare an unactivated proposal. Real preparation always uses the actual clock."""
    events, meta = parent_record(parent_path, parent_sha256)
    if mode != meta['mode']:
        raise ValueError('Parent and proposed cohort modes differ')
    at = clock(mode, controlled)
    return {'schema_version': IDENTITY+'.registration', 'protocol_version': VERSION,
            'state': 'unactivated', 'mode': mode, 'prepared_at_utc': stamp(at),
            'rules': deepcopy(RULES), 'rules_sha256': RULES_SHA256,
            'v2_code_sha256': fingerprint(), 'v1_code_fingerprints': fingerprints(), 'runtime': runtime(),
            'parent': _provenance(events, meta, parent_sha256),
            'required_activation_inputs': ['fresh complete future first slate', 'current complete result history',
                'independent official reference and hashed documents', 'valid operational approval in real mode',
                'separate new v2 ledger', 'explicit real registration before first issue and kickoff']}


def _draft(value, events, meta, checksum):
    fields(value, ('schema_version', 'protocol_version', 'state', 'mode', 'prepared_at_utc',
        'rules', 'rules_sha256', 'v2_code_sha256', 'v1_code_fingerprints', 'runtime', 'parent',
        'required_activation_inputs'))
    if value['schema_version'] != IDENTITY+'.registration' or value['protocol_version'] != VERSION or value['state'] != 'unactivated' or value['mode'] != meta['mode']:
        raise ValueError('Expected an unactivated v2 draft with the parent mode')
    if value['rules'] != RULES or value['rules_sha256'] != RULES_SHA256 or value['v2_code_sha256'] != fingerprint() or value['v1_code_fingerprints'] != fingerprints() or value['runtime'] != runtime():
        raise ValueError('Draft rules, code or runtime changed')
    if value['parent'] != _provenance(events, meta, checksum):
        raise ValueError('Original fit/model provenance differs from the draft')
    instant(value['prepared_at_utc'])


def metadata(events):
    if not events or events[0]['kind'] != 'registration':
        raise ValueError('This is not a separately registered v2 ledger')
    value = events[0]['payload']
    if value.get('protocol_version') != VERSION or value.get('rules_sha256') != RULES_SHA256 or value.get('rules') != RULES:
        raise ValueError('Mixed cohort versions or rules')
    if value['v2_code_sha256'] != fingerprint() or value['v1_code_fingerprints'] != fingerprints() or value['runtime'] != runtime():
        raise ValueError('Registered code or runtime changed')
    if object_digest(value['fit']) != value['parent']['fit_sha256']:
        raise ValueError('Registered numerical fit changed')
    registration = events[0]['event_hash']
    for event in events[1:]:
        payload = event['payload']
        if payload.get('protocol_version') != VERSION or payload.get('rules_sha256') != RULES_SHA256 or payload.get('registration_hash') != registration:
            raise ValueError('Mixed cohort event, registration or rules')
        if event['kind'] not in ('issue', 'facts', 'review', 'review_correction'):
            raise ValueError('Unknown v2 event kind')
    return value


def _ledger(path):
    """Reject a legacy or mixed database through an immutable read before any transaction."""
    path = _outside(path)
    if not path.is_file():
        raise ValueError('The separately registered v2 ledger does not exist')
    connection = sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True)
    try:
        events, previous = [], '0'*64
        for seq, key, kind, raw, parent, checksum in connection.execute('SELECT * FROM events ORDER BY seq'):
            event = {'seq': seq, 'key': key, 'kind': kind, 'payload': json.loads(raw), 'previous_hash': parent}
            if seq != len(events)+1 or parent != previous or object_digest(event) != checksum:
                raise ValueError('V2 ledger hash chain failed')
            event['event_hash'] = checksum; events.append(event); previous = checksum
        metadata(events)
    except sqlite3.Error as exc:
        raise ValueError('Not a registered v2 event database') from exc
    finally:
        connection.close()
    return path


def _append(connection, events, key, kind, payload):
    return append(connection, events, key, kind, dict(payload, protocol_version=VERSION,
        rules_sha256=RULES_SHA256, registration_hash=events[0]['event_hash']))


def _authority(url, mode, authority=None):
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    if parsed.scheme != 'https' or parsed.username or parsed.password or not host:
        raise ValueError('Official evidence needs an ordinary HTTPS source URL')
    if mode == 'real' and not any(host == h or host.endswith('.'+h) for h in OFFICIAL_HOSTS):
        raise ValueError('Evidence authority is outside the registered official sources')
    if mode == 'real' and authority is not None:
        expected = 'official_league' if host == 'premierleague.com' or host.endswith('.premierleague.com') else 'official_club'
        if authority != expected:
            raise ValueError('Declared authority kind differs from the official domain')


def _qualified(reference_path, past, source, meta, at, now, previous=None):
    reference_path = _outside(reference_path)
    reference, checksum = read_snapshot(reference_path)
    counts = reconcile(reference, reference_path.parent, past, source, meta['mode'], at, now,
                       previous, meta['eligible_history'])
    for document in reference['documents'].values():
        if document['kind'] in ('official_result', 'official_schedule'):
            _authority(document['url'], meta['mode'])
    return {'reference': reference, 'reference_sha256': checksum, 'counts': counts}


def _approval(path, mode, at, source_id):
    value = read_snapshot(path)[0] if path is not None else None
    checked = live_gates(value, mode, at)
    if mode == 'real' and checked['source_id'] != source_id:
        raise ValueError('Operational approval names a different source')
    return checked


def register(ledger, draft_path, parent_path, parent_sha256, fixtures_path, history_path,
             reference_path, controlled=None, approval_path=None):
    """Explicit activation; this is never invoked by draft preparation or export."""
    ledger = _outside(ledger)
    events, parent = parent_record(parent_path, parent_sha256)
    proposal, proposal_hash = read_snapshot(draft_path)
    _draft(proposal, events, parent, parent_sha256)
    source, source_hash = read_snapshot(fixtures_path)
    past, history_hash = read_snapshot(history_path)
    request = {'draft_sha256': proposal_hash, 'parent_export_sha256': parent_sha256,
               'first_fixture_sha256': source_hash, 'history_sha256': history_hash,
               'reference_sha256': digest(reference_path)}
    if ledger.exists():
        _ledger(ledger)
        with transaction(ledger) as (_, saved):
            original = metadata(saved)
            if original['request'] != request:
                raise ValueError('A registration cannot be replaced')
            return original
    at = clock(proposal['mode'], controlled)
    if instant(proposal['prepared_at_utc']) > at or instant(parent['frozen_at_utc']) >= at:
        raise ValueError('Registration must follow preparation and the original freeze')
    _approval(approval_path, proposal['mode'], at, parent['source_id'])
    qualified = _qualified(reference_path, past, source, parent, at, at)
    targets, omissions = slate(source, parent['mode'], at)
    if omissions or not targets:
        raise ValueError('Registration requires the complete future first slate')
    excluded = sorted({r['fixture_id'] for e in events if e['kind'] == 'issue' for r in e['payload']['fixtures']})
    if set(excluded) & {r['fixture_id'] for r in targets}:
        raise ValueError('Previously issued v1 fixtures cannot enter v2')
    bound = min(instant(r['kickoff_at_utc']) for r in targets)
    completed = clock(proposal['mode'], controlled)
    if completed >= bound or completed.astimezone(LONDON).date() != at.astimezone(LONDON).date():
        raise ValueError('Registration missed the first future kickoff or London date')
    _approval(approval_path, proposal['mode'], completed, parent['source_id'])
    _qualified(reference_path, past, source, parent, at, completed)
    if digest(reference_path) != request['reference_sha256']:
        raise ValueError('Reference changed during registration')
    payload = {**deepcopy(proposal), 'state': 'active', 'registered_at_utc': stamp(completed),
               'request': request, 'fit': deepcopy(parent['fit']), 'eligible_history': deepcopy(parent['eligible_history']),
               'source_id': parent['source_id'], 'excluded_v1_fixture_ids': excluded,
               'first_slate_id': source['slate_id'], 'first_fixture_ids': sorted(r['fixture_id'] for r in targets),
               'first_verified_kickoff_bound_utc': stamp(bound), 'qualification': qualified,
               'label': 'Synthetic v2 rehearsal' if parent['mode'] == 'synthetic' else 'Prospective cohort v2'}
    # Publish a closed SQLite file atomically. A failed first transaction never
    # leaves an empty ledger that blocks recovery, and an existing file is preserved.
    external_directory(ledger.parent)
    with TemporaryDirectory(prefix='cohort-registration-', dir=ledger.parent) as folder:
        candidate = Path(folder)/'registration.sqlite'
        with transaction(candidate, create=True) as (connection, saved):
            append(connection, saved, 'registration', 'registration', payload)
        try:
            os.link(candidate, ledger)
        except FileExistsError:
            _ledger(ledger)
            with transaction(ledger) as (_, saved):
                original = metadata(saved)
                if original['request'] != request:
                    raise ValueError('A concurrent registration cannot be replaced')
                return original
    return payload


def issue(ledger, fixtures_path, history_path, reference_path, controlled=None, approval_path=None):
    ledger = _ledger(ledger)
    source, source_hash = read_snapshot(fixtures_path)
    past, history_hash = read_snapshot(history_path)
    request = {'fixture_sha256': source_hash, 'history_sha256': history_hash,
               'reference_sha256': digest(reference_path)}
    with transaction(ledger) as (connection, events):
        meta = metadata(events)
        original = next((e for e in events if e['key'] == 'issue:'+source['slate_id']), None)
        if original:
            if original['payload']['request'] != request:
                raise ValueError('An original v2 issue cannot be replaced')
            return original['payload']
        at = clock(meta['mode'], controlled)
        if at <= instant(meta['registered_at_utc']):
            raise ValueError('V2 issuance must follow real registration')
        _approval(approval_path, meta['mode'], at, meta['source_id'])
        prior = [e['payload']['qualification']['reference'] for e in events if e['kind'] == 'issue']
        qualified = _qualified(reference_path, past, source, meta, at, at,
                                prior[-1] if prior else meta['qualification']['reference'])
        targets, omissions = slate(source, meta['mode'], at)
        eligible, excluded = history(past, meta['mode'], at)
        if omissions or not targets:
            raise ValueError('Pause the whole v2 slate on any omission')
        ids = {r['fixture_id'] for r in targets}
        known = {r['fixture_id'] for r in eligible}
        old = set(meta['excluded_v1_fixture_ids']) | {r['fixture_id'] for e in events if e['kind'] == 'issue' for r in e['payload']['fixtures']}
        if ids & (old | known):
            raise ValueError('V2 fixture was already issued or has a known result')
        if not prior and (source['slate_id'] != meta['first_slate_id'] or sorted(ids) != meta['first_fixture_ids']):
            raise ValueError('The first issued slate must match registration')
        forecasts, traces = forecast_pair(meta['fit'], targets, eligible, at.astimezone(LONDON).date().isoformat())
        completed = clock(meta['mode'], controlled)
        if completed >= min(instant(r['kickoff_at_utc']) for r in targets) or completed.astimezone(LONDON).date() != at.astimezone(LONDON).date():
            raise ValueError('V2 slate started or the shared London cutoff changed')
        _approval(approval_path, meta['mode'], completed, meta['source_id'])
        again = _qualified(reference_path, past, source, meta, at, completed,
                          prior[-1] if prior else meta['qualification']['reference'])
        if again['reference_sha256'] != request['reference_sha256']:
            raise ValueError('Reference changed during issuance')
        payload = {'request': request, 'issued_at_utc': stamp(completed), 'data_cutoff_at_utc': stamp(at),
                   'slate_id': source['slate_id'], 'fit_sha256': meta['parent']['fit_sha256'],
                   'shared_london_cutoff_date': at.astimezone(LONDON).date().isoformat(),
                   'fixtures': targets, 'forecasts': forecasts, 'feature_traces': traces,
                   'excluded_history': excluded, 'qualification': again}
        return _append(connection, events, 'issue:'+source['slate_id'], 'issue', payload)['payload']


def _issued(events):
    return {r['fixture_id']: (r, e) for e in events if e['kind'] == 'issue' for r in e['payload']['fixtures']}


def _latest(events):
    view = {}
    for event in events:
        if event['kind'] == 'facts':
            for fact in event['payload']['facts']:
                view[fact['result']['fixture_id']] = fact
    return view


def cohort(events):
    issued, latest = _issued(events), _latest(events)
    positions = sorted(issued, key=lambda key: (issued[key][1]['seq'], instant(issued[key][0]['kickoff_at_utc']), key))
    chosen, blocked = [], None
    for key in positions:
        status = latest.get(key, {}).get('result', {}).get('status', 'scheduled')
        if status in ('cancelled', 'awarded'):
            continue
        if status != 'completed':
            blocked = key; break
        chosen.append(key)
        if len(chosen) == RULES['cohort_size']:
            break
    return chosen, blocked


def progress(events):
    metadata(events)
    issued, latest = _issued(events), _latest(events)
    count = lambda statuses: sum(f['result']['status'] in statuses for f in latest.values())
    settled, void = count(('completed',)), count(('cancelled', 'awarded'))
    chosen, blocked = cohort(events)
    review = next((e for e in events if e['kind'] == 'review'), None)
    return {'protocol_version': VERSION, 'issued': len(issued), 'settled': settled, 'void': void,
            'pending': len(issued)-settled-void, 'review_required_count': RULES['cohort_size'],
            'closed_frontier_completed': len(chosen), 'blocked_fixture_id': blocked,
            'review_ready': len(chosen) == RULES['cohort_size'], 'review_frozen': review is not None,
            'integrity_notices': [e['payload']['review_impact'] for e in events
                                  if e['kind'] == 'facts' and e['payload']['review_impact'] is not None]}


def _documents(source, root, mode, observed, now):
    documents = source['documents']
    if not isinstance(documents, dict) or not documents:
        raise ValueError('Factual evidence documents are required')
    for doc in documents.values():
        fields(doc, ('path', 'sha256', 'url', 'authority', 'observed_at_utc', 'precision'))
        path = (root/doc['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file() or not _hash(doc['sha256']) or digest(path) != doc['sha256']:
            raise ValueError('Factual evidence bytes or path changed')
        if doc['authority'] not in RULES['source_policy']['authorities']:
            raise ValueError('Factual evidence must use a registered official authority')
        _authority(doc['url'], mode, doc['authority'])
        if not instant(doc['observed_at_utc']) <= observed <= now or not isinstance(doc['precision'], str) or not doc['precision'].strip():
            raise ValueError('Evidence observation/precision is missing or dishonest')
    return documents


def settle(ledger, snapshot_path, controlled=None):
    """Record verified facts. Observation instants are never completion instants."""
    ledger = _ledger(ledger)
    source, checksum = read_snapshot(snapshot_path)
    root = _outside(snapshot_path).parent
    with transaction(ledger) as (connection, events):
        meta = metadata(events)
        previous_delivery = next((e for e in events if e['key'] == 'facts:'+checksum), None)
        if previous_delivery:
            return progress(events)
        at = clock(meta['mode'], controlled)
        fields(source, ('schema_version', 'protocol_version', 'rules_sha256', 'mode', 'source_id',
            'observed_at_utc', 'reviewed_at_utc', 'reviewed_by', 'documents', 'updates'))
        if source['schema_version'] != IDENTITY+'.facts' or source['protocol_version'] != VERSION or source['rules_sha256'] != RULES_SHA256 or source['mode'] != meta['mode'] or source['source_id'] != meta['source_id']:
            raise ValueError('Mixed factual snapshot version, rules, mode or source')
        observed, reviewed = instant(source['observed_at_utc']), instant(source['reviewed_at_utc'])
        if not instant(meta['registered_at_utc']) <= observed <= reviewed <= at or not isinstance(source['reviewed_by'], str) or not source['reviewed_by'].strip():
            raise ValueError('Factual observation/review chronology is invalid')
        earlier = [instant(e['payload']['observed_at_utc']) for e in events if e['kind'] == 'facts']
        if earlier and observed < max(earlier):
            raise ValueError('Factual snapshots cannot move backward')
        docs = _documents(source, root, meta['mode'], observed, at)
        issued, latest = _issued(events), _latest(events)
        if not isinstance(source['updates'], list):
            raise ValueError('Factual updates must be a complete array')
        updates, changes = {}, []
        for row in source['updates']:
            fields(row, ('fixture_id', 'season', 'home', 'away', 'status', 'home_goals', 'away_goals',
                'played_date', 'available_at_utc', 'document', 'basis', 'supersedes', 'correction_reason'))
            key = identity(row)
            if key in updates or key not in issued or row['document'] not in docs:
                raise ValueError('Duplicate, unknown or unsupported factual fixture')
            original, issue_event = issued[key]
            if any(row[k] != original[k] for k in ('season', 'home', 'away')) or observed < instant(issue_event['payload']['issued_at_utc']):
                raise ValueError('Factual identity/time differs from original issue')
            doc = docs[row['document']]
            status = row['status']
            if status in ('completed', 'cancelled', 'awarded') and instant(doc['observed_at_utc']) < instant(issue_event['payload']['issued_at_utc']):
                raise ValueError('Final evidence observation predates the original issue')
            if status == 'completed':
                day = date.fromisoformat(row['played_date'])
                if day.isoformat() != row['played_date']:
                    raise ValueError('Played date must be a canonical ISO calendar date')
                season_date(row['season'], day)
                if any(type(row[g]) is not int or row[g] < 0 for g in ('home_goals', 'away_goals')) or row['basis'] not in ('sporting_completion', 'official_replay'):
                    raise ValueError('Final sporting completion needs integer scores and a verified basis')
                available = instant(row['available_at_utc'])
                if not instant(issue_event['payload']['issued_at_utc']) < available <= instant(doc['observed_at_utc']) or not instant(issue_event['payload']['issued_at_utc']).astimezone(LONDON).date() <= day <= available.astimezone(LONDON).date():
                    raise ValueError('Played date/result availability chronology failed')
            elif status in ('scheduled', 'postponed', 'unresolved', 'suspended', 'abandoned', 'cancelled', 'awarded'):
                if any(row[k] is not None for k in ('home_goals', 'away_goals', 'played_date', 'available_at_utc')):
                    raise ValueError('Pending or void facts cannot contain placeholder scores or dates')
                expected = 'official_cancellation' if status == 'cancelled' else 'administrative_award' if status == 'awarded' else 'awaiting_review'
                if row['basis'] != expected:
                    raise ValueError('Exceptional disposition basis differs from status')
            else:
                raise ValueError('Unknown factual status')
            result = {k: row[k] for k in ('fixture_id', 'season', 'home', 'away', 'status', 'home_goals', 'away_goals', 'played_date', 'available_at_utc', 'basis')}
            old = latest.get(key)
            changed = old is not None and old['result'] != result
            if changed:
                if row['supersedes'] != old['fact_sha256'] or not isinstance(row['correction_reason'], str) or not row['correction_reason'].strip():
                    raise ValueError('A changed fact requires its parent hash and correction reason')
                changes.append({'fixture_id': key, 'before': old['result'], 'after': result,
                                'parent_fact_sha256': row['supersedes'], 'reason': row['correction_reason']})
            elif row['supersedes'] is not None or row['correction_reason'] is not None:
                raise ValueError('Unchanged/new facts cannot invent a correction parent')
            fact = {'result': result, 'document': deepcopy(doc), 'reviewed_by': source['reviewed_by'],
                    'reviewed_at_utc': source['reviewed_at_utc'], 'supersedes': row['supersedes'],
                    'correction_reason': row['correction_reason']}
            fact['fact_sha256'] = object_digest(fact)
            # Reobserving an unchanged fact does not replace its correction identity.
            updates[key] = old if old is not None and not changed else fact
        if not issued or set(updates) != set(issued):
            raise ValueError('Facts must cover every issued identity exactly once')
        review = next((e for e in events if e['kind'] == 'review'), None)
        impact = None
        if review and changes:
            boundary_changes = [c['fixture_id'] for c in changes
                if (c['before']['status'] in ('cancelled', 'awarded')) != (c['after']['status'] in ('cancelled', 'awarded'))]
            affected = sorted(set(review['payload']['cohort_fixture_ids']) & {c['fixture_id'] for c in changes})
            if affected or boundary_changes:
                impact = {'original_review_event_hash': review['event_hash'], 'affected_cohort_fixture_ids': affected,
                          'disposition_boundary_fixture_ids': boundary_changes,
                          'effect': 'Original review retained; any corrected analysis must use the same cohort. A disposition boundary requires a separate amendment.'}
        payload = {'snapshot_sha256': checksum, 'observed_at_utc': source['observed_at_utc'],
                   'reviewed_at_utc': source['reviewed_at_utc'], 'recorded_at_utc': stamp(at),
                   'source_snapshot': source, 'facts': [updates[k] for k in sorted(updates)],
                   'changes': changes, 'review_impact': impact}
        _append(connection, events, 'facts:'+checksum, 'facts', payload)
        return progress(events)


def _metrics(events, ids):
    latest = _latest(events)
    if any(latest.get(key, {}).get('result', {}).get('status') != 'completed' for key in ids):
        raise ValueError('Frozen cohort has a changed disposition; a separate amendment is required')
    cohort_events = [{'payload': {'fixture_id': key, 'result': latest[key]['result']}} for key in ids]
    return review_metrics(events, cohort_events)


def review(ledger, controlled=None):
    ledger = _ledger(ledger)
    with transaction(ledger) as (connection, events):
        meta = metadata(events)
        original = next((e for e in events if e['kind'] == 'review'), None)
        if original:
            return original['payload']
        at = clock(meta['mode'], controlled)
        ids, blocked = cohort(events)
        if len(ids) != RULES['cohort_size']:
            raise ValueError('Review requires a closed 100-pair frontier; blocked='+str(blocked))
        latest = _latest(events)
        if any(instant(latest[key]['reviewed_at_utc']) > at for key in ids):
            raise ValueError('Review precedes verified facts')
        payload = _metrics(events, ids)
        payload.update(mode=meta['mode'], label=meta['label'], reviewed_at_utc=stamp(at),
                       cohort_fact_sha256={key: latest[key]['fact_sha256'] for key in ids})
        return _append(connection, events, 'review', 'review', payload)['payload']


def corrected_review(ledger, reason, controlled=None):
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('A corrected analysis needs an attributable reason')
    ledger = _ledger(ledger)
    with transaction(ledger) as (connection, events):
        meta = metadata(events)
        original = next((e for e in events if e['kind'] == 'review'), None)
        if original is None:
            raise ValueError('No frozen review exists')
        latest = _latest(events)
        ids = original['payload']['cohort_fixture_ids']
        facts = {key: latest[key]['fact_sha256'] for key in ids}
        if facts == original['payload']['cohort_fact_sha256']:
            raise ValueError('The frozen cohort facts have not changed')
        if any(e['kind'] == 'facts' and e['payload']['review_impact'] and e['payload']['review_impact']['disposition_boundary_fixture_ids'] for e in events):
            raise ValueError('Disposition boundary correction requires a separate amendment')
        key = 'review-correction:'+object_digest(facts)
        previous = next((e for e in events if e['key'] == key), None)
        if previous:
            return previous['payload']
        at = clock(meta['mode'], controlled)
        if any(instant(latest[identity]['reviewed_at_utc']) > at for identity in ids):
            raise ValueError('Corrected analysis precedes verified facts')
        payload = _metrics(events, ids)
        payload.update(original_review_event_hash=original['event_hash'], reviewed_at_utc=stamp(at),
            reason=reason, cohort_fact_sha256=facts, cohort_unchanged=True,
            impact={'original_paired_log_loss_difference': original['payload']['paired_log_loss_difference'],
                    'corrected_paired_log_loss_difference': payload['paired_log_loss_difference']})
        return _append(connection, events, key, 'review_correction', payload)['payload']


def export(ledger, output):
    ledger = _ledger(ledger)
    with transaction(ledger) as (_, events):
        meta = metadata(events)
        destination = external_directory(output, fresh=True)
        reviewed = next((e['payload'] for e in events if e['kind'] == 'review'), None)
        data = {'protocol_version': VERSION, 'mode': meta['mode'], 'label': meta['label'],
                'progress': progress(events), 'review': reviewed,
                'review_corrections': [e['payload'] for e in events if e['kind'] == 'review_correction']}
        write_json(destination/'summary.json', data)
        write_json(destination/'events.json', events)
        write_json(destination/'provenance.json', {'protocol_version': VERSION, 'rules_sha256': RULES_SHA256,
            'v2_code_sha256': meta['v2_code_sha256'], 'parent': meta['parent'], 'ledger_head': events[-1]['event_hash']})
        return data
