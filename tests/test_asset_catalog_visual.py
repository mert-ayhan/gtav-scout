import copy, importlib.util, io, json, sqlite3, sys, tempfile, unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import asset_catalog as c
import asset_catalog_visual as v

def png(color='red'):
    b=io.BytesIO();Image.new('RGB',(24,24),color).save(b,format='PNG');return b.getvalue()
class VisualTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=c.connect(self.root/'catalog.sqlite')
        for i in (1,2):
            p={'record':{'id':i,'name':'opaque'+str(i)},'hints':[],'catalogSource':'fixture'}
            self.db.execute('INSERT INTO assets VALUES (?,?,?,?,?,?)',(f'gta5:model:{i}','gta5','model','opaque'+str(i),c.digest(p),c.canonical(p)))
            c.searchable(self.db,f'gta5:model:{i}','opaque'+str(i),p,c.digest(p))
        self.db.commit()
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def prep(self,**kwargs):
        report=v.prepare(self.db,['gta5:model:1','gta5:model:2'],self.root/'packets',fetcher=lambda u:png(),**kwargs)
        return report,v.read_json(report['manifest'])
    def responses(self,m,status='accepted'):
        return {'packet_id':m['packet_id'],'reviews':[{'image_id':e['image_id'],'status':status,'description':'Visible cupboard with shelves','tags':['shelf','étagère'],'confidence':.8,'model':'test-fixture-NOT-real-vision','limitations':'Only front visible'} for e in m['entries']]}
    def test_prepare_and_cache(self):
        a,m=self.prep();b,n=self.prep();self.assertEqual(a['ready'],2);self.assertEqual(b['cached'],2);self.assertEqual(m,n)
    def test_small_native_view_enlarges_without_changing_source(self):
        source=self.root/'native.png';Image.new('RGBA',(8,8),(255,0,0,255)).save(source);before=source.read_bytes()
        report=v.prepare(self.db,['gta5:model:1'],self.root/'native-packet',overrides={'gta5:model:1':[str(source)]})
        manifest=v.read_json(report['manifest']);e=manifest['entries'][0]
        with Image.open(e['image_path']) as image:
            self.assertEqual(image.getpixel((10,10)),(255,0,0));self.assertEqual(image.size,(512,512))
        self.assertEqual(source.read_bytes(),before);self.assertEqual(e['views'][0]['sha256'],v.sha(before))
    def test_pixel_properties_distinguish_alpha_from_white_material(self):
        image=Image.new('RGBA',(2,2),(255,255,255,0));image.putpixel((0,0),(255,255,255,128));image.putpixel((1,1),(255,255,255,255))
        buf=io.BytesIO();image.save(buf,format='PNG');props=v.pixel_properties(buf.getvalue())
        self.assertEqual(props['width'],2);self.assertEqual(props['fully_transparent_pixels'],2);self.assertEqual(props['partially_transparent_pixels'],1);self.assertEqual(props['opaque_pixels'],1)
    def test_packet_blind(self):
        a,m=self.prep();p=v.read_json(a['packet']);text=json.dumps(p)
        self.assertNotIn('opaque',text);self.assertNotIn('gta5:model',text);self.assertNotIn('source',p['images'][0]);self.assertNotIn('asset_hash',text)
    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):v.prepare(self.db,['gta5:model:1']*2,self.root)
    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):v.prepare(self.db,['gta5:model:404'],self.root)
    def test_worker_bound(self):
        with self.assertRaises(ValueError):self.prep(workers=50)
    def test_failed_fetch_resumes(self):
        def failure(url):raise OSError('offline')
        a=v.prepare(self.db,['gta5:model:1'],self.root/'packets',fetcher=failure)
        self.assertEqual(len(a['failed']),1);b,m=self.prep();self.assertEqual(b['ready'],2)
    def test_html_rejected(self):
        a=v.prepare(self.db,['gta5:model:1'],self.root/'packets',fetcher=lambda u:b'<html>oops</html>');self.assertEqual(a['ready'],0)
    def test_truncated_png_rejected(self):self.assertFalse(v.image_ok(b'\x89PNG\r\n\x1a\n'))
    def test_cache_corruption_reported(self):
        a,m=self.prep();Path(m['entries'][0]['image_path']).write_bytes(b'corrupt');b,n=self.prep();self.assertEqual(b['ready'],0)
        b,n=self.prep(refresh=True);self.assertEqual(b['ready'],2)
    def test_import_and_resume(self):
        a,m=self.prep();r=self.responses(m);self.assertEqual(v.import_reviews(self.db,m,r)['accepted'],2)
        self.assertEqual(v.import_reviews(self.db,m,r)['unchanged'],2);self.assertEqual(len(c.search(self.db,'étagère')),2)
    def test_changed_image_rejected(self):
        a,m=self.prep();Path(m['entries'][0]['image_path']).write_bytes(png('blue'))
        with self.assertRaisesRegex(ValueError,'evidence changed'):v.import_reviews(self.db,m,self.responses(m))
    def test_changed_metadata_rejected(self):
        a,m=self.prep();self.db.execute("UPDATE assets SET hash='changed' WHERE key='gta5:model:1'")
        with self.assertRaisesRegex(ValueError,'Stale'):v.import_reviews(self.db,m,self.responses(m))
    def test_manifest_tamper_rejected(self):
        a,m=self.prep();m['entries'][0]['source']='https://fake.invalid'
        with self.assertRaisesRegex(ValueError,'content hash'):v.import_reviews(self.db,m,self.responses(m))
    def test_packet_id_mismatch(self):
        a,m=self.prep();r=self.responses(m);r['packet_id']='fake'
        with self.assertRaises(ValueError):v.import_reviews(self.db,m,r)
    def test_unknown_image_id(self):
        a,m=self.prep();r=self.responses(m);r['reviews'][0]['image_id']='fake'
        with self.assertRaises(ValueError):v.import_reviews(self.db,m,r)
    def test_duplicate_review_rejected(self):
        a,m=self.prep();r=self.responses(m);r['reviews'].append(r['reviews'][0])
        with self.assertRaises(ValueError):v.import_reviews(self.db,m,r)
    def test_invalid_confidences(self):
        a,m=self.prep()
        for x in (True,None,float('nan'),float('inf'),-.1,1.1):
            r=self.responses(m);r['reviews'][0]['confidence']=x
            with self.subTest(x=x),self.assertRaises(ValueError):v.import_reviews(self.db,m,r)
    def test_low_confidence_not_accepted(self):
        a,m=self.prep();r=self.responses(m);r['reviews'][0]['confidence']=.3
        with self.assertRaises(ValueError):v.import_reviews(self.db,m,r)
    def test_missing_evidence_fields(self):
        a,m=self.prep()
        for k in ('description','model','limitations','tags','status'):
            r=self.responses(m);del r['reviews'][0][k]
            with self.subTest(k=k),self.assertRaises(ValueError):v.import_reviews(self.db,m,r)
    def test_batch_validation_atomic(self):
        a,m=self.prep();r=self.responses(m);r['reviews'][1]['confidence']=99
        with self.assertRaises(ValueError):v.import_reviews(self.db,m,r)
        self.assertEqual(self.db.execute('SELECT count(*) FROM annotations').fetchone()[0],0)
    def test_ambiguous_kept_outside_index(self):
        a,m=self.prep();self.assertEqual(v.import_reviews(self.db,m,self.responses(m,'ambiguous'))['ambiguous'],2)
        self.assertEqual(c.search(self.db,'étagère'),[]);self.assertEqual(self.db.execute('SELECT count(*) FROM visual_reviews').fetchone()[0],2)
    def test_new_ambiguous_quarantines_old_annotation(self):
        a,m=self.prep();v.import_reviews(self.db,m,self.responses(m))
        a=v.prepare(self.db,['gta5:model:1','gta5:model:2'],self.root/'packets',refresh=True,fetcher=lambda u:png('blue'));n=v.read_json(a['manifest'])
        v.import_reviews(self.db,n,self.responses(n,'ambiguous'));self.assertEqual(c.search(self.db,'étagère'),[])
    def test_changed_review_cannot_rewrite_audit(self):
        a,m=self.prep();r=self.responses(m);v.import_reviews(self.db,m,r);r['reviews'][0]['description']='rewritten'
        with self.assertRaises(ValueError):v.import_reviews(self.db,m,r)
    def test_local_multiview_and_original_hash(self):
        paths=[]
        for i in range(4):p=self.root/f'view{i}.png';p.write_bytes(png());paths.append(str(p))
        a,m=self.prep(overrides={'gta5:model:1':paths});self.assertEqual(len(m['entries'][0]['views']),4)
        v.import_reviews(self.db,m,self.responses(m));Path(paths[0]).write_bytes(png('blue'))
        with self.assertRaisesRegex(ValueError,'Original view'):v.import_reviews(self.db,m,self.responses(m))
    def test_override_unknown_key(self):
        with self.assertRaises(ValueError):self.prep(overrides={'gta5:model:88':[]})
    def test_sheets(self):
        a,m=self.prep();r=v.sheets(m,self.root/'sheets');self.assertEqual(len(r['sheets']),1)
        self.assertTrue(Path(r['sheets'][0]['path']).exists())
    def test_texture_preview_collision_fails(self):
        for source in ('a.img','b.img'):
            p={'record':{'txd':'shared','name':'thing','source':source},'hints':[]}
            self.db.execute('INSERT INTO assets VALUES (?,?,?,?,?,?)',(source,'gta5','texture','thing',c.digest(p),c.canonical(p)))
        a=v.prepare(self.db,['a.img'],self.root/'packets',fetcher=lambda u:png());self.assertEqual(a['ready'],0);self.assertIn('collides',a['failed'][0]['error'])
if __name__=='__main__':unittest.main()
