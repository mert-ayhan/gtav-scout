import copy,io,json,sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import asset_catalog as c
import asset_catalog_visual as v
import asset_catalog_revision as rev
import asset_catalog_semantic as sem
import numpy as np

class FakeEncoder:
    identity='fixture-only:revision-tests'
    def encode(self,texts,query=False): return np.tile([1.,0.],(len(texts),1))

class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.db=c.connect(self.root/'db.sqlite');self.addCleanup(self.db.close)
        for i in [1,2]:
            p={'record':{'id':i,'name':'opaque'},'hints':[],'catalogSource':'fixture'}
            self.db.execute('INSERT INTO assets VALUES (?,?,?,?,?,?)',(f'gta5:model:{i}','gta5','model','opaque',c.digest(p),c.canonical(p)));c.searchable(self.db,f'gta5:model:{i}','opaque',p,c.digest(p))
        self.db.commit();image=io.BytesIO();Image.new('RGB',(8,8),'red').save(image,format='PNG')
        report=v.prepare(self.db,['gta5:model:1','gta5:model:2'],self.root/'packet',fetcher=lambda _:image.getvalue());self.manifest=v.read_json(report['manifest'])
        self.old={'packet_id':self.manifest['packet_id'],'reviews':[{'image_id':e['image_id'],'status':'accepted','description':'Synthetic red box','tags':['box'],'confidence':.8,'model':'synthetic-test-fixture','limitations':'Synthetic tests only'} for e in self.manifest['entries']]}
        v.import_reviews(self.db,self.manifest,self.old);self.new=copy.deepcopy(self.old)
        for r in self.new['reviews']:r['description']='Synthetic red box with visible lid; possible storage.'
    def test_revision_history_and_repeat(self):
        original=[tuple(r) for r in self.db.execute('select * from visual_reviews')]
        self.assertEqual(rev.revise(self.db,self.manifest,self.old,self.new)['revised'],2)
        self.assertEqual(rev.revise(self.db,self.manifest,self.old,self.new)['unchanged'],2)
        self.assertEqual(original,[tuple(r) for r in self.db.execute('select * from visual_reviews')])
        self.assertEqual(self.db.execute('select count(*) from annotation_revisions').fetchone()[0],2)
    def test_invalid_batch_atomic(self):
        self.new['reviews'][1]['confidence']=float('nan')
        with self.assertRaises(ValueError):rev.revise(self.db,self.manifest,self.old,self.new)
        self.assertTrue(all(r[0]=='Synthetic red box' for r in self.db.execute('select description from annotations')))
    def test_parent_conflict_rolls_back_earlier_entry(self):
        bad=copy.deepcopy(self.old);bad['reviews'][1]['description']='different parent'
        with self.assertRaises(ValueError):rev.revise(self.db,self.manifest,bad,self.new)
        self.assertEqual(self.db.execute('select count(*) from annotation_revisions').fetchone()[0],0)
        self.assertTrue(all(r[0]=='Synthetic red box' for r in self.db.execute('select description from annotations')))
    def test_duplicate_foreign_and_stale_image(self):
        for altered in ['duplicate','foreign']:
            bad=copy.deepcopy(self.new)
            if altered=='duplicate':bad['reviews'].append(bad['reviews'][0])
            else:bad['reviews'][0]['image_id']='foreign'
            with self.assertRaises(ValueError):rev.revise(self.db,self.manifest,self.old,bad)
        Path(self.manifest['entries'][0]['image_path']).write_bytes(b'changed')
        with self.assertRaises(ValueError):rev.revise(self.db,self.manifest,self.old,self.new)
    def test_stale_metadata_and_out_of_band_annotation(self):
        self.db.execute("update assets set hash='changed' where key='gta5:model:1'");self.db.commit()
        with self.assertRaises(ValueError):rev.revise(self.db,self.manifest,self.old,self.new)
    def test_annotation_tampering_rejected(self):
        self.db.execute("update annotations set description='external edit' where key='gta5:model:2'");self.db.commit()
        with self.assertRaises(ValueError):rev.revise(self.db,self.manifest,self.old,self.new)
        self.assertEqual(self.db.execute('select count(*) from annotation_revisions').fetchone()[0],0)
    def test_mutation_between_validation_and_write_is_rejected(self):
        original=v.import_reviews
        def interleaved(staged,manifest,responses):
            result=original(staged,manifest,responses)
            self.db.execute("update assets set hash='concurrent-change' where key='gta5:model:2'")
            self.db.commit()
            return result
        with patch.object(v,'import_reviews',side_effect=interleaved):
            with self.assertRaises(ValueError):rev.revise(self.db,self.manifest,self.old,self.new)
        self.assertEqual(self.db.execute('select count(*) from annotation_revisions').fetchone()[0],0)
        self.assertTrue(all(r[0]=='Synthetic red box' for r in self.db.execute('select description from annotations')))
    def test_existing_transaction_rejected_without_commit(self):
        self.db.execute("update annotations set description='pending change' where key='gta5:model:1'")
        with self.assertRaises(ValueError):rev.revise(self.db,self.manifest,self.old,self.new)
        self.assertTrue(self.db.in_transaction)
        self.db.rollback()

    def test_old_embeddings_excluded_until_rebuild(self):
        enc=FakeEncoder();sem.build(self.db,enc)
        rev.revise(self.db,self.manifest,self.old,self.new)
        result=sem.search(self.db,enc,'box')
        self.assertEqual(result['results'],[])
        self.assertEqual(sem.build(self.db,enc)['embedded'],2)

if __name__=='__main__':unittest.main()
