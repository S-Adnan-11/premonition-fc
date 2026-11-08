"""Offline paired-trial preparation with explicit external input/output paths."""
import argparse
from pathlib import Path

from .workflow import display_reissue, export, freeze, issue, review, settle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('freeze')
    command.add_argument('--ledger', type=Path, required=True)
    command.add_argument('--history', type=Path, required=True)
    command.add_argument('--cutoff', required=True)
    command.add_argument('--mode', choices=('synthetic', 'real'), required=True)
    command.add_argument('--clock')
    command.add_argument('--approval', type=Path)
    command = sub.add_parser('issue')
    command.add_argument('--ledger', type=Path, required=True)
    command.add_argument('--fixtures', type=Path, required=True)
    command.add_argument('--history', type=Path, required=True)
    command.add_argument('--clock')
    command.add_argument('--approval', type=Path)
    command = sub.add_parser('settle')
    command.add_argument('--ledger', type=Path, required=True)
    command.add_argument('--snapshot', type=Path, required=True)
    command.add_argument('--clock')
    command = sub.add_parser('review')
    command.add_argument('--ledger', type=Path, required=True)
    command.add_argument('--clock')
    command = sub.add_parser('export')
    command.add_argument('--ledger', type=Path, required=True)
    command.add_argument('--output', type=Path, required=True)
    command = sub.add_parser('display-reissue')
    command.add_argument('--ledger', type=Path, required=True)
    command.add_argument('--fixture-id', required=True)
    command.add_argument('--kickoff', required=True)
    command.add_argument('--clock')
    args = parser.parse_args()
    if args.command == 'freeze':
        result = freeze(args.ledger, args.history, args.cutoff, args.mode, args.clock, args.approval)
        print(result['label']+': frozen paired fit '+result['fit_sha256'])
    elif args.command == 'issue':
        result = issue(args.ledger, args.fixtures, args.history, args.clock, args.approval)
        print(result['label']+': saved pair for '+result['slate_id'])
    elif args.command == 'settle':
        print(settle(args.ledger, args.snapshot, args.clock))
    elif args.command == 'review':
        print(review(args.ledger, args.clock)['label']+': 100-fixture review saved')
    elif args.command == 'display-reissue':
        print(display_reissue(args.ledger, args.fixture_id, args.kickoff, args.clock))
    else:
        print(export(args.ledger, args.output)['label']+': report exported')


if __name__ == '__main__':
    main()
