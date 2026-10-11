"""Independent interleaving checks for the original visual import path."""
import io,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import asset_catalog as c
import asset_catalog_visual as v

class ImportRaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.db=c.connect(self.root/'db.sqlite');self.addCleanup(self.db.close)
        for i in (1,2):
            payload={'record':{'id':i,'name':'fixture'+str(i)},'hints':[]}
            self.db.execute('INSERT INTO assets VALUES (?,?,?,?,?,?)',(f'gta5:model:{i}','gta5','model','fixture'+str(i),c.digest(payload),c.canonical(payload)))
        self.db.commit();buf=io.BytesIO();Image.new('RGB',(12,12),'red').save(buf,format='PNG')
        report=v.prepare(self.db,['gta5:model:1','gta5:model:2'],self.root/'packet',fetcher=lambda _:buf.getvalue())
        self.manifest=v.read_json(report['manifest'])
        self.responses={'packet_id':self.manifest['packet_id'],'reviews':[{'image_id':e['image_id'],'status':'accepted','description':'Synthetic test fixture','tags':['fixture'],'confidence':.8,'model':'TEST-NOT-VISION','limitations':'Test only'} for e in self.manifest['entries']]}
    def test_image_change_after_manifest_validation_rejected(self):
        original=v.validate_manifest;calls=0
        def validate_then_change(manifest):
            nonlocal calls
            original(manifest);calls+=1
            if calls==1:Path(manifest['entries'][0]['image_path']).write_bytes(b'changed after validation')
        with patch.object(v,'validate_manifest',validate_then_change):
            with self.assertRaises(ValueError):v.import_reviews(self.db,self.manifest,self.responses)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM annotations').fetchone()[0],0)
    def test_metadata_change_after_last_staged_read_rejected(self):
        db=self.db;root=self.root;triggered=[]
        class Cursor:
            def __init__(self,cursor):self.cursor=cursor
            def fetchone(self):
                row=self.cursor.fetchone()
                if row and row['key']=='gta5:model:2' and not triggered:
                    triggered.append(True)
                    other=sqlite3.connect(root/'db.sqlite',timeout=.1)
                    try:other.execute("UPDATE assets SET hash='changed concurrently' WHERE key='gta5:model:2'");other.commit()
                    finally:other.close()
                return row
            def __getattr__(self,name):return getattr(self.cursor,name)
        class Proxy:
            def execute(self,sql,*args):
                cur=db.execute(sql,*args)
                return Cursor(cur) if sql.startswith('SELECT * FROM assets WHERE key=') else cur
            def __enter__(self):db.__enter__();return self
            def __exit__(self,*args):return db.__exit__(*args)
            def __getattr__(self,name):return getattr(db,name)
        with self.assertRaises((ValueError,sqlite3.OperationalError)):
            v.import_reviews(Proxy(),self.manifest,self.responses)
        self.assertTrue(triggered)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM annotations').fetchone()[0],0)
    def test_interrupted_second_write_rolls_back_and_retries(self):
        original=c.searchable;calls=[]
        def interrupt_second(*args,**kwargs):
            calls.append(args[1])
            original(*args,**kwargs)
            if len(calls)==2:raise RuntimeError('simulated interrupted import')
        with patch.object(c,'searchable',interrupt_second):
            with self.assertRaisesRegex(RuntimeError,'simulated interrupted'):
                v.import_reviews(self.db,self.manifest,self.responses)
        self.assertEqual(len(calls),2)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM annotations').fetchone()[0],0)
        has_reviews=self.db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='visual_reviews'").fetchone()[0]
        if has_reviews:self.assertEqual(self.db.execute('SELECT COUNT(*) FROM visual_reviews').fetchone()[0],0)
        report=v.import_reviews(self.db,self.manifest,self.responses)
        self.assertEqual(report['accepted'],2)
        self.assertEqual(v.import_reviews(self.db,self.manifest,self.responses)['unchanged'],2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM annotations').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM visual_reviews').fetchone()[0],2)
    def test_existing_transaction_is_preserved_on_rejection(self):
        self.db.execute("UPDATE assets SET name='uncommitted marker' WHERE key='gta5:model:1'")
        with self.assertRaisesRegex(ValueError,'own immediate transaction'):
            v.import_reviews(self.db,self.manifest,self.responses)
        self.assertTrue(self.db.in_transaction)
        self.assertEqual(self.db.execute("SELECT name FROM assets WHERE key='gta5:model:1'").fetchone()[0],'uncommitted marker')
        other=sqlite3.connect(self.root/'db.sqlite')
        try:self.assertEqual(other.execute("SELECT name FROM assets WHERE key='gta5:model:1'").fetchone()[0],'fixture1')
        finally:other.close()
        self.db.rollback()
    def test_changed_image_after_import_is_not_usable_evidence(self):
        v.import_reviews(self.db,self.manifest,self.responses)
        entry=self.manifest['entries'][0]
        annotation=self.db.execute('SELECT * FROM annotations WHERE key=?',(entry['key'],)).fetchone()
        self.assertTrue(c.annotation_is_usable(self.db,annotation))
        Path(entry['image_path']).write_bytes(b'changed after successful import')
        self.assertFalse(c.annotation_is_usable(self.db,annotation))

if __name__=='__main__':unittest.main()
