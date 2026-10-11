#!/usr/bin/env python3
"""Explicit evidence-bound annotation revisions; immutable original reviews remain intact."""
import argparse, json, sqlite3
from pathlib import Path
import asset_catalog as catalog
import asset_catalog_visual as visual


def revise(db, manifest, previous, responses):
    if db.in_transaction:
        raise ValueError('Revision requires a connection without an active transaction')
    visual.validate_manifest(manifest)
    if previous.get('packet_id') != manifest['packet_id'] or responses.get('packet_id') != manifest['packet_id']:
        raise ValueError('Revision packet mismatch')
    old_rows=previous.get('reviews',[]); new_rows=responses.get('reviews',[])
    old={r['image_id']:r for r in old_rows}; new={r['image_id']:r for r in new_rows}
    entries={e['image_id']:e for e in manifest['entries']}
    if not new or len(new)!=len(new_rows) or len(old)!=len(old_rows) or set(new)!=set(old) or not set(new)<=set(entries):
        raise ValueError('Revision requires matching unique known IDs')
    # Reuse the full existing schema/evidence validator on an isolated snapshot.
    # Original history is removed only from this throwaway validation database.
    staged=sqlite3.connect(':memory:'); staged.row_factory=sqlite3.Row
    try:
        db.backup(staged)
        with staged:
            staged.executemany('DELETE FROM visual_reviews WHERE packet_id=? AND image_id=?',[(manifest['packet_id'],i) for i in new])
        visual.import_reviews(staged,manifest,responses)
    finally:
        staged.close()
    db.execute('CREATE TABLE IF NOT EXISTS annotation_revisions(packet_id TEXT NOT NULL,image_id TEXT NOT NULL,previous_hash TEXT NOT NULL,response_hash TEXT NOT NULL,response TEXT NOT NULL,evidence TEXT NOT NULL,PRIMARY KEY(packet_id,image_id,response_hash))')
    counts={'revised':0,'unchanged':0,'accepted':0,'ambiguous':0,'failed':0}
    db.execute('BEGIN IMMEDIATE')
    with db:
        visual.validate_manifest(manifest)
        for iid,r in new.items():
            e=entries[iid]
            current_asset=db.execute('SELECT hash FROM assets WHERE key=?',(e['key'],)).fetchone()
            if not current_asset or current_asset['hash']!=e['asset_hash']:
                raise ValueError('Asset changed between validation and revision transaction')
            previous_hash=catalog.digest(old[iid]); response_hash=catalog.digest(r)
            latest=db.execute('SELECT response,evidence FROM annotation_revisions WHERE packet_id=? AND image_id=? ORDER BY rowid DESC LIMIT 1',(manifest['packet_id'],iid)).fetchone()
            if not latest: latest=db.execute('SELECT response,evidence FROM visual_reviews WHERE packet_id=? AND image_id=?',(manifest['packet_id'],iid)).fetchone()
            if not latest: raise ValueError('Original reviewed parent missing')
            current=json.loads(latest['response'])
            existing=db.execute('SELECT previous_hash FROM annotation_revisions WHERE packet_id=? AND image_id=? AND response_hash=?',(manifest['packet_id'],iid,response_hash)).fetchone()
            identical=current==r
            reapply=identical and existing and existing['previous_hash']==previous_hash
            if not reapply and catalog.digest(current)!=previous_hash:
                raise ValueError('Revision parent has changed')
            # A separate writer must not have edited annotations behind this history.
            annotation=db.execute('SELECT * FROM annotations WHERE key=?',(e['key'],)).fetchone()
            if current['status']=='accepted':
                if not annotation or annotation['description']!=current['description'] or json.loads(annotation['tags'])!=current['tags'] or annotation['model']!=current['model'] or annotation['confidence']!=current['confidence'] or annotation['asset_hash']!=e['asset_hash'] or annotation['method']!='model-visual' or annotation['evidence']!=latest['evidence']:
                    raise ValueError('Active annotation differs from revision parent')
            elif annotation: raise ValueError('Unexpected active annotation for ambiguous parent')
            if identical:
                counts['unchanged']+=1
                continue
            evidence=dict(e,packet_id=manifest['packet_id'],limitations=r['limitations'],verification='revision: image bytes and catalog metadata checked',previous_review_hash=previous_hash,revision_hash=response_hash)
            db.execute('INSERT INTO annotation_revisions VALUES (?,?,?,?,?,?)',(manifest['packet_id'],iid,previous_hash,response_hash,catalog.canonical(r),catalog.canonical(evidence)))
            if r['status']=='accepted':
                db.execute('INSERT OR REPLACE INTO annotations VALUES (?,?,?,?,?,?,?,?)',(e['key'],e['asset_hash'],r['description'],catalog.canonical(r['tags']),'model-visual',r['model'],r['confidence'],catalog.canonical(evidence)))
            else: db.execute('DELETE FROM annotations WHERE key=?',(e['key'],))
            asset=db.execute('SELECT * FROM assets WHERE key=?',(e['key'],)).fetchone()
            catalog.searchable(db,asset['key'],asset['name'],json.loads(asset['payload']),asset['hash'])
            counts['revised']+=1; counts[r['status']]+=1
    return counts


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',required=True);p.add_argument('--manifest',required=True);p.add_argument('--previous',required=True);p.add_argument('--responses',required=True)
    a=p.parse_args(); db=catalog.connect(a.db)
    try: print(json.dumps(revise(db,visual.read_json(a.manifest),visual.read_json(a.previous),visual.read_json(a.responses)),indent=2))
    finally: db.close()

if __name__=='__main__':main()
