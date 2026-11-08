"""Exercise a complete fictional paired trial through the public CLI."""
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from premonition_fc.storage import digest, external_directory, read_json, write_json
from fictional import fixture_slates, history_snapshot, settlement_snapshot


def dry_run(output):
    root = external_directory(output, fresh=True)
    inputs = root/'inputs'
    inputs.mkdir()
    ledger = root/'trial.sqlite'
    source = Path(__file__).resolve().parents[1]
    commands = []
    def run(name, arguments, expected=0):
        result = subprocess.run([sys.executable, '-B', '-m', 'prospective_trial', *map(str,arguments)],
                                cwd=source, capture_output=True, text=True)
        (root/(name+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
        if (expected == 0 and result.returncode != 0) or (expected != 0 and result.returncode == 0):
            raise AssertionError('Unexpected CLI status: '+name)
        commands.append({'name':name,'arguments':list(map(str,arguments)),'returncode':result.returncode,
                         'expected_rejection':expected != 0})
    history = inputs/'history.json'
    write_json(history, history_snapshot())
    run('freeze',['freeze','--ledger',ledger,'--history',history,'--cutoff','2026-11-09T12:00:00Z',
                  '--mode','synthetic','--clock','2026-11-09T12:00:00Z'])
    run('repeat-freeze',['freeze','--ledger',ledger,'--history',history,'--cutoff','2026-11-09T12:00:00Z',
                        '--mode','synthetic','--clock','2026-11-09T12:00:00Z'])
    slates = fixture_slates()
    for i, slate in enumerate(slates):
        path=inputs/f'slate-{i:02}.json'
        write_json(path, slate)
        run(f'issue-{i:02}',['issue','--ledger',ledger,'--fixtures',path,'--history',history,'--clock','2026-11-09T13:00:00Z'])
    run('repeat-issue',['issue','--ledger',ledger,'--fixtures',inputs/'slate-00.json','--history',history,'--clock','2026-11-09T13:00:00Z'])
    first = settlement_snapshot(slates)
    first_path=inputs/'settlement-99.json'
    write_json(first_path, first)
    run('settle-99',['settle','--ledger',ledger,'--snapshot',first_path,'--clock',first['observed_at_utc']])
    run('review-99-rejected',['review','--ledger',ledger,'--clock',first['observed_at_utc']],expected=1)
    run('export-99',['export','--ledger',ledger,'--output',root/'progress-99'])
    assert read_json(root/'progress-99/summary.json')['progress']['settled']==99
    assert read_json(root/'progress-99/summary.json')['review'] is None
    new_kickoff=datetime.fromisoformat(first['observed_at_utc'])+timedelta(hours=1)
    run('display-reissue',['display-reissue','--ledger',ledger,'--fixture-id',slates[0]['fixtures'][0]['fixture_id'],
                          '--kickoff',new_kickoff.isoformat(),'--clock',first['observed_at_utc']])
    second=settlement_snapshot(slates,True)
    second_path=inputs/'settlement-100.json'
    write_json(second_path,second)
    run('settle-100',['settle','--ledger',ledger,'--snapshot',second_path,'--clock',second['observed_at_utc']])
    run('repeat-settle',['settle','--ledger',ledger,'--snapshot',second_path,'--clock',second['observed_at_utc']])
    run('review-100',['review','--ledger',ledger,'--clock',second['observed_at_utc']])
    run('repeat-review',['review','--ledger',ledger,'--clock',second['observed_at_utc']])
    run('export-final',['export','--ledger',ledger,'--output',root/'final'])
    run('export-replay',['export','--ledger',ledger,'--output',root/'replay'])
    names=('summary.json','events.json','fits.json','provenance.json','REPORT.md')
    assert all((root/'final'/n).read_bytes()==(root/'replay'/n).read_bytes() for n in names)
    final=read_json(root/'final/summary.json')
    assert final['progress']['settled']==100 and final['progress']['pending']==0 and final['progress']['void']==1
    assert final['progress']['omitted']==1 and final['review']['fixtures']==100
    events=read_json(root/'final/events.json')
    assert len([e for e in events if e['kind']=='settled'])==100
    assert len([e for e in events if e['kind']=='review'])==1
    write_json(root/'verification.json',{'status':'PASS','mode':'synthetic','provider_requests':0,
        'progress':final['progress'],'cli_commands':commands,'event_count':len(events),
        'byte_identical_exports':{n:digest(root/'final'/n) for n in names}})
    print('Synthetic dry run PASS: 101 eligible; 100 settled; one void; one omission; immutable 100-pair review.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    dry_run(parser.parse_args().output)
