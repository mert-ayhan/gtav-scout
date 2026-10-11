#!/usr/bin/env python3
"""Query-specific visual review packets; never writes judgments into global annotations."""
import argparse, json
from pathlib import Path
import asset_catalog as catalog
import asset_catalog_visual as visual
VERSION='query-visual-shortlist-v1'

def retrieve(db,encoder,query,kind=None,limit=30,corpus='annotations',game=None,diversify_pixels=False):
    import asset_catalog_semantic as semantic
    if not isinstance(query,str) or not query.strip():raise ValueError('Nonempty query required')
    if not 1<=limit<=100:raise ValueError('limit must be 1..100 per retrieval channel')
    sem=semantic.search(db,encoder,query,limit,corpus,game,kind,False,diversify_pixels)
    merged={}
    for rank,row in enumerate(sem['results'],1):
        merged[row['key']]={'key':row['key'],'kind':row['kind'],'semantic_rank':rank,'cosine_score':row['cosineScore'],'lexical_rank':None}
        for field in ('pixel_group_sha256','equivalent_pixel_occurrences','equivalence_scope'):
            if field in row:merged[row['key']][field]=row[field]
    lexical=catalog.search(db,query,1000 if diversify_pixels else limit,kind,game)
    if diversify_pixels:lexical=semantic.diversify_texture_pixels(db,lexical)[:limit]
    for rank,row in enumerate(lexical,1):
        target=merged.setdefault(row['key'],{'key':row['key'],'kind':row['kind'],'semantic_rank':None,'cosine_score':None,'lexical_rank':None});target['lexical_rank']=rank
        for field in ('pixel_group_sha256','equivalent_pixel_occurrences','equivalence_scope'):
            if field in row:target.setdefault(field,row[field])
    if diversify_pixels:return semantic.diversify_texture_pixels(db,list(merged.values())),{k:v for k,v in sem.items() if k!='results'}
    return list(merged.values()),{k:v for k,v in sem.items() if k!='results'}

def reuse_views(db,key):
    row=db.execute('SELECT n.* FROM annotations n JOIN assets a ON a.key=n.key AND a.hash=n.asset_hash WHERE a.key=?',(key,)).fetchone()
    if not row:return None
    if not catalog.annotation_is_fresh(db,row):return None
    try:
        e=json.loads(row['evidence']); views=catalog.evidence_views(e)
        if all(visual.sha(Path(v['path']).read_bytes())==v['sha256'] for v in views):return [v['path'] for v in views]
    except (KeyError,ValueError,OSError,TypeError):pass
    return None

def validate_constraints(constraints):
    if not isinstance(constraints,list):raise ValueError('Constraints must be an array')
    ids=set()
    for constraint in constraints:
        if not isinstance(constraint,dict) or not all(isinstance(constraint.get(k),str) and constraint[k].strip() for k in ('id','requirement')):raise ValueError('Constraint ID and visible requirement required')
        if constraint['id'] in ids:raise ValueError('Duplicate constraint ID')
        ids.add(constraint['id'])
    return constraints

def prepare(db,encoder,query,out,kind=None,limit=30,corpus='annotations',game=None,fetcher=visual.fetch_image,constraints=None,diversify_pixels=False):
    constraints=validate_constraints(constraints or [])
    candidates,coverage=retrieve(db,encoder,query,kind,limit,corpus,game,diversify_pixels)
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    for candidate in candidates:
        row=db.execute('SELECT hash,game,kind,name FROM assets WHERE key=?',(candidate['key'],)).fetchone()
        candidate.update(asset_hash=row['hash'],game=row['game'],kind=row['kind'],name=row['name'])
    overrides={}
    for c in candidates:
        views=reuse_views(db,c['key'])
        if views:overrides[c['key']]=views
    if candidates:
        report=visual.prepare(db,[c['key'] for c in candidates],out/'images',fetcher=fetcher,overrides=overrides)
        manifest=visual.read_json(report['manifest'])
    else:
        manifest={'version':visual.VERSION,'entries':[],'packet_id':visual.packet_id([])}
        report={'ready':0,'failed':[],'cached':0}
    payload={'version':VERSION,'query':query,'kind':kind,'game':game,'limit_per_channel':limit,'corpus':corpus,'retrieval':coverage,'candidates':candidates,'visual_manifest':manifest,'preview_failures':report['failed']}
    if constraints:payload['constraints']=constraints
    identity=catalog.digest(payload)
    packet={'query_packet_id':identity,'payload':payload,'instructions':'Inspect the actual candidate images against this query. Mark relevant, partial, irrelevant, or uncertain, with a visible-evidence reason. These are query-specific judgments, never global object descriptions. Scores are retrieval signals, not relevance probabilities. Unreviewed candidates remain explicitly unresolved.', 'images':[{k:e[k] for k in ('image_id','image_path','image_sha256')} for e in manifest['entries']], 'response_schema':{'query_packet_id':identity,'reviews':[{'image_id':'COPY_ID','status':'relevant | partial | irrelevant | uncertain','reason':'query-specific visible evidence','reviewer':'actual reviewer'}]}}
    if constraints:
        packet['instructions']+=' For every candidate, check every explicit constraint separately against visible evidence. Use pass, fail, or unknown; never infer hidden geometry. A direct answer requires pass for every constraint. No direct candidate means abstention, not proof of absence from the game.'
        packet['response_schema']['reviews'][0]['constraint_checks']=[{'id':c['id'],'verdict':'pass | fail | unknown','reason':'visible evidence for this specific constraint'} for c in constraints]
    path=out/identity/'query-packet.json'
    if path.exists() and visual.read_json(path)!=packet:raise ValueError('Immutable query packet collision')
    visual.write_json(path,packet)
    sheets=visual.sheets(manifest,path.parent/'sheets') if manifest['entries'] else None
    result={'packet':str(path),'query_packet_id':identity,'candidates':len(candidates),'ready_images':report['ready'],'preview_failures':len(report['failed']),'sheets':sheets}
    visual.write_json(out/'latest.json',result);return result

