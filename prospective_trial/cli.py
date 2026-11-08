"""Offline paired-trial preparation with explicit external input/output paths."""
import argparse
from pathlib import Path

from .workflow import freeze


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
    args = parser.parse_args()
    result = freeze(args.ledger, args.history, args.cutoff, args.mode, args.clock, args.approval)
    print(result['label']+': frozen paired fit '+result['fit_sha256'])


if __name__ == '__main__':
    main()
