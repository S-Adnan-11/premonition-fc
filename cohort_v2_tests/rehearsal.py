"""Offline CLI rehearsal with fictional v1 and v2 ledgers and deterministic replay."""
import argparse
from copy import deepcopy
from pathlib import Path
import subprocess
import sys

from premonition_fc.storage import digest, external_directory, object_digest, read_json, write_json
from prospective_trial.store import transaction
from prospective_v2.workflow import _latest
from cohort_v2_tests.fictional import scenario, fact_snapshot, reconcile_parents


def run(output):
    root = external_directory(output, fresh=True)
    inputs = root/'inputs'; inputs.mkdir()
    past, slates, reference, paths = scenario(inputs)
    v1, v2 = root/'fictional-v1.sqlite', root/'fictional-v2.sqlite'
    commands = []
    def command(name, module, args, expected=0):
        guarded = ('from '+module+' import main\nimport socket\n'
            'def blocked(*a, **k):\n    raise AssertionError("Offline rehearsal forbids network")\n'
            'socket.socket = blocked\nsocket.create_connection = blocked\nmain()\n')
        result = subprocess.run([sys.executable, '-B', '-c', guarded, *map(str, args)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        (root/(name+'.log')).write_text(result.stdout+result.stderr, encoding='utf-8')
        assert result.returncode == expected, name+': '+result.stdout+result.stderr
        commands.append({'name': name, 'module': module, 'arguments': list(map(str, args)), 'exit_code': result.returncode})
    legacy = lambda name, args, expected=0: command(name, 'prospective_trial.cli', args, expected)
    current = lambda name, args, expected=0: command(name, 'prospective_v2.cli', args, expected)
    legacy('legacy-freeze', ['freeze', '--ledger', v1, '--history', inputs/'history.json',
        '--cutoff', '2026-11-09T12:00:00Z', '--mode', 'synthetic', '--clock', '2026-11-09T12:00:00Z'])
    legacy('legacy-export', ['export', '--ledger', v1, '--output', root/'parent'])
    v1_hash = digest(v1)
    legacy('legacy-replay', ['export', '--ledger', v1, '--output', root/'parent-repeat'])
    assert all(f.read_bytes() == (root/'parent-repeat'/f.name).read_bytes() for f in (root/'parent').iterdir())
    parent = root/'parent/events.json'; parent_pin = digest(parent)
    current('draft', ['draft', '--parent', parent, '--parent-sha256', parent_pin,
        '--mode', 'synthetic', '--clock', '2026-11-09T12:40:00Z', '--output', root/'draft.json'])
    assert read_json(root/'draft.json')['state'] == 'unactivated' and not v2.exists()
    activation = ['register', '--ledger', v2, '--draft', root/'draft.json', '--parent', parent,
        '--parent-sha256', parent_pin, '--fixtures', paths[0], '--history', inputs/'history.json',
        '--reference', inputs/'reference.json', '--clock', '2026-11-09T12:45:00Z']
    current('register', activation); current('registration-replay', activation)
    issue = lambda path: ['issue', '--ledger', v2, '--fixtures', path, '--history', inputs/'history.json',
                          '--reference', inputs/'reference.json', '--clock', '2026-11-09T13:00:00Z']
    missing = deepcopy(slates[0]); missing['fixtures'].pop(); write_json(inputs/'missing.json', missing)
    current('missing-whole-slate-rejected', issue(inputs/'missing.json'), 1)
    for i, path in enumerate(paths): current('issue-'+str(i), issue(path))
    current('issue-replay', issue(paths[0]))
    with transaction(v2) as (_, events):
        original_issues = [deepcopy(e) for e in events if e['kind'] == 'issue']
        assert len(original_issues) == len(paths)
        assert events[0]['payload']['fit'] == read_json(parent)[0]['payload']['fit']
    first = fact_snapshot(inputs, slates, pending_first=True, void_last=True)
    facts_path = inputs/'facts-first.json'; write_json(facts_path, first)
    settle = lambda path, at: ['settle', '--ledger', v2, '--snapshot', path, '--clock', at]
    current('99-settled-earlier-pending', settle(facts_path, first['reviewed_at_utc']))
    current('facts-replay', settle(facts_path, first['reviewed_at_utc']))
    current('review-before-closed-100-rejected', ['review', '--ledger', v2, '--clock', first['reviewed_at_utc']], 1)
    current('no-interim-export', ['export', '--ledger', v2, '--output', root/'before-review'])
    interim = read_json(root/'before-review/summary.json')
    assert interim['review'] is None and interim['progress']['settled'] == 99
    assert interim['progress']['void'] == 1 and interim['progress']['pending'] == 1
    with transaction(v2) as (_, events): final = fact_snapshot(inputs, slates, void_last=True, events=events)
    final['updates'][0].update(home_goals=0, away_goals=0, basis='official_replay')
    with transaction(v2) as (_, events): reconcile_parents(final, events)
    final_path = inputs/'facts-final.json'; write_json(final_path, final)
    current('100-settled-original-zero-zero', settle(final_path, final['reviewed_at_utc']))
    current('freeze-review', ['review', '--ledger', v2, '--clock', final['reviewed_at_utc']])
    current('review-replay', ['review', '--ledger', v2, '--clock', final['reviewed_at_utc']])
    with transaction(v2) as (_, events):
        review = next(deepcopy(e) for e in events if e['kind'] == 'review')
        assert review['payload']['fixtures'] == 100
        assert _latest(events)[final['updates'][0]['fixture_id']]['result']['home_goals'] == 0
        assert _latest(events)[final['updates'][0]['fixture_id']]['result']['away_goals'] == 0
    corrected = deepcopy(final); corrected['updates'][0]['home_goals'] = 7
    with transaction(v2) as (_, events): reconcile_parents(corrected, events)
    correction_path = inputs/'score-correction.json'; write_json(correction_path, corrected)
    current('append-score-correction', settle(correction_path, corrected['reviewed_at_utc']))
    current('retain-original-review', ['review', '--ledger', v2, '--clock', corrected['reviewed_at_utc']])
    current('corrected-same-cohort-analysis', ['corrected-review', '--ledger', v2,
        '--reason', 'Fictional reviewed official correction', '--clock', corrected['reviewed_at_utc']])
    wrong = deepcopy(corrected); wrong['protocol_version'] = 1
    wrong_path = inputs/'wrong-version.json'; write_json(wrong_path, wrong)
    current('mixed-version-rejected', settle(wrong_path, wrong['reviewed_at_utc']), 1)
    current('legacy-ledger-rejected', ['export', '--ledger', v1, '--output', root/'wrong-legacy'], 1)
    legacy('v2-ledger-rejected-by-legacy', ['export', '--ledger', v2, '--output', root/'wrong-v2'], 1)
    current('export', ['export', '--ledger', v2, '--output', root/'final'])
    current('deterministic-export', ['export', '--ledger', v2, '--output', root/'final-repeat'])
    assert all(f.read_bytes() == (root/'final-repeat'/f.name).read_bytes() for f in (root/'final').iterdir())
    assert digest(v1) == v1_hash
    with transaction(v2) as (_, events):
        assert [e for e in events if e['kind'] == 'issue'] == original_issues
        assert next(e for e in events if e['kind'] == 'review') == review
        correction = next(e for e in events if e['kind'] == 'review_correction')
        assert correction['payload']['cohort_fixture_ids'] == review['payload']['cohort_fixture_ids']
    summary = read_json(root/'final/summary.json')
    assert summary['progress']['issued'] == 101 and summary['progress']['settled'] == 100 and summary['progress']['void'] == 1
    result = {'status': 'PASS', 'mode': 'synthetic', 'network_disabled_in_cli_children': True,
        'provider_requests': 0, 'live_ledger_writes': 0, 'real_activation': False,
        'commands': commands, 'legacy_v1_bytes_preserved': True, 'exact_parent_fit_reused_without_refit': True,
        'all_original_pairs_preserved': True, 'frozen_review_preserved_after_correction': True,
        'deterministic_exports': True, 'summary': summary,
        'final_output_hashes': {f.name: digest(f) for f in (root/'final').iterdir()}}
    write_json(root/'verification.json', result)
    print('Fictional v2 CLI rehearsal PASS: '+str(len(commands))+' commands; 101 issued, 100 settled, 1 void; original review retained.')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
