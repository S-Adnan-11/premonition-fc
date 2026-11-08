"""Separate the launch fit, immutable issue record, and settlement ledger."""
import json
from pathlib import Path

from premonition_fc.storage import digest, object_digest

from .contracts import clock, history, instant, live_gates, stamp
from .models import fit_pair
from .protocol import RULES, fingerprints
from .store import append, transaction


def read_input(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Nonfinite JSON number')
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique, parse_constant=invalid)


def frozen(events):
    if not events or events[0]['kind'] != 'freeze':
        raise ValueError('Missing trial freeze')
    value = events[0]['payload']
    if value['rules'] != RULES or value['code_fingerprints'] != fingerprints() or value['fit_sha256'] != object_digest(value['fit']):
        raise ValueError('Frozen code, fit or rules changed')
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
    source = read_input(history_path)
    gates = approve(approval_path, mode, at, source['source_id'])
    eligible, excluded = history(source, mode, cutoff_time)
    request = {'history_sha256': digest(history_path), 'cutoff_at_utc': stamp(cutoff_time),
               'mode': mode, 'rules': RULES, 'code_fingerprints': fingerprints()}
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
                   'source_snapshot': source, 'source_snapshot_sha256': digest(history_path), 'gates': gates,
                   'eligible_history': eligible, 'excluded_history': excluded, 'fit': fit, 'fit_sha256': object_digest(fit),
                   'rules': RULES, 'rules_sha256': object_digest(RULES), 'code_fingerprints': fingerprints()}
        append(connection, events, 'freeze', 'freeze', payload)
        return payload
