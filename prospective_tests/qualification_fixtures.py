"""Fictional independent register and local evidence for offline qualification tests."""
import itertools

from premonition_fc.storage import digest


def reference_bundle(root, history, slate):
    documents = {}
    for name, kind in [('history', 'historical_audit'), ('schedule', 'official_schedule'), ('audit', 'season_audit')]:
        path = root/(name+'.txt')
        path.write_text('Fictional local '+name+' evidence.\n', encoding='utf-8')
        documents[name] = {'path': path.name, 'sha256': digest(path), 'kind': kind, 'url': 'https://example.test/'+name}
    seasons = {}
    for row in history['results']+slate['fixtures']:
        seasons.setdefault(row['season'], set()).update([row['home'], row['away']])
    records = {}
    for season, clubs in sorted(seasons.items()):
        for h, a in itertools.permutations(sorted(clubs), 2):
            key = ':'.join((season, h, a))
            records[key] = {'fixture_id': key, 'season': season, 'home': h, 'away': a,
                            'status': 'scheduled', 'slate_id': season+':'+season[:4]+'-11-24',
                            'kickoff_at_utc': season[:4]+'-11-27T15:00:00Z', 'document': 'schedule'}
    for row in history['results']:
        records[row['fixture_id']] = {k: row[k] for k in ('fixture_id', 'season', 'home', 'away', 'status', 'played_date', 'home_goals', 'away_goals')}
        records[row['fixture_id']]['document'] = 'history'
    for row in slate['fixtures']:
        records[row['fixture_id']] = {k: row[k] for k in ('fixture_id', 'season', 'home', 'away', 'status', 'kickoff_at_utc')}
        records[row['fixture_id']].update(document='schedule', slate_id=slate['slate_id'])
    return {'version': 1, 'mode': 'synthetic', 'competition': 'premier-league',
            'source_id': history['source_id'], 'observed_at_utc': history['observed_at_utc'],
            'history_start_season': min(seasons), 'history_through_london_date': '2026-11-09', 'history_complete': True,
            'schedule_complete': True, 'season_clubs': {s: sorted(c) for s, c in seasons.items()},
            'fixtures': list(records.values()), 'documents': documents, 'amendments': [],
            'season_audit': {'status': 'FAIL', 'returned': 17, 'expected': len(records), 'document': 'audit'}}


def reschedule(reference, fixture, kickoff):
    row = next(r for r in reference['fixtures'] if r['fixture_id'] == fixture['fixture_id'])
    names = ('status', 'slate_id', 'kickoff_at_utc')
    before = {k: row[k] for k in names}
    row['kickoff_at_utc'] = kickoff
    fixture['kickoff_at_utc'] = kickoff
    reference['amendments'].append({'fixture_id': row['fixture_id'], 'from': before,
        'to': {k: row[k] for k in names}, 'document': 'schedule', 'reason': 'Fictional official rescheduling notice'})
