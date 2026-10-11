#!/usr/bin/env python3
"""Plan a bounded, category-balanced batch of assets not yet visually reviewed."""
import argparse,collections,hashlib,json,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import asset_catalog as catalog

def choose_batch(rows,limit,seed):
 if not 1<=limit<=1000:raise ValueError('limit must be between1 and1000')
 groups=collections.defaultdict(list)
 for row in rows:groups[(row['game'],row['kind'],row['category'])].append(row)
 for group in groups:
  groups[group]=collections.deque(sorted(groups[group],key=lambda r:hashlib.sha256((str(seed)+'\0'+r['key']).encode()).hexdigest()))
 selected=[]
 while len(selected)<limit:
  added=False
  for group in sorted(groups):
   if groups[group]:selected.append(groups[group].popleft());added=True
   if len(selected)==limit:break
  if not added:break
 return selected

def pending(db,game=None,kind=None,categories=None):
 reviewed={};needs_review=[]
 if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='visual_reviews'").fetchone():
  for r in db.execute('SELECT key,status,evidence FROM visual_reviews ORDER BY rowid'):
   evidence=json.loads(r['evidence']);reviewed[r['key']]={'status':r['status'],'hash':evidence['asset_hash']}
 rows=[]
 for a in db.execute('SELECT a.*,n.key annotation_key,n.method,n.confidence,n.evidence FROM assets a LEFT JOIN annotations n ON n.key=a.key AND n.asset_hash=a.hash'):
  if game and a['game']!=game or kind and a['kind']!=kind:continue
  category=json.loads(a['payload'])['record'].get('category','unknown')
  if categories and category not in categories:continue
  review=reviewed.get(a['key']);current=review and review['hash']==a['hash']
  if a['annotation_key'] and not catalog.annotation_is_usable(db,a):
   needs_review.append({'key':a['key'],'reason':'unresolved-or-stale-visual-annotation'});continue
  if current:
   if review['status']!='accepted':needs_review.append({'key':a['key'],'reason':review['status']})
   continue
  if a['annotation_key']:continue
  rows.append({'key':a['key'],'game':a['game'],'kind':a['kind'],'category':category})
 return rows,needs_review

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',default='output/asset-catalog/visual-v2/catalog.sqlite');p.add_argument('--out',required=True);p.add_argument('--limit',type=int,default=80);p.add_argument('--seed',default='next-batch');p.add_argument('--game',choices=['gta5']);p.add_argument('--kind',choices=['model','texture']);p.add_argument('--categories',help='Optional comma-separated metadata categories; may be inaccurate.')
 a=p.parse_args();path=Path(a.db).resolve()
 if not path.is_file():p.error('Existing catalog required')
 db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
 rows,review=pending(db,a.game,a.kind,set(a.categories.split(',')) if a.categories else None);selected=choose_batch(rows,a.limit,a.seed);db.close()
 out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True)
 report={'seed':a.seed,'eligibleUnreviewed':len(rows),'selected':len(selected),'sampling':'Round-robin source metadata categories; deterministic hash shuffle inside strata. This is exploration coverage, not a relevance ranking.','strata':dict(collections.Counter('/'.join((r['game'],r['kind'],r['category'])) for r in selected)),'needsReview':review}
 for name,data in [('keys.json',[r['key'] for r in selected]),('plan.json',report)]:
  target=out/name
  if target.exists() and json.loads(target.read_text())!=data:p.error('Output plan already exists with different content; choose a new output directory.')
 for name,data in [('keys.json',[r['key'] for r in selected]),('plan.json',report)]: (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
