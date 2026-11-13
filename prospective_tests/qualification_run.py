"""Offline CLI proof of whole-slate pauses and a verified kickoff amendment."""
import argparse
from copy import deepcopy
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from premonition_fc.storage import external_directory, read_json, write_json
from prospective_trial.store import transaction
from fictional import fixture_slates, history_snapshot, settlement_snapshot
from qualification_fixtures import reference_bundle, reschedule


def run(output):
    root = external_directory(output, fresh=True)
    inputs = root/'inputs'
    inputs.mkdir()
    ledger, decisions = root/'trial.sqlite', root/'decisions.sqlite'
    history, slate = history_snapshot(), fixture_slates(3)[0]
    slate['omissions'] = []
    slate['expected_fixture_ids'] = [r['fixture_id'] for r in slate['fixtures']]
    reference = reference_bundle(inputs, history, slate)
    hpath, fpath, rpath = (inputs/n for n in ('history.json', 'slate.json', 'reference.json'))
    write_json(hpath, history)
    write_json(fpath, slate)
    write_json(rpath, reference)
    commands = []
    # Imports complete before network functions are disabled in every child.
    guarded = ('from prospective_trial.cli import main\nimport socket\n'
               'from prospective_trial.qualification import QualificationPaused\n'
               'def blocked(*a, **k):\n    raise AssertionError("Offline proof forbids network")\n'
               'socket.socket = blocked\nsocket.create_connection = blocked\n'
               'try:\n    main()\nexcept QualificationPaused as e:\n    print("PAUSED:", e)\n    raise SystemExit(2)\n')
    def command(name, args, expected=0):
        result = subprocess.run([sys.executable, '-B', '-c', guarded, *map(str, args)],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        (root/(name+'.log')).write_text(result.stdout+result.stderr, encoding='utf-8')
        assert result.returncode == expected, name+': '+result.stdout+result.stderr
        commands.append({'name': name, 'arguments': list(map(str, args)), 'exit_code': result.returncode})
    common = ['--ledger', ledger, '--history', hpath, '--reference', rpath, '--decisions', decisions]
    command('freeze', ['freeze', *common, '--mode', 'synthetic', '--cutoff', '2026-11-09T12:00:00Z', '--clock', '2026-11-09T12:00:00Z'])
    def issue_args():
        return ['issue', *common, '--fixtures', fpath, '--clock', '2026-11-09T13:00:00Z']
    missing = deepcopy(slate)
    missing['fixtures'].pop()
    missing['expected_fixture_ids'] = [r['fixture_id'] for r in missing['fixtures']]
    write_json(fpath, missing)
    command('missing-fixture-paused', issue_args(), 2)
    with transaction(ledger) as (_, events):
        assert len(events) == 1 and events[0]['kind'] == 'freeze'
    with transaction(decisions) as (_, events):
        assert events[-1]['payload']['reason_code'] == 'EXPECTED_FIXTURE_MISSING'
        assert events[-1]['payload']['recorded_before_known_kickoff'] is True
    slate['fixtures'][0]['kickoff_at_utc'] = '2026-11-13T16:00:00Z'
    write_json(fpath, slate)
    command('kickoff-conflict-paused', issue_args(), 2)
    with transaction(ledger) as (_, events):
        assert len(events) == 1
    reschedule(reference, slate['fixtures'][0], '2026-11-13T16:00:00Z')
    write_json(rpath, reference)
    command('amended-slate-issued', issue_args())
    command('identical-retry', issue_args())
    with transaction(ledger) as (_, events):
        assert len(events) == 2
        issued = events[-1]['payload']
        original_hash = events[-1]['event_hash']
        assert len(issued['forecasts']) == 6 and issued['fit_sha256'] == events[0]['payload']['fit_sha256']
        assert issued['qualification']['decision']['reference']['season_audit']['status'] == 'FAIL'
    first, second = settlement_snapshot([slate]), settlement_snapshot([slate], True)
    write_json(inputs/'settlement-first.json', first)
    command('postponed-original-pending', ['settle', '--ledger', ledger, '--snapshot', inputs/'settlement-first.json', '--clock', first['observed_at_utc']])
    command('display-only-reschedule', ['display-reissue', '--ledger', ledger, '--fixture-id', slate['fixtures'][0]['fixture_id'],
                                      '--kickoff', '2026-11-15T12:00:00Z', '--clock', first['observed_at_utc']])
    write_json(inputs/'settlement-final.json', second)
    command('original-pair-settles-zero-zero', ['settle', '--ledger', ledger, '--snapshot', inputs/'settlement-final.json', '--clock', second['observed_at_utc']])
    command('review-before-100-rejected', ['review', '--ledger', ledger, '--clock', second['observed_at_utc']], 1)
    command('export', ['export', '--ledger', ledger, '--output', root/'final'])
    summary = read_json(root/'final/summary.json')
    assert summary['progress']['settled'] == 2 and summary['progress']['void'] == 1 and summary['review'] is None
    with transaction(ledger) as (_, events):
        assert next(e for e in events if e['kind'] == 'issue')['event_hash'] == original_hash
    with transaction(decisions) as (_, decisions_events):
        pauses = [e['payload'] for e in decisions_events if e['payload']['status'] == 'PAUSED']
        assert [p['reason_code'] for p in pauses] == ['EXPECTED_FIXTURE_MISSING', 'KICKOFF_UNVERIFIED']
        assert all(p['recorded_before_known_kickoff'] for p in pauses)
    write_json(root/'verification.json', {'status': 'PASS', 'mode': 'synthetic', 'provider_requests': 0,
        'network_disabled_in_cli_children': True, 'commands': commands, 'pause_reasons': [p['reason_code'] for p in pauses],
        'no_partial_issue_after_pauses': True, 'documented_amendment_preserves_identity': True,
        'original_fits_and_issue_pair_preserved': True, 'season_failure_retained': True,
        'settled': 2, 'void': 1, 'review_blocked_below_100': True})
    print('Offline qualification proof PASS: whole-slate pauses, documented amendment, original-pair settlement; no provider requests.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
