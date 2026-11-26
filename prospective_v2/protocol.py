"""Versioned cohort semantics, retaining the original numerical specifications."""
from copy import deepcopy
from pathlib import Path

from premonition_fc.storage import digest, object_digest
from prospective_trial.protocol import MODELS, RULES as LEGACY_RULES

VERSION = 2
IDENTITY = 'premonition-fc.prospective-cohort.v2'
RULES = deepcopy(LEGACY_RULES)
RULES.update(version=VERSION,
    cohort_order='original issue event sequence, original scheduled kickoff UTC, canonical fixture ID',
    cohort_closure='first 100 completed non-void positions; earlier pending positions block closure',
    registration='separate ledger; actual registration before first affected issuance and kickoff',
    cancelled='verified cancellation or administrative award is void, without a sporting score',
    postponed='original pair and ordering position retained through postponement or verified replay',
    corrections='append-only attributed facts; freeze review once; corrections never replace cohort members',
    completion_evidence='official final sporting score and London played date; observation is not whistle time')
RULES['source_policy'] = {
    'authorities': ['official_league', 'official_club'],
    'final_status': 'verified regulation-time sporting completion',
    'timestamps': 'honest source observation, availability and review instants; played date has day precision',
    'exceptional': 'suspended/abandoned/unresolved pending; administrative award void; official replay retains identity',
}
RULES_SHA256 = object_digest(RULES)
OFFICIAL_HOSTS = frozenset(('premierleague.com', 'arsenal.com', 'avfc.co.uk', 'afcb.co.uk',
    'brentfordfc.com', 'brightonandhovealbion.com', 'chelseafc.com', 'ccfc.co.uk', 'cpfc.co.uk',
    'evertonfc.com', 'fulhamfc.com', 'hullcitytigers.com', 'itfc.co.uk', 'leedsunited.com',
    'liverpoolfc.com', 'mancity.com', 'manutd.com', 'nufc.co.uk', 'newcastleunited.com',
    'nottinghamforest.co.uk', 'safc.com', 'tottenhamhotspur.com', 'burnleyfootballclub.com',
    'lcfc.com', 'lutontown.co.uk', 'canaries.co.uk', 'sufc.co.uk', 'southamptonfc.com',
    'watfordfc.com', 'wba.co.uk', 'whufc.com', 'wolves.co.uk'))


def fingerprint():
    return object_digest({p.name: digest(p) for p in sorted(Path(__file__).parent.glob('*.py'))})
