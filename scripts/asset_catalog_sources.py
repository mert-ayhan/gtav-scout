#!/usr/bin/env python3
"""Read-only GTA V (Legacy) metadata adapter.

Drives tools/GtavScout.Extract, which parses YTYP archetypes, YTD dictionaries and
YMAP placements with CodeWalker.Core. Emits catalogue metadata only: no game
binaries, no decoded pixels.

Assets come from one of two sources:

  --asset-root DIR   a tree of files exported from the game with OpenIV
  --game-root DIR    the game's RPF archives directly

The RPF source needs the NG key material CodeWalker derives from GTA5.exe, which
recent game builds no longer expose; run `gtav-scout-extract keys --game-root DIR
--probe 1` to see what this installation offers. Use --asset-root when that fails.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ADAPTER = 'gta5-legacy-v1'
REQUIRED = ('models/data/models.json', 'models/data/model-sizes.json',
            'models/data/locations.json', 'textures/data/textures.json')
PROJECT = Path(__file__).resolve().parent.parent / 'tools' / 'GtavScout.Extract'


def tool_command(out, asset_root=None, game_root=None, codewalker_path=None,
                 dotnet=None, project=None):
    if bool(asset_root) == bool(game_root):
        raise ValueError('Pass exactly one of --asset-root (extracted files) '
                         'or --game-root (RPF archives)')
    codewalker_path = codewalker_path or os.environ.get('CODEWALKER_PATH')
    if not codewalker_path:
        raise ValueError(
            'CODEWALKER_PATH is not set. Clone https://github.com/dexyfex/CodeWalker '
            'and point CODEWALKER_PATH at it; CodeWalker is not bundled with this tool.')
    source = ['--asset-root', str(asset_root)] if asset_root else ['--game-root', str(game_root)]
    return ([dotnet or 'dotnet', 'run', '-c', 'Release', '--project',
             str(project or PROJECT), '--', 'inventory'] + source + ['--out', str(out)])


def validate_snapshot(out):
    """Refuse a snapshot that a partly-failed scan could have produced."""
    out = Path(out)
    report_path = out / 'source-report.json'
    if not report_path.is_file():
        raise ValueError('No source-report.json under ' + str(out))
    report = json.loads(report_path.read_text())
    if report.get('adapter') != ADAPTER:
        raise ValueError('Unexpected adapter %r; this front-end drives %s'
                         % (report.get('adapter'), ADAPTER))
    for name in REQUIRED:
        if not (out / name).is_file():
            raise ValueError('Snapshot is missing ' + name)
    if not report.get('models'):
        raise ValueError('Snapshot contains no models; read failures in source-report.json')
    if not report.get('textures'):
        raise ValueError('Snapshot contains no textures; read failures in source-report.json')
    return report


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--asset-root', help='Directory of files exported from the game')
    parser.add_argument('--game-root', help='GTA V installation, read through its RPF archives')
    parser.add_argument('--out', required=True, help='New directory for the snapshot')
    parser.add_argument('--codewalker-path')
    parser.add_argument('--project')
    parser.add_argument('--dotnet', default='dotnet')
    return parser


def main():
    args = build_parser().parse_args()

    command = tool_command(args.out, args.asset_root, args.game_root,
                           args.codewalker_path, args.dotnet, args.project)
    environment = dict(os.environ)
    if args.codewalker_path:
        environment['CODEWALKER_PATH'] = args.codewalker_path

    completed = subprocess.run(command, env=environment)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)

    report = validate_snapshot(args.out)
    print(json.dumps(report, indent=2))
    if report.get('failures'):
        print('%d source failures recorded; read source-report.json before trusting coverage.'
              % len(report['failures']), file=sys.stderr)


if __name__ == '__main__':
    main()
