"""Explicit opt-in v2 commands. Preparation does not activate a cohort."""
import argparse
from pathlib import Path

from premonition_fc.storage import write_json
from . import workflow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    draft = sub.add_parser('draft')
    draft.add_argument('--parent', type=Path, required=True)
    draft.add_argument('--parent-sha256', required=True)
    draft.add_argument('--mode', choices=('synthetic', 'real'), required=True)
    draft.add_argument('--clock')
    draft.add_argument('--output', type=Path, required=True)
    register = sub.add_parser('register')
    register.add_argument('--draft', type=Path, required=True)
    register.add_argument('--parent', type=Path, required=True)
    register.add_argument('--parent-sha256', required=True)
    for command in (register, sub.add_parser('issue')):
        command.add_argument('--ledger', type=Path, required=True)
        command.add_argument('--fixtures', type=Path, required=True)
        command.add_argument('--history', type=Path, required=True)
        command.add_argument('--reference', type=Path, required=True)
        command.add_argument('--approval', type=Path)
        command.add_argument('--clock')
    settle = sub.add_parser('settle')
    settle.add_argument('--ledger', type=Path, required=True)
    settle.add_argument('--snapshot', type=Path, required=True)
    settle.add_argument('--clock')
    review = sub.add_parser('review')
    review.add_argument('--ledger', type=Path, required=True)
    review.add_argument('--clock')
    correction = sub.add_parser('corrected-review')
    correction.add_argument('--ledger', type=Path, required=True)
    correction.add_argument('--reason', required=True)
    correction.add_argument('--clock')
    export = sub.add_parser('export')
    export.add_argument('--ledger', type=Path, required=True)
    export.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'draft':
            output = workflow._outside(args.output)
            if output.exists():
                raise ValueError('Preserve the existing draft; use a fresh file')
            value = workflow.draft(args.parent, args.parent_sha256, args.mode, args.clock)
            write_json(output, value)
            print('V2 draft prepared; state unactivated; no ledger created.')
        elif args.command == 'register':
            value = workflow.register(args.ledger, args.draft, args.parent, args.parent_sha256,
                args.fixtures, args.history, args.reference, args.clock, args.approval)
            print('V2 registered at '+value['registered_at_utc'])
        elif args.command == 'issue':
            value = workflow.issue(args.ledger, args.fixtures, args.history, args.reference, args.clock, args.approval)
            print('V2 original paired issue saved for '+value['slate_id'])
        elif args.command == 'settle':
            print(workflow.settle(args.ledger, args.snapshot, args.clock))
        elif args.command == 'review':
            print('V2 frozen review: '+str(workflow.review(args.ledger, args.clock)['fixtures'])+' pairs')
        elif args.command == 'corrected-review':
            print('V2 corrected analysis: '+str(workflow.corrected_review(args.ledger, args.reason, args.clock)['fixtures'])+' unchanged cohort pairs')
        else:
            print(workflow.export(args.ledger, args.output)['label']+': exported')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise SystemExit('V2 operation failed: '+str(exc)) from exc
