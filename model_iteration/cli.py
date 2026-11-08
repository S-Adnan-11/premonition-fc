"""Explicit stages separate development fitting, forecast saving and target scoring."""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from premonition_fc.storage import digest, external_directory, object_digest, read_json, write_json

from .diagnostics import diagnose
from .protocol import PROTOCOL


def plan(args):
    output = external_directory(args.output, fresh=True)
    write_json(output/'protocol.json', {'declared_at_utc': datetime.now(timezone.utc).isoformat(),
               'rules': PROTOCOL, 'rules_sha256': object_digest(PROTOCOL)})


def diagnostics(args):
    output = external_directory(args.output, fresh=True)
    baseline = Path(args.baseline)
    sources = {'development': baseline/'development/scored_validation.json',
               'previously_seen_2025_26': baseline/'evaluation/scored_holdout.json'}
    for name, source in sources.items():
        write_json(output/(name+'.json'), diagnose(read_json(source)))
    write_json(output/'provenance.json', {'sources': {k: digest(v) for k, v in sources.items()},
               'comparison_label': PROTOCOL['comparison_label'], 'provider_requests': 0})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='stage', required=True)
    for name, function in [('plan', plan), ('diagnose', diagnostics)]:
        command = sub.add_parser(name)
        command.add_argument('--output', type=Path, required=True)
        if name == 'diagnose':
            command.add_argument('--baseline', type=Path, required=True)
        command.set_defaults(function=function)
    args = parser.parse_args()
    args.function(args)


if __name__ == '__main__':
    main()
