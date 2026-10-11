#!/usr/bin/env python3
"""Resume bounded local render/preparation chunks; never manufacture visual reviews.

Every invocation revalidates the renderer cache and evidence packet. Its JSONL
journal preserves timings and failures across interruption/restart. Source input
and immutable packets remain separately available for provenance.
"""
import argparse
import collections
import hashlib
import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import asset_catalog_campaign as campaign
import asset_catalog_visual as visual

ROOT = Path(__file__).resolve().parent.parent


def record(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        stream.write(json.dumps(dict(data, timestamp=time.time()), ensure_ascii=False)+'\n')


def evidence_overrides(report):
    """Only successfully rendered evidence; incomplete textures remain explicit."""
    result = {}
    for item in report['assets']:
        if item['status'] not in ('ready', 'incomplete_textures','low_signal_render'):
            continue
        views = item.get('views', [])
        if len(views) != 4:
            raise ValueError('Expected four rendered views: '+item['id'])
        for view in views:
            data = Path(view['path']).read_bytes()
            if hashlib.sha256(data).hexdigest() != view['sha256'] or not visual.image_ok(data):
                raise ValueError('Invalid rendered evidence: '+item['id'])
        if item['id'] in result:
            raise ValueError('Duplicate model identity')
        result[item['id']] = [v['path'] for v in views]
    return result


def run_chunk(folder, db_path, blender, size=384, samples=12, reserve_bytes=2*1024**3):
    folder = Path(folder).resolve()
    journal = folder/'runs.jsonl'
    free_before = shutil.disk_usage(folder).free
    if free_before < reserve_bytes:
        record(journal, {'stage':'storage_reserve_reached','free_bytes':free_before,'reserve_bytes':reserve_bytes})
        raise RuntimeError('Storage reserve reached; no more render files written')
    started = time.monotonic()
    command = [blender, '-b', '--python', str(ROOT/'scripts/render-asset-catalog-views.py'),
               '--', '--input', str(folder/'input.json'), '--output', str(folder/'render'),
               '--size', str(size), '--samples', str(samples)]
    record(journal, {'stage': 'render_start', 'command': command})
    with (folder/'render.log').open('a') as log:
        process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    render_seconds = round(time.monotonic()-started, 3)
    if process.returncode:
        record(journal, {'stage': 'render_process_failed', 'exit_code': process.returncode,
                         'seconds': render_seconds})
        raise RuntimeError('Blender process failed; see '+str(folder/'render.log'))
    report = json.loads((folder/'render/manifest.json').read_text())
    overrides = evidence_overrides(report)
    counts = dict(collections.Counter(a['status'] for a in report['assets']))
    record(journal, {'stage': 'render_complete', 'seconds': render_seconds,
                     'statuses': counts, 'cache_hits': sum(a.get('cacheHit', False) for a in report['assets'])})
    if not overrides:
        record(journal, {'stage': 'no_reviewable_images', 'statuses': counts})
        return {'chunk': str(folder), 'reviewable': 0, 'statuses': counts}
    visual.write_json(folder/'keys.json', list(overrides))
    visual.write_json(folder/'overrides.json', overrides)
    db = sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    started = time.monotonic()
    try:
        prepared = visual.prepare(db, list(overrides), folder/'packets', overrides=overrides)
    finally:
        db.close()
    dispatch = campaign.split_packet(prepared['packet'], folder/'reviewers'/prepared['packet_id'],
                                     batch_size=100, per_page=6)
    summary = {'chunk': str(folder), 'reviewable': prepared['ready'], 'statuses': counts,
               'render_seconds': render_seconds, 'prepare_seconds': round(time.monotonic()-started, 3),
               'packet': prepared, 'dispatch': dispatch,
               'annotation_status': 'Not annotated by this runner. Actual image review is required.',
               'incomplete_texture_keys': [a['id'] for a in report['assets'] if a['status']=='incomplete_textures']}
    summary['storage'] = {'free_bytes_before':free_before,'free_bytes_after':shutil.disk_usage(folder).free,'reserve_bytes':reserve_bytes,
                          'chunk_file_bytes':sum(f.stat().st_size for f in folder.rglob('*') if f.is_file())}
    visual.write_json(folder/'ready.json', summary)
    record(journal, dict(summary, stage='packet_ready'))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chunks', required=True)
    parser.add_argument('--db', default=str(ROOT/'output/asset-catalog/visual-v2/catalog.sqlite'))
    parser.add_argument('--blender', default='blender')
    parser.add_argument('--start', type=int, default=0)
    parser.add_argument('--stop', type=int)
    parser.add_argument('--size', type=int, default=384)
    parser.add_argument('--samples', type=int, default=12)
    args = parser.parse_args()
    for folder in sorted(Path(args.chunks).iterdir())[args.start:args.stop]:
        if folder.is_dir() and (folder/'input.json').is_file():
            result = run_chunk(folder, args.db, args.blender, args.size, args.samples)
            print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
