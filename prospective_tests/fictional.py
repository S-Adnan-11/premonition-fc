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
