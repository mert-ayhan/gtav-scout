import importlib.util,json,sqlite3,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('batch',Path(__file__).parents[1]/'scripts/plan-asset-catalog-batch.py');batch=importlib.util.module_from_spec(spec);spec.loader.exec_module(batch)
class BatchTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
  self.db.executescript("CREATE TABLE assets(key TEXT,game TEXT,kind TEXT,hash TEXT,payload TEXT);CREATE TABLE annotations(key TEXT,asset_hash TEXT,method TEXT DEFAULT 'model-visual',confidence REAL DEFAULT 1,evidence TEXT DEFAULT '{}');CREATE TABLE visual_reviews(key TEXT,status TEXT,evidence TEXT);")
  for i in range(6):self.db.execute('INSERT INTO assets VALUES(?,?,?,?,?)',(str(i),'gta5','model','v1',json.dumps({'record':{'category':'interior'}})))
 def tearDown(self):self.db.close()
 def test_annotation_and_reviewed_assets_excluded(self):
  self.db.execute('INSERT INTO annotations(key,asset_hash) VALUES(?,?)',('0','v1'));self.db.execute('INSERT INTO visual_reviews VALUES(?,?,?)',('1','accepted','{"asset_hash":"v1"}'))
  rows,_=batch.pending(self.db);self.assertEqual({r['key'] for r in rows},{'2','3','4','5'})
 def test_ambiguous_separate_queue(self):
  self.db.execute('INSERT INTO visual_reviews VALUES(?,?,?)',('1','ambiguous','{"asset_hash":"v1"}'));rows,review=batch.pending(self.db)
  self.assertNotIn('1',{r['key'] for r in rows});self.assertEqual(review,[{'key':'1','reason':'ambiguous'}])
 def test_stale_reviews_reenter_new_queue(self):
  self.db.execute('INSERT INTO visual_reviews VALUES(?,?,?)',('1','accepted','{"asset_hash":"v0"}'));rows,_=batch.pending(self.db);self.assertIn('1',{r['key'] for r in rows})
 def test_latest_review_resolves_ambiguity(self):
  for status in ['ambiguous','accepted']:self.db.execute('INSERT INTO visual_reviews VALUES(?,?,?)',('1',status,'{"asset_hash":"v1"}'))
  rows,review=batch.pending(self.db);self.assertEqual(review,[]);self.assertNotIn('1',{r['key'] for r in rows})
 def test_balancing_prevents_large_group_starvation(self):
  rows=[{'key':str(i),'game':'gta5','kind':'model','category':'huge'} for i in range(100)]+[{'key':'rare','game':'gta5','kind':'texture','category':'rare'}]
  chosen=batch.choose_batch(rows,4,'fixed');self.assertIn('rare',{r['key'] for r in chosen});self.assertEqual(len(chosen),4)
 def test_reproducible_independent_of_input_order(self):
  rows,_=batch.pending(self.db);self.assertEqual(batch.choose_batch(rows,4,'seed'),batch.choose_batch(list(reversed(rows)),4,'seed'))
 def test_size_limits(self):
  for n in [0,1001]:
   with self.assertRaises(ValueError):batch.choose_batch([],n,'seed')
 def test_filters(self):
  self.assertEqual(batch.pending(self.db,kind='texture'),([],[]));self.assertEqual(batch.pending(self.db,categories={'nature'}),([],[]))
 def test_legacy_uncertain_annotation_enters_review_queue(self):
  self.db.execute('INSERT INTO annotations VALUES(?,?,?,?,?)',('0','v1','model-visual',.2,'{"needs_another_view":true}'))
  rows,review=batch.pending(self.db);self.assertNotIn('0',{r['key'] for r in rows});self.assertEqual(review,[{'key':'0','reason':'unresolved-or-stale-visual-annotation'}])
if __name__=='__main__':unittest.main()
