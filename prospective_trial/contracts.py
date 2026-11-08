"""Strict snapshot identities, aware times, conservative date bounds and live gates."""
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from .protocol import RULES

LONDON = ZoneInfo('Europe/London')
UTC = timezone.utc


def fields(value, required, optional=()):
    if not isinstance(value, dict) or set(required)-value.keys() or set(value)-set(required)-set(optional):
        raise ValueError('Missing or unexpected input fields')


def instant(value):
    if not isinstance(value, str) or not re.search(r'(?:Z|[+-]\d{2}:\d{2})$', value):
        raise ValueError('A timezone-aware ISO timestamp is required')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Ambiguous timestamp')
    return result.astimezone(UTC)


def stamp(value):
    return value.astimezone(UTC).isoformat()


def clock(mode, controlled=None):
    if mode not in ('synthetic', 'real'):
        raise ValueError('Unknown run mode')
    if mode == 'real' and controlled is not None:
        raise ValueError('A controlled clock is allowed only for synthetic runs')
    if mode == 'synthetic' and controlled is None:
        raise ValueError('Synthetic runs require an explicit controlled clock')
    return instant(controlled) if controlled is not None else datetime.now(UTC)


def identity(row):
    if not isinstance(row, dict):
        raise ValueError('Fixture must be an object')
    season, home, away = (row.get(k) for k in ('season', 'home', 'away'))
    if not isinstance(season, str) or not re.fullmatch(r'\d{4}-\d{2}', season) or int(season[5:]) != (int(season[:4])+1) % 100:
        raise ValueError('Invalid season')
    if any(not isinstance(t, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', t) for t in (home, away)) or home == away:
        raise ValueError('Invalid club identities')
    if row.get('fixture_id') != ':'.join((season, home, away)):
        raise ValueError('Fixture identity changed or is not canonical')
    return row['fixture_id']


def season_date(season, day):
    year = int(season[:4])
    if not date(year, 7, 1) <= day <= date(year+1, 6, 30):
        raise ValueError('Date does not belong to season')


def snapshot(value, kind, mode, asof):
    fields(value, ('version', 'mode', 'competition', 'source_id', 'observed_at_utc', 'coverage', kind))
    if value['version'] != 1 or value['mode'] != mode or value['competition'] != 'premier-league' or not isinstance(value['source_id'], str) or not value['source_id']:
        raise ValueError('Snapshot mode, competition or source differs')
    observed = instant(value['observed_at_utc'])
    if observed > asof or asof-observed > timedelta(hours=RULES['snapshot_max_age_hours']):
        raise ValueError('Snapshot is future-dated or stale')
    coverage = value['coverage']
    fields(coverage, ('complete', 'checked_at_utc', 'evidence_sha256'))
    if coverage['complete'] is not True or not re.fullmatch('[0-9a-f]{64}', str(coverage['evidence_sha256'])):
        raise ValueError('Completeness requires explicit evidence')
    if not observed-timedelta(hours=24) <= instant(coverage['checked_at_utc']) <= observed:
        raise ValueError('Coverage check is stale or follows observation')
    if not isinstance(value[kind], list):
        raise ValueError('Snapshot records must be an array')
    return observed


def history(value, mode, asof):
    observed = snapshot(value, 'results', mode, asof)
    eligible, excluded, seen = [], [], set()
    for row in value['results']:
        fields(row, ('fixture_id', 'season', 'home', 'away', 'played_date', 'status', 'home_goals', 'away_goals', 'availability_basis'), ('available_at_utc',))
        key = identity(row)
        if key in seen:
            raise ValueError('Duplicate historical fixture')
        seen.add(key)
        played = date.fromisoformat(row['played_date'])
        season_date(row['season'], played)
        if row['status'] != 'completed' or any(type(row[g]) is not int or row[g] < 0 for g in ('home_goals', 'away_goals')):
            raise ValueError('Only confirmed complete historical scores are allowed')
        bound = datetime.combine(played+timedelta(days=1), time.min, LONDON).astimezone(UTC)
        if row['availability_basis'] == 'confirmed_time':
            available = instant(row.get('available_at_utc'))
            if available.astimezone(LONDON).date() < played:
                raise ValueError('Score confirmation precedes played date')
        elif row['availability_basis'] == 'date_only_history' and 'available_at_utc' not in row:
            available = bound
        else:
            raise ValueError('Missing or ambiguous result availability')
        if available > observed:
            raise ValueError('Result was unavailable at snapshot observation')
        reason = None
        if played >= asof.astimezone(LONDON).date():
            reason = 'played date is not strictly before shared London cutoff'
        elif available > asof:
            reason = 'confirmation after cutoff'
        if reason:
            excluded.append({'fixture_id': key, 'reason': reason})
        else:
            eligible.append(dict(row, knowledge_bound_utc=stamp(available)))
    if not eligible:
        raise ValueError('No eligible past results')
    eligible.sort(key=lambda r: (r['played_date'], r['season'], r['home'], r['away']))
    return eligible, excluded


def live_gates(value, mode, now):
    if mode == 'synthetic':
        return {'mode': 'synthetic', 'live_authorized': False}
    if value is None:
        raise ValueError('Real workflow blocked: live gates missing')
    fields(value, ('project', 'source_id', 'platform', 'product', 'plan', 'reviewed_at_utc', 'expires_at_utc',
                   'access', 'freshness', 'model_input_and_display', 'retention'))
    if value['project'] != 'Premonition-FC' or any(not isinstance(value[k], str) or not value[k] for k in ('source_id', 'platform', 'product', 'plan')):
        raise ValueError('Live approval must name this project and exact source/plan')
    if not instant(value['reviewed_at_utc']) <= now < instant(value['expires_at_utc']):
        raise ValueError('Live approval is expired or future-dated')
    for gate in ('freshness', 'model_input_and_display', 'retention'):
        fields(value[gate], ('status', 'evidence_sha256'))
        if value[gate]['status'] != 'PASS' or not re.fullmatch('[0-9a-f]{64}', str(value[gate]['evidence_sha256'])):
            raise ValueError('Real workflow blocked: '+gate)
    access = value['access']
    fields(access, ('status', 'evidence_sha256', 'quota_observed_at_utc', 'quota_reset_at_utc', 'remaining', 'shared_reserve', 'project_allowance'))
    if access['status'] != 'PASS' or not re.fullmatch('[0-9a-f]{64}', str(access['evidence_sha256'])):
        raise ValueError('Real workflow blocked: source access')
    if not instant(access['quota_observed_at_utc']) <= now < instant(access['quota_reset_at_utc']) or now-instant(access['quota_observed_at_utc']) > timedelta(hours=24):
        raise ValueError('Quota evidence is stale')
    if any(type(access[k]) is not int or access[k] < 0 for k in ('remaining', 'shared_reserve', 'project_allowance')) or not 0 < access['project_allowance'] <= 6 or access['remaining']-access['shared_reserve'] < access['project_allowance']:
        raise ValueError('Project allowance or shared quota is unverified')
    return value
