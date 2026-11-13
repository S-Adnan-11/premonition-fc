"""Offline reconciliation against an independent register, with durable pause decisions."""
from datetime import date, timedelta
import itertools
from pathlib import Path
import re
from urllib.parse import urlsplit

from premonition_fc.features import bucket_start
from premonition_fc.storage import digest, object_digest

from .contracts import LONDON, fields, history, identity, instant, season_date, slate, stamp
from .protocol import RULES
from .store import append, transaction


class QualificationPaused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code+': '+detail)


def pause(code, detail):
    raise QualificationPaused(code, detail)


def fresh(value, now):
    at = instant(value)
    if not at <= now <= at+timedelta(hours=RULES['snapshot_max_age_hours']):
        pause('EVIDENCE_STALE', 'Refresh observations and official verification before use')
    return at


def register(value, root, mode, asof, now):
    fields(value, ('version', 'mode', 'competition', 'source_id', 'observed_at_utc',
                   'history_start_season', 'history_through_london_date', 'history_complete', 'schedule_complete',
                   'season_clubs', 'fixtures', 'documents', 'amendments', 'season_audit'))
    if value['version'] != 1 or type(value['version']) is not int or value['mode'] != mode or value['competition'] != 'premier-league':
        pause('REFERENCE_INVALID', 'Reference version, mode or competition differs')
    observed = fresh(value['observed_at_utc'], now)
    if observed > asof or value['history_through_london_date'] != asof.astimezone(LONDON).date().isoformat():
        pause('RECENT_RESULTS_UNRECONCILED', 'Reference must cover the shared London cutoff date')
    if value['history_complete'] is not True or value['schedule_complete'] is not True:
        pause('REFERENCE_INCOMPLETE', 'Independent history and schedule attestations are required')
    documents = value['documents']
    if not isinstance(documents, dict) or not documents:
        pause('REFERENCE_INVALID', 'Reference documents are missing')
    for doc in documents.values():
        fields(doc, ('path', 'sha256', 'url', 'kind'))
        path = (root/doc['path']).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() not in ('.json', '.md', '.txt', '.html', '.pdf'):
            pause('REFERENCE_INVALID', 'Evidence must be a local document inside the reference bundle')
        if not re.fullmatch('[0-9a-f]{64}', str(doc['sha256'])) or not path.is_file() or digest(path) != doc['sha256']:
            pause('EVIDENCE_CHANGED', 'Referenced document bytes do not match their digest')
        url = urlsplit(doc['url'])
        if doc['kind'] not in ('official_schedule', 'official_result', 'historical_audit', 'season_audit') or (mode == 'real' and (url.scheme != 'https' or not url.hostname)):
            pause('REFERENCE_INVALID', 'Declare official schedule/result or preserved historical evidence')
    audit = value['season_audit']
    fields(audit, ('status', 'returned', 'expected', 'document'))
    if audit['document'] not in documents or documents[audit['document']]['kind'] != 'season_audit':
        pause('REFERENCE_INVALID', 'Preserve the separate full-season finding and its evidence')
    if audit['status'] not in ('PASS', 'FAIL') or any(type(audit[k]) is not int or audit[k] < 0 for k in ('returned', 'expected')):
        pause('REFERENCE_INVALID', 'Invalid full-season audit finding')
    # The season finding is carried as evidence; a failed future tail is not a history/slate failure.
    universe = set()
    if not isinstance(value['season_clubs'], dict) or not value['season_clubs']:
        pause('REFERENCE_INVALID', 'Explicit season membership is required')
    for season, clubs in value['season_clubs'].items():
        if not isinstance(clubs, list) or len(clubs) != len(set(clubs)) or len(clubs) < 2 or (mode == 'real' and len(clubs) != 20):
            pause('REFERENCE_INVALID', 'Season membership must enumerate every unique club')
        universe.update(':'.join((season, h, a)) for h, a in itertools.permutations(clubs, 2))
    if not isinstance(value['fixtures'], list):
        pause('REFERENCE_INVALID', 'Expected fixture register is missing')
    rows = {}
    for row in value['fixtures']:
        fields(row, ('fixture_id', 'season', 'home', 'away', 'status', 'document'),
               ('played_date', 'home_goals', 'away_goals', 'kickoff_at_utc', 'slate_id', 'reason'))
        key = identity(row)
        if key in rows or row['document'] not in documents:
            pause('REFERENCE_INVALID', 'Duplicate identity or missing document reference')
        kind = documents[row['document']]['kind']
        if row['status'] == 'completed':
            if kind not in ('official_result', 'historical_audit'):
                pause('RECENT_RESULTS_UNRECONCILED', 'Completed result needs result or audited historical evidence')
            day = date.fromisoformat(row['played_date'])
            season_date(row['season'], day)
            if any(type(row.get(g)) is not int or row[g] < 0 for g in ('home_goals', 'away_goals')):
                pause('RECENT_RESULTS_UNRECONCILED', 'Expected completed score is unresolved')
        elif row['status'] in ('scheduled', 'postponed', 'cancelled', 'unresolved'):
            if kind != 'official_schedule' or any(k in row for k in ('home_goals', 'away_goals', 'played_date')):
                pause('REFERENCE_INVALID', 'Unplayed fixtures need official schedule evidence and no scores')
            start = row['slate_id'].split(':')
            if len(start) != 2 or start[0] != row['season'] or bucket_start(start[1]) != start[1]:
                pause('REFERENCE_INVALID', 'Expected slate must be a Tuesday London bucket')
            if row.get('kickoff_at_utc') is not None:
                day = instant(row['kickoff_at_utc']).astimezone(LONDON).date()
                season_date(row['season'], day)
                if row['status'] == 'scheduled' and bucket_start(day.isoformat()) != start[1]:
                    pause('KICKOFF_UNVERIFIED', 'Reference kickoff disagrees with the assigned slate')
            if row['status'] in ('postponed', 'cancelled') and not row.get('reason', '').strip():
                pause('REFERENCE_INVALID', 'Official lifecycle exception needs a reason')
        else:
            pause('REFERENCE_INVALID', 'Unrecognized expected fixture status')
        rows[key] = row
    if set(rows) != universe:
        pause('REFERENCE_INCOMPLETE', 'Independent register must retain every ordered pairing in each declared season')
    years = sorted(int(s[:4]) for s in value['season_clubs'])
    current = asof.astimezone(LONDON).year-(asof.astimezone(LONDON).month < 7)
    if value['history_start_season'] != min(value['season_clubs']) or years != list(range(years[0], current+1)):
        pause('REFERENCE_INCOMPLETE', 'History seasons must be contiguous through the cutoff season')
    return rows, documents


