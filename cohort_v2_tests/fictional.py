"""Fictional full-census v2 inputs; no actual clubs, results or provider data."""
from copy import deepcopy
from datetime import datetime, timedelta
import itertools

from premonition_fc.storage import digest, object_digest, write_json
from prospective_tests.fictional import envelope, fixture_slates, history_snapshot
from prospective_v2.protocol import IDENTITY, RULES_SHA256


def scenario(root, count=101):
    past = history_snapshot()
    slates = fixture_slates(count)
    for source in slates:
        source['omissions'] = []
        source['expected_fixture_ids'] = [r['fixture_id'] for r in source['fixtures']]
    clubs = sorted({r[s] for source in slates for r in source['fixtures'] for s in ('home', 'away')}
                  | {r[s] for r in past['results'] for s in ('home', 'away')})
    documents = {}
    for name, kind in [('history', 'historical_audit'), ('schedule', 'official_schedule'), ('audit', 'season_audit')]:
        path = root/(name+'.txt'); path.write_text('Fictional '+name+' source.\n')
        documents[name] = {'path': path.name, 'sha256': digest(path), 'kind': kind, 'url': 'https://example.test/'+name}
    seasons = {season: sorted({r[s] for r in past['results'] if r['season'] == season for s in ('home', 'away')})
               for season in sorted({r['season'] for r in past['results']})}
    seasons['2026-27'] = clubs
    fixtures = {}
    for season, teams in seasons.items():
        for home, away in itertools.permutations(teams, 2):
            key = ':'.join((season, home, away))
            fixtures[key] = {'fixture_id': key, 'season': season, 'home': home, 'away': away,
                'status': 'scheduled', 'slate_id': '2026-27:2027-06-22',
                'kickoff_at_utc': '2027-06-25T15:00:00Z', 'document': 'schedule'}
    for row in past['results']:
        fixtures[row['fixture_id']] = {k: row[k] for k in ('fixture_id', 'season', 'home', 'away',
            'status', 'played_date', 'home_goals', 'away_goals')} | {'document': 'history'}
    for source in slates:
        for row in source['fixtures']:
            fixtures[row['fixture_id']] = {k: row[k] for k in ('fixture_id', 'season', 'home', 'away',
                'status', 'kickoff_at_utc')} | {'slate_id': source['slate_id'], 'document': 'schedule'}
    reference = {'version': 1, 'mode': 'synthetic', 'competition': 'premier-league',
        'source_id': past['source_id'], 'observed_at_utc': past['observed_at_utc'],
        'history_start_season': min(seasons), 'history_through_london_date': '2026-11-09',
        'history_complete': True, 'schedule_complete': True, 'season_clubs': seasons,
        'fixtures': list(fixtures.values()), 'documents': documents, 'amendments': [],
        'season_audit': {'status': 'FAIL', 'returned': 17, 'expected': len(fixtures), 'document': 'audit'}}
    write_json(root/'history.json', past); write_json(root/'reference.json', reference)
    paths = []
    for i, source in enumerate(slates):
        path = root/f'slate-{i}.json'; write_json(path, source); paths.append(path)
    return past, slates, reference, paths


def fact_snapshot(root, slates, *, pending_first=False, void_last=False, events=None):
    fixtures = [r for source in slates for r in source['fixtures']]
    last = max(datetime.fromisoformat(r['kickoff_at_utc'].replace('Z', '+00:00')) for r in fixtures)
    observed = last+timedelta(days=3)
    document = root/'results.txt'; document.write_text('Fictional official final scores and dates.\n')
    updates = []
    for i, row in enumerate(fixtures):
        pending = pending_first and i == 0
        cancelled = void_last and i == len(fixtures)-1
        updates.append({key: row[key] for key in ('fixture_id', 'season', 'home', 'away')} | {
            'status': 'postponed' if pending else 'cancelled' if cancelled else 'completed',
            'home_goals': None if pending or cancelled else i % 4,
            'away_goals': None if pending or cancelled else (i+1) % 3,
            'played_date': None if pending or cancelled else row['kickoff_at_utc'][:10],
            'available_at_utc': None if pending or cancelled else (
                datetime.fromisoformat(row['kickoff_at_utc'].replace('Z', '+00:00'))+timedelta(hours=3)).isoformat(),
            'document': 'official', 'basis': 'awaiting_review' if pending else 'official_cancellation' if cancelled else 'sporting_completion',
            'supersedes': None, 'correction_reason': None})
    value = {'schema_version': IDENTITY+'.facts', 'protocol_version': 2, 'rules_sha256': RULES_SHA256,
        'mode': 'synthetic', 'source_id': 'fictional-local', 'observed_at_utc': observed.isoformat(),
        'reviewed_at_utc': (observed+timedelta(minutes=1)).isoformat(), 'reviewed_by': 'Fictional source reviewer',
        'documents': {'official': {'path': document.name, 'sha256': digest(document),
            'url': 'https://example.test/official-results', 'authority': 'official_league',
            'observed_at_utc': observed.isoformat(), 'precision': 'final integer score; London calendar played date; observation seconds'}},
        'updates': updates}
    if events:
        reconcile_parents(value, events)
    return value


def reconcile_parents(snapshot, events):
    from prospective_v2.workflow import _latest
    latest = _latest(events)
    for row in snapshot['updates']:
        old = latest.get(row['fixture_id'])
        result = {key: row[key] for key in ('fixture_id', 'season', 'home', 'away', 'status',
            'home_goals', 'away_goals', 'played_date', 'available_at_utc', 'basis')}
        if old is not None and old['result'] != result:
            row['supersedes'] = old['fact_sha256']; row['correction_reason'] = 'Fictional reviewed official correction'
        else:
            row['supersedes'] = row['correction_reason'] = None
    return snapshot
