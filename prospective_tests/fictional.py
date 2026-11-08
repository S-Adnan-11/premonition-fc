"""Fictional clubs and scores, unrelated to any actual Premier League fixture."""
from datetime import date, datetime, timedelta, timezone
import itertools

from premonition_fc.storage import object_digest


def envelope(kind, records, observed):
    return {'version': 1, 'mode': 'synthetic', 'competition': 'premier-league', 'source_id': 'fictional-local',
            'observed_at_utc': observed, 'coverage': {'complete': True, 'checked_at_utc': observed,
              'evidence_sha256': object_digest({'fictional': True, 'records': records})}, kind: records}


def history_snapshot(year=2026):
    records = []
    clubs = ['harbour-athletic', 'vale-city', 'moor-united', 'rail-rovers']
    # Two fictional seasons, each ordered home/away pairing exactly once.
    for offset in (1, 0):
        y = year-offset
        season = f'{y}-{str(y+1)[2:]}'
        for i, (home, away) in enumerate(itertools.permutations(clubs, 2)):
            played = date(y, 8, 1)+timedelta(days=7*i)
            records.append({'fixture_id': ':'.join((season, home, away)), 'season': season,
                            'home': home, 'away': away, 'played_date': played.isoformat(), 'status': 'completed',
                            'home_goals': (2, 0, 1, 3)[i % 4], 'away_goals': (0, 0, 1, 2)[i % 4],
                            'availability_basis': 'date_only_history'})
    return envelope('results', records, f'{year}-11-09T12:00:00Z')


def fixture_slates(count=101):
    from premonition_fc.features import bucket_start
    clubs = ['harbour-athletic', 'vale-city', 'moor-united', 'rail-rovers']+[f'fictional-{i:02}' for i in range(16)]
    pairs = [(h,a) for h,a in itertools.permutations(clubs, 2) if h not in clubs[:4] or a not in clubs[:4]][:count]
    slates = []
    for start in range(0, count, 6):
        day = date(2026,11,13)+timedelta(weeks=start//6)
        records = []
        for home, away in pairs[start:start+6]:
            records.append({'fixture_id': ':'.join(('2026-27',home,away)), 'season': '2026-27',
                            'home': home, 'away': away, 'status': 'scheduled',
                            'kickoff_at_utc': day.isoformat()+'T15:00:00Z', 'verified_at_utc': '2026-11-09T12:30:00Z'})
        slate = envelope('fixtures', records, '2026-11-09T12:30:00Z')
        slate.update(slate_id='2026-27:'+bucket_start(day.isoformat()), expected_fixture_ids=[r['fixture_id'] for r in records], omissions=[], earliest_verified_kickoff_at_utc=min(r['kickoff_at_utc'] for r in records))
        slates.append(slate)
    # One declared omission has no invented kickoff or score.
    omission = {'fixture_id':'2026-27:fictional-15:fictional-14', 'season':'2026-27',
                'home':'fictional-15','away':'fictional-14','reason':'No verified kickoff in fictional source'}
    slates[0]['omissions'].append(omission)
    slates[0]['expected_fixture_ids'].append(omission['fixture_id'])
    return slates


def settlement_snapshot(slates, complete_postponed=False):
    fixtures = [r for s in slates for r in s['fixtures']]
    last = max(datetime.fromisoformat(r['kickoff_at_utc'].replace('Z','+00:00')) for r in fixtures)
    observed = last+timedelta(days=2 if complete_postponed else 1)
    records = []
    for i, row in enumerate(fixtures):
        base = {k:row[k] for k in ('fixture_id','season','home','away')}
        if i == len(fixtures)-1:
            records.append(dict(base,status='cancelled'))
        elif i == 0 and not complete_postponed:
            records.append(dict(base,status='postponed'))
        else:
            completed = last+timedelta(days=1,hours=2) if i == 0 else datetime.fromisoformat(row['kickoff_at_utc'].replace('Z','+00:00'))+timedelta(hours=2)
            records.append(dict(base,status='completed',home_goals=0 if i==0 else (i%4),away_goals=0 if i==0 else ((i+1)%3),completed_at_utc=completed.isoformat()))
    return envelope('updates',records,observed.isoformat())