def continuity(value, rows, previous):
    if previous is None:
        return
    old = {r['fixture_id']: r for r in previous['fixtures']}
    if set(old) != set(rows) or value['season_clubs'] != previous['season_clubs']:
        pause('EXPECTED_FIXTURE_MISSING', 'An expected identity or season membership disappeared from the register')
    if value['season_audit'] != previous['season_audit']:
        pause('EVIDENCE_CHANGED', 'The original full-season finding cannot be replaced')
    for key, before in old.items():
        after = rows[key]
        if before['status'] == 'completed':
            if any(after.get(k) != before.get(k) for k in ('status', 'played_date', 'home_goals', 'away_goals')):
                pause('RECENT_RESULTS_UNRECONCILED', 'Previously reconciled result changed: '+key)
        elif after['status'] != 'completed':
            names = ('status', 'slate_id', 'kickoff_at_utc')
            origin, target = ({k: r.get(k) for k in names} for r in (before, after))
            if origin != target and not any(a.get('fixture_id') == key and a.get('from') == origin and a.get('to') == target
                    and isinstance(a.get('reason'), str) and a['reason'].strip() and a.get('document') in value['documents']
                    and value['documents'][a['document']]['kind'] == 'official_schedule' for a in value['amendments']):
                pause('KICKOFF_UNVERIFIED', 'Schedule change needs a documented identity-preserving amendment: '+key)


def reconcile(value, root, past, fixtures, mode, asof, now, previous, frozen_history):
    rows, documents = register(value, root, mode, asof, now)
    if value['source_id'] != past['source_id'] or (fixtures is not None and value['source_id'] != fixtures['source_id']):
        pause('REFERENCE_INVALID', 'Source identity differs')
    continuity(value, rows, previous)
    try:
        eligible, _ = history(past, mode, asof)
        fresh(past['observed_at_utc'], now)
    except ValueError as error:
        pause('RECENT_RESULTS_UNRECONCILED', str(error))
    known = {r['fixture_id']: r for r in eligible}
    expected = {k: r for k, r in rows.items() if r['status'] == 'completed' and r['played_date'] < asof.astimezone(LONDON).date().isoformat()}
    if set(known) != set(expected):
        pause('RECENT_RESULTS_UNRECONCILED', 'Required history differs; missing='+str(sorted(set(expected)-set(known)))+' extra='+str(sorted(set(known)-set(expected))))
    for key, row in expected.items():
        if any(known[key][k] != row[k] for k in ('season', 'home', 'away', 'played_date', 'home_goals', 'away_goals')):
            pause('RECENT_RESULTS_UNRECONCILED', 'Required result differs: '+key)
    if any(known.get(r['fixture_id']) != r for r in frozen_history):
        pause('RECENT_RESULTS_UNRECONCILED', 'Frozen history is missing or changed')
    for key, row in rows.items():
        if row['status'] in ('scheduled', 'unresolved'):
            kickoff = row.get('kickoff_at_utc')
            if (kickoff is not None and instant(kickoff) <= asof) or (kickoff is None and row['slate_id'].split(':')[1] <= bucket_start(asof.astimezone(LONDON).date().isoformat())):
                pause('RECENT_RESULTS_UNRECONCILED', 'Past fixture has no reconciled result or official exception: '+key)
    if fixtures is None:
        return {'history_count': len(expected), 'slate_id': None, 'fixture_count': 0}
    slate_id = fixtures['slate_id']
    wanted = {k: r for k, r in rows.items() if r.get('slate_id') == slate_id and r['status'] != 'completed'}
    if not wanted:
        pause('EXPECTED_FIXTURE_MISSING', 'No independently expected fixtures in the slate')
    if any(r['status'] != 'scheduled' or r.get('kickoff_at_utc') is None for r in wanted.values()):
        pause('KICKOFF_UNVERIFIED', 'Every expected fixture needs a verified scheduled kickoff')
    actual_ids = [r['fixture_id'] for r in fixtures['fixtures']]
    if set(actual_ids) != set(wanted) or len(actual_ids) != len(set(actual_ids)) or fixtures['omissions'] or set(fixtures['expected_fixture_ids']) != set(wanted):
        pause('EXPECTED_FIXTURE_MISSING', 'Pause the whole slate; missing, extra, duplicate or omitted expected fixture')
    for row in fixtures['fixtures']:
        expected_row = wanted[row['fixture_id']]
        if any(row[k] != expected_row[k] for k in ('season', 'home', 'away')) or instant(row['kickoff_at_utc']) != instant(expected_row['kickoff_at_utc']):
            pause('KICKOFF_UNVERIFIED', 'Saved kickoff or identity differs from official register: '+row['fixture_id'])
    try:
        slate(fixtures, mode, asof)
        fresh(fixtures['observed_at_utc'], now)
        if now >= min(instant(r['kickoff_at_utc']) for r in wanted.values()):
            pause('SLATE_STARTED', 'The earliest verified kickoff has passed; do not backfill')
    except ValueError as error:
        if isinstance(error, QualificationPaused):
            raise
        pause('KICKOFF_UNVERIFIED', str(error))
    return {'history_count': len(expected), 'slate_id': slate_id, 'fixture_count': len(wanted)}