def validate_packet(db,packet):
    p=packet['payload']
    if p.get('version')!=VERSION or catalog.digest(p)!=packet.get('query_packet_id'):raise ValueError('Query packet content mismatch')
    validate_constraints(p.get('constraints',[]))
    visual.validate_manifest(p['visual_manifest'])
    expected=[{k:e[k] for k in ('image_id','image_path','image_sha256')} for e in p['visual_manifest']['entries']]
    if packet.get('images')!=expected:raise ValueError('Image packet mismatch')
    keys=[c['key'] for c in p['candidates']]
    if len(keys)!=len(set(keys)):raise ValueError('Repeated candidate key')
    by_key={c['key']:c for c in p['candidates']}
    for c in p['candidates']:
        row=db.execute('SELECT hash FROM assets WHERE key=?',(c['key'],)).fetchone()
        if not row or row['hash']!=c['asset_hash']:raise ValueError('Stale candidate asset metadata')
    for e in p['visual_manifest']['entries']:
        if e['key'] not in by_key or e['asset_hash']!=by_key[e['key']]['asset_hash']:raise ValueError('Image/candidate binding mismatch')
    return p

def finalize(db,packet,responses):
    p=validate_packet(db,packet)
    if responses.get('query_packet_id')!=packet['query_packet_id']:raise ValueError('Query response identity mismatch')
    reviews=responses.get('reviews')
    if not isinstance(reviews,list):raise ValueError('Review array required')
    images={e['image_id']:e for e in p['visual_manifest']['entries']};reviewed={}
    for r in reviews:
        iid=r.get('image_id')
        if iid not in images or iid in reviewed:raise ValueError('Unknown or duplicate image ID')
        if r.get('status') not in ('relevant','partial','irrelevant','uncertain'):raise ValueError('Invalid relevance status')
        if not all(isinstance(r.get(k),str) and r[k].strip() for k in ('reason','reviewer')):raise ValueError('Reason and reviewer required')
        constraints=p.get('constraints',[])
        if constraints:
            checks=r.get('constraint_checks')
            if not isinstance(checks,list) or len(checks)!=len(constraints):raise ValueError('Every explicit constraint needs an individual check')
            if any(not isinstance(c,dict) for c in checks):raise ValueError('Invalid constraint check')
            if {c.get('id') for c in checks}!={c['id'] for c in constraints}:raise ValueError('Constraint check identity mismatch')
            for check in checks:
                if check.get('verdict') not in ('pass','fail','unknown') or not isinstance(check.get('reason'),str) or not check['reason'].strip():raise ValueError('Constraint verdict and visual reason required')
            if r['status']=='relevant' and any(c['verdict']!='pass' for c in checks):
                r=dict(r,proposed_status='relevant',status='partial' if any(c['verdict']=='fail' for c in checks) else 'uncertain',gate_reason='Explicit constraints not all visually verified')
        reviewed[iid]=r
    by_key={e['key']:e for e in images.values()};groups={s:[] for s in ('relevant','partial','irrelevant','uncertain','unreviewed')}
    for c in p['candidates']:
        e=by_key.get(c['key']);r=reviewed.get(e['image_id']) if e else None
        status=r['status'] if r else 'unreviewed'
        groups[status].append(dict(c,image_id=e['image_id'] if e else None,review=r,evidence=e,preview_status='ready' if e else 'failed'))
    return {'query_packet_id':packet['query_packet_id'],'query':p['query'],'groups':groups,'candidate_count':len(p['candidates']),'reviewed_count':len(reviewed),'unreviewed_count':len(groups['unreviewed']),'preview_failures':p['preview_failures'],'retrieval':p['retrieval'],'global_annotations_modified':False,'constraints':p.get('constraints',[]),'decision':'answered' if groups['relevant'] else 'abstained','decision_reason':'Visually reviewed direct candidates available' if groups['relevant'] else 'No reviewed direct match in this candidate pool; this does not prove absence from the game','constraint_verification':'explicit_per_candidate' if p.get('constraints') else 'unstructured_query_review'}

def build_parser():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--db',default='output/asset-catalog/visual-v2/catalog.sqlite')
    sub=parser.add_subparsers(dest='command',required=True);p=sub.add_parser('prepare')
    p.add_argument('--query',required=True);p.add_argument('--kind',choices=['model','texture']);p.add_argument('--game',choices=['gta5']);p.add_argument('--out',required=True);p.add_argument('--limit',type=int,default=30);p.add_argument('--corpus',choices=['annotations','metadata'],default='annotations')
    p.add_argument('--constraints',help='JSON array of {id, requirement}; frozen with query, checked individually against images')
    p.add_argument('--diversify-pixels',action='store_true',help='Review one representative per proven texture pixel group; occurrence context remains separate')
    p=sub.add_parser('finalize');p.add_argument('--packet',required=True);p.add_argument('--responses',required=True);p.add_argument('--out',required=True)
    return parser

def main():
    parser=build_parser()
    a=parser.parse_args()
    if not Path(a.db).is_file():parser.error('Existing catalog required')
    db=catalog.connect(a.db)
    if a.command=='prepare':
        import asset_catalog_semantic as semantic
        result=prepare(db,semantic.Encoder(),a.query,a.out,a.kind,a.limit,a.corpus,a.game,constraints=visual.read_json(a.constraints) if a.constraints else None,diversify_pixels=a.diversify_pixels)
    else:
        result=finalize(db,visual.read_json(a.packet),visual.read_json(a.responses));visual.write_json(a.out,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
