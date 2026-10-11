#!/usr/bin/env python3
"""Transfer a visual texture description only to verified byte-identical pixels.

This is evidence reuse, NOT another vision inspection. The source audit binds
decoded pixels to exact TXD entry bytes; target bytes are checked before writes.
Manual annotations are never overwritten. Full transfer history is retained.
"""
import argparse
import collections
import hashlib
import json
import sqlite3
from pathlib import Path

from PIL import Image
import asset_catalog as catalog

METHOD = 'exact-pixel-visual-transfer'


def pixel_hash(path):
    with Image.open(path) as original:
        image = original.convert('RGBA')
        return hashlib.sha256(f'{image.width}x{image.height}:'.encode()+image.tobytes()).hexdigest()


def verify_source(source, cache):
    path = source.get('path') or source.get('file') or source.get('archive')
    identity = (path, source['offset'], source['bytes'], source['sha256'])
    if identity not in cache:
        with open(path, 'rb') as stream:
            stream.seek(source['offset'])
            data = stream.read(source['bytes'])
        if len(data) != source['bytes'] or hashlib.sha256(data).hexdigest() != source['sha256']:
            raise ValueError('Source TXD bytes changed: '+str(path))
        cache.add(identity)


def transfer(db, audit_path, apply=False, refresh_stale=False):
    audit_path = Path(audit_path).resolve()
    audit_bytes = audit_path.read_bytes()
    audit_sha = hashlib.sha256(audit_bytes).hexdigest()
    records = json.loads(audit_bytes)
    by_key = {r['key']: r for r in records}
    if len(by_key) != len(records):
        raise ValueError('Duplicate source audit identity')
    groups = collections.defaultdict(list)
    for row in records:
        if row['status'] == 'resolved':
            groups[row['pixelSha256']].append(row)
    parents = {};observations=[]
    rejected = []
    for row in db.execute("SELECT a.*,n.description,n.tags,n.method,n.model,n.confidence,n.evidence FROM assets a JOIN annotations n ON n.key=a.key AND n.asset_hash=a.hash WHERE a.kind='texture' AND n.method='model-visual' ORDER BY a.key"):
        if not catalog.annotation_is_fresh(db,row):
            raise ValueError('Parent image evidence missing or changed: '+row['key'])
        if not catalog.annotation_is_usable(db,row):continue
        audited = by_key.get(row['key'])
        if not audited or audited['status'] != 'resolved':
            continue
        evidence = json.loads(row['evidence'])
        path = Path(evidence['image_path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != evidence['image_sha256']:
            raise ValueError('Parent image bytes changed: '+row['key'])
        if evidence.get('views'):
            if len(evidence['views']) != 1:
                continue
            original=evidence['views'][0]
            path=Path(original['path'])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=original['sha256']:
                raise ValueError('Parent native pixel evidence changed: '+row['key'])
        pixel = pixel_hash(path)
        if pixel != audited['pixelSha256']:
            rejected.append(row['key'])
            continue
        fingerprint=catalog.digest({k:row[k] for k in ('key','hash','description','tags','method','model','confidence','evidence')})
        observations.append({'key':row['key'],'parent_annotation_sha256':fingerprint,'pixel_sha256':pixel,
                             'source_audit_sha256':audit_sha,'source':audited['sources'][0]['source'],
                             'image_path':str(path),'image_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        # Deterministic parent; original visual review remains separately stored.
        parents.setdefault(pixel, dict(row))
    staged = [];replacements={};freshness_cache={}
    verified_sources = set()
    existing = {r['key']: dict(r) for r in db.execute('SELECT * FROM annotations')}
    for pixel, parent in parents.items():
        for row in groups[pixel]:
            if row['key'] in existing:
                old=existing[row['key']]
                if not refresh_stale or old['method']!=METHOD or catalog.annotation_is_fresh(db,old,freshness_cache):continue
                replacements[row['key']]=catalog.canonical(old)
            target = db.execute('SELECT * FROM assets WHERE key=?', (row['key'],)).fetchone()
            if not target or target['kind'] != 'texture':
                raise ValueError('Unknown audited texture identity')
            record = json.loads(target['payload'])['record']
            # The audit is tied to this exact occurrence, not merely a texture name.
            for field in ('name', 'txd'):
                if record.get(field) != row[field]:
                    raise ValueError('Audit/catalog metadata mismatch')
            if record.get('source') != row['archive'] or any(record.get(k)!=row['expected'][k] for k in ('width','height')):
                raise ValueError('Audit/catalog occurrence or dimensions mismatch')
            if len(row['sources']) != 1:
                raise ValueError('Transfer needs an unambiguous source')
            source = row['sources'][0]
            matching = [m for m in source['matches'] if m['pixelSha256'] == pixel]
            if len(matching) != 1:
                raise ValueError('Transfer needs an unambiguous decoded texture')
            verify_source(source['source'], verified_sources)
            original = json.loads(parent['evidence'])
            parent_fingerprint = catalog.digest({k: parent[k] for k in ('key','hash','description','tags','method','model','confidence','evidence')})
            evidence = {'type': METHOD, 'image_path': original['image_path'],
                        'image_sha256': original['image_sha256'], 'pixel_sha256': pixel,
                        'parent_key': parent['key'], 'parent_annotation_sha256': parent_fingerprint,
                        'parent_evidence': original, 'asset_hash': target['hash'],
                        'source_audit': {'path': str(audit_path), 'sha256': audit_sha},
                        'target_source': source,
                        'limitations': 'Exact pixel appearance reused from an actual visual review. This occurrence was not independently inspected. Model use, atlas placement, and material function require occurrence-specific context.'}
            staged.append((dict(target), parent, evidence))
    if apply:
        if db.in_transaction:raise ValueError('Transfer requires its own immediate transaction')
        db.execute('BEGIN IMMEDIATE')
        with db:
            if hashlib.sha256(audit_path.read_bytes()).hexdigest()!=audit_sha:
                raise ValueError('Source audit changed before transaction')
            freshness_cache={};transaction_sources=set()
            for observation in observations:
                bound={'parent_key':observation['key'],'parent_annotation_sha256':observation['parent_annotation_sha256']}
                if not catalog.annotation_is_fresh(db,{'method':METHOD,'evidence':catalog.canonical(bound)},freshness_cache):
                    raise ValueError('Observed visual parent changed before transaction')
                verify_source(observation['source'],transaction_sources)
            for target,parent,evidence in staged:
                current=db.execute('SELECT hash FROM assets WHERE key=?',(target['key'],)).fetchone()
                if not current or current['hash']!=target['hash']:
                    raise ValueError('Target metadata changed before transaction')
                if not catalog.annotation_is_fresh(db,{'method':METHOD,'evidence':catalog.canonical(evidence)},freshness_cache):
                    raise ValueError('Visual parent changed before transaction')
                verify_source(evidence['target_source']['source'],transaction_sources)
            db.execute('CREATE TABLE IF NOT EXISTS visual_pixel_transfers(key TEXT,parent_key TEXT,parent_annotation_sha256 TEXT,evidence TEXT,PRIMARY KEY(key,parent_annotation_sha256))')
            db.execute('CREATE TABLE IF NOT EXISTS visual_pixel_observations(key TEXT,parent_annotation_sha256 TEXT,pixel_sha256 TEXT,evidence TEXT,PRIMARY KEY(key,parent_annotation_sha256))')
            for observation in observations:
                db.execute('INSERT OR IGNORE INTO visual_pixel_observations VALUES (?,?,?,?)',(observation['key'],observation['parent_annotation_sha256'],observation['pixel_sha256'],catalog.canonical(observation)))
            for target, parent, evidence in staged:
                current=db.execute('SELECT * FROM annotations WHERE key=?',(target['key'],)).fetchone()
                if current and replacements.get(target['key'])!=catalog.canonical(dict(current)):
                    raise ValueError('Target annotation appeared or changed during transfer')
                if target['key'] in replacements and not current:raise ValueError('Stale target removed during transfer')
                db.execute('INSERT OR REPLACE INTO annotations VALUES (?,?,?,?,?,?,?,?)',
                           (target['key'], target['hash'], parent['description'], parent['tags'], METHOD,
                            parent['model'], parent['confidence'], catalog.canonical(evidence)))
                db.execute('INSERT INTO visual_pixel_transfers VALUES (?,?,?,?)',
                           (target['key'], parent['key'], evidence['parent_annotation_sha256'], catalog.canonical(evidence)))
                catalog.searchable(db,target['key'],target['name'],json.loads(target['payload']),target['hash'])
    return {'applied': apply, 'eligible_transfers': len(staged), 'reviewed_pixel_groups': len(parents),
            'refreshed_stale_transfers':len(replacements),
            'verified_direct_pixel_observations':len(observations),
            'parent_images_not_exact_local_pixels': rejected, 'target_sources_verified': len(verified_sources),
            'audit_sha256': audit_sha, 'new_vision_inspections': 0,
            'scope': 'Appearance only; per-occurrence model/TXD links remain separate.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='output/asset-catalog/visual-v2/catalog.sqlite')
    parser.add_argument('--audit', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--refresh-stale', action='store_true',help='Refresh only stale pixel transfers from current verified parents, preserving transfer history')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    db = catalog.connect(args.db)
    report = transfer(db, args.audit, args.apply,args.refresh_stale)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
