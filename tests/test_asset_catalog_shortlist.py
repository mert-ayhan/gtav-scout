import io,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
from PIL import Image
import asset_catalog as c
import asset_catalog_semantic as sem
import asset_catalog_shortlist as s
import asset_catalog_visual as v
class FakeEncoder:
    identity='shortlist-test-synthetic-encoder'
    def encode(self,texts,query=False):return np.array([[1.,0.] if query or 'round' in t else [0.,1.] for t in texts])
def png():
    b=io.BytesIO();Image.new('RGB',(16,16),'red').save(b,format='PNG');return b.getvalue()
class ShortlistTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=c.connect(self.root/'db.sqlite');self.encoder=FakeEncoder()
        for i in range(1,5):
            name='metal' if i<3 else 'round'
            p={'record':{'id':i,'name':name},'hints':[],'catalogSource':'fixture'};key=f'gta5:model:{i}'
            self.db.execute('INSERT INTO assets VALUES (?,?,?,?,?,?)',(key,'gta5','model',name,c.digest(p),c.canonical(p)))
            c.searchable(self.db,key,name,p,c.digest(p))
        self.db.commit();sem.build(self.db,self.encoder,'metadata')
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def prepare(self,query='metal',fetcher=lambda u:png()):
        r=s.prepare(self.db,self.encoder,query,self.root/'packets',kind='model',limit=2,corpus='metadata',fetcher=fetcher)
        return v.read_json(r['packet'])
    def responses(self,p):return {'query_packet_id':p['query_packet_id'],'reviews':[{'image_id':p['images'][0]['image_id'],'status':'relevant','reason':'Synthetic visible form matches request','reviewer':'test-fixture'}]}
    def test_union_preserves_both_channels(self):
        rows,coverage=s.retrieve(self.db,self.encoder,'metal',limit=2,corpus='metadata')
        self.assertEqual(len(rows),4);self.assertEqual([r['key'] for r in rows],['gta5:model:3','gta5:model:4','gta5:model:1','gta5:model:2'])
    def test_overlap_not_duplicated(self):
        rows,_=s.retrieve(self.db,self.encoder,'round',limit=2,corpus='metadata');self.assertEqual(len(rows),2)
    def test_partial_reviews_preserve_unreviewed(self):
        p=self.prepare();r=s.finalize(self.db,p,self.responses(p));self.assertEqual(r['candidate_count'],4);self.assertEqual(r['unreviewed_count'],3)
        self.assertEqual(sum(map(len,r['groups'].values())),4)
    def test_no_annotation_writes(self):
        before=self.db.execute('SELECT * FROM annotations').fetchall();p=self.prepare();s.finalize(self.db,p,self.responses(p));self.assertEqual(before,self.db.execute('SELECT * FROM annotations').fetchall())
    def test_query_tamper_rejected(self):
        p=self.prepare();r=self.responses(p);p['payload']['query']='tampered'
        with self.assertRaisesRegex(ValueError,'content mismatch'):s.finalize(self.db,p,r)
    def test_response_query_identity_rejected(self):
        p=self.prepare();r=self.responses(p);r['query_packet_id']='wrong'
        with self.assertRaisesRegex(ValueError,'identity'):s.finalize(self.db,p,r)
    def test_unknown_id_rejected(self):
        p=self.prepare();r=self.responses(p);r['reviews'][0]['image_id']='wrong'
        with self.assertRaises(ValueError):s.finalize(self.db,p,r)
    def test_duplicate_review_rejected(self):
        p=self.prepare();r=self.responses(p);r['reviews']*=2
        with self.assertRaises(ValueError):s.finalize(self.db,p,r)
    def test_stale_image_rejected(self):
        p=self.prepare();r=self.responses(p);Path(p['images'][0]['image_path']).write_bytes(b'changed')
        with self.assertRaises(ValueError):s.finalize(self.db,p,r)
    def test_stale_metadata_rejected(self):
        p=self.prepare();r=self.responses(p);self.db.execute("UPDATE assets SET hash='changed' WHERE key='gta5:model:1'")
        with self.assertRaisesRegex(ValueError,'Stale'):s.finalize(self.db,p,r)
    def test_image_wrapper_tamper_rejected(self):
        p=self.prepare();r=self.responses(p);p['images'][0]['image_path']='wrong'
        with self.assertRaisesRegex(ValueError,'Image packet'):s.finalize(self.db,p,r)
    def test_failed_previews_preserved(self):
        def fail(url):raise OSError('offline')
        p=self.prepare(fetcher=fail);r=s.finalize(self.db,p,{'query_packet_id':p['query_packet_id'],'reviews':[]})
        self.assertEqual(r['unreviewed_count'],4);self.assertEqual(len(r['preview_failures']),4)
    def test_missing_review_reason_rejected(self):
        p=self.prepare();r=self.responses(p);r['reviews'][0]['reason']=''
        with self.assertRaises(ValueError):s.finalize(self.db,p,r)
    def test_empty_candidates(self):
        self.db.execute('DELETE FROM assets');self.db.execute('DELETE FROM search');self.db.commit()
        p=self.prepare();r=s.finalize(self.db,p,{'query_packet_id':p['query_packet_id'],'reviews':[]});self.assertEqual(r['candidate_count'],0)
    def test_no_vector_build_during_prepare(self):
        before=list(self.db.execute('SELECT * FROM semantic_vectors'));self.prepare();self.assertEqual(before,list(self.db.execute('SELECT * FROM semantic_vectors')))
    def test_bounds(self):
        for n in (0,101):
            with self.assertRaises(ValueError):s.retrieve(self.db,self.encoder,'metal',limit=n)
    def constrained(self):
        r=s.prepare(self.db,self.encoder,'fixture shape',self.root/'constrained',kind='model',limit=2,corpus='metadata',fetcher=lambda u:png(),constraints=[{'id':'geometry','requirement':'Two visibly separate tiers'}])
        return v.read_json(r['packet'])
    def test_explicit_constraints_require_individual_evidence(self):
        p=self.constrained()
        with self.assertRaisesRegex(ValueError,'individual check'):s.finalize(self.db,p,self.responses(p))
    def test_unknown_or_failed_constraint_cannot_be_direct_answer(self):
        for verdict,group in [('unknown','uncertain'),('fail','partial')]:
            p=self.constrained();r=self.responses(p)
            r['reviews'][0]['constraint_checks']=[{'id':'geometry','verdict':verdict,'reason':'Synthetic test evidence, not a real asset judgment'}]
            result=s.finalize(self.db,p,r)
            self.assertEqual(result['decision'],'abstained');self.assertEqual(len(result['groups'][group]),1)
            self.assertEqual(r['reviews'][0]['status'],'relevant')
    def test_verified_constraints_allow_direct_answer(self):
        p=self.constrained();r=self.responses(p)
        r['reviews'][0]['constraint_checks']=[{'id':'geometry','verdict':'pass','reason':'Synthetic two tier geometry'}]
        result=s.finalize(self.db,p,r)
        self.assertEqual(result['decision'],'answered');self.assertEqual(len(result['groups']['relevant']),1)
    def test_constraint_identity_tamper_rejected(self):
        p=self.constrained();r=self.responses(p);p['payload']['constraints'][0]['requirement']='changed'
        with self.assertRaisesRegex(ValueError,'content mismatch'):s.finalize(self.db,p,r)
    def test_invalid_constraint_rejected_before_preparation(self):
        for constraints in [[{'id':'x','requirement':''}],[{'id':'x','requirement':'one'},{'id':'x','requirement':'two'}]]:
            with self.assertRaises(ValueError):s.validate_constraints(constraints)
    def test_legacy_preview_count_reuses_verified_image(self):
        path=self.root/'legacy.png';path.write_bytes(png())
        asset=self.db.execute("SELECT * FROM assets WHERE key='gta5:model:1'").fetchone()
        evidence={'preview':str(path),'sha256':v.sha(path.read_bytes()),'views':1}
        self.db.execute('INSERT INTO annotations VALUES (?,?,?,?,?,?,?,?)',(asset['key'],asset['hash'],'Synthetic fixture','[]','model-visual','fixture',.8,c.canonical(evidence)));self.db.commit()
        self.assertEqual(s.reuse_views(self.db,asset['key']),[str(path)])
        path.write_bytes(b'changed');self.assertIsNone(s.reuse_views(self.db,asset['key']))
if __name__=='__main__':unittest.main()