def qualify(reference_path, decisions_path, past, fixtures, mode, asof, now, *, previous=None, frozen_history=(), expected_sha=None):
    """Persist a scoped decision before returning, including on a rejected transaction."""
    from .workflow import read_snapshot
    if reference_path is None or decisions_path is None:
        raise QualificationPaused('QUALIFICATION_REQUIRED', 'Supply the independent reference and separate decision ledger')
    root = Path(reference_path).resolve().parent
    if Path(decisions_path).resolve() == Path(reference_path).resolve():
        raise ValueError('Decision ledger must be separate from its inputs')
    read_error = None
    try:
        reference, reference_sha = read_snapshot(reference_path)
    except (ValueError, OSError) as failure:
        reference, reference_sha, read_error = {}, None, failure
    payload = {'mode': mode, 'stage': 'fit' if fixtures is None else 'slate',
               'recorded_at_utc': stamp(now), 'cutoff_at_utc': stamp(asof),
               'reference_sha256': reference_sha, 'reference': reference,
               'history_sha256': object_digest(past), 'fixtures_sha256': object_digest(fixtures),
               'slate_id': None if fixtures is None else fixtures.get('slate_id')}
    error = None
    try:
        if read_error is not None:
            pause('REFERENCE_INVALID', str(read_error))
        if any((p/'.git').exists() for p in (root, *root.parents)):
            pause('REFERENCE_INVALID', 'Reference evidence belongs outside Git worktrees')
        if expected_sha is not None and expected_sha != reference_sha:
            pause('EVIDENCE_CHANGED', 'Reference changed during fitting or prediction')
        if asof > now:
            pause('REFERENCE_INVALID', 'Cutoff is in the future')
        if fixtures is not None and now.astimezone(LONDON).date() != asof.astimezone(LONDON).date():
            pause('CUTOFF_DATE_CHANGED', 'The shared London cutoff date changed during prediction')
        payload['counts'] = reconcile(reference, root, past, fixtures, mode, asof, now, previous, frozen_history)
        payload.update(status='PASS', reason_code=None, reason=None)
    except (ValueError, KeyError, TypeError, OSError) as failure:
        error = failure if isinstance(failure, QualificationPaused) else QualificationPaused('REFERENCE_INVALID', str(failure))
        payload.update(status='PAUSED', reason_code=error.code, reason=str(error))
    bounds = []
    for source in (reference.get('fixtures', []) if isinstance(reference, dict) else [], [] if fixtures is None else fixtures.get('fixtures', [])):
        if not isinstance(source, list):
            continue
        for row in source:
            if isinstance(row, dict) and row.get('slate_id', payload['slate_id']) == payload['slate_id'] and row.get('kickoff_at_utc'):
                try:
                    bounds.append(instant(row['kickoff_at_utc']))
                except ValueError:
                    pass
    payload['earliest_known_kickoff_at_utc'] = stamp(min(bounds)) if bounds else None
    payload['recorded_before_known_kickoff'] = now < min(bounds) if bounds else None
    with transaction(decisions_path, create=True) as (connection, events):
        event = append(connection, events, 'qualification:'+object_digest(payload), 'qualification', payload)
    if error is not None:
        raise error
    return {'event_hash': event['event_hash'], 'decision': payload}
