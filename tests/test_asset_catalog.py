"""End-to-end acceptance tests for incremental catalog and evidence handling."""
import importlib.util, json, os, tempfile, unittest, hashlib
from PIL import Image
from pathlib import Path
spec=importlib.util.spec_from_file_location('asset_catalog',Path(__file__).parents[1]/'scripts/asset_catalog.py'); c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

class CatalogTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=c.connect(self.root/'db.sqlite')
  self.models=[{'id':1,'name':'officedesk1','txd':'office','category':'buildings','tags':[]},{'id':2,'name':'washer','txd':'bath','tags':[]},{'id':3,'name':'compound_gate','txd':'metal','tags':[]},{'id':4,'name':'obscure_xyz','txd':'misc','tags':[]}]
  self.textures=[{'name':'wall','txd':'a','source':'one.img'},{'name':'wall','txd':'b','source':'one.img'}]
  self.write()
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def put(self,path,data):
  path=self.root/path;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data))
 def write(self):
  self.put('models/data/models.json',{'models':self.models});self.put('textures/data/textures.json',{'textures':self.textures})
  self.put('models/data/model-sizes.json',{'1':{'width':1.2},'2':{'width':2.5}})
  self.put('models/data/locations.json',{'locations':{'1':{'ipls':['police.ipl'],'locs':[{'x':1,'y':2,'z':3,'i':0}]}}})
 def build(self):return c.build(self.db,self.root)
 def annotation(self,key='gta5:model:4'):
  h=self.db.execute('SELECT hash FROM assets WHERE key=?',(key,)).fetchone()[0]
  image=self.root/'fixture.png';Image.new('RGB',(4,4),'red').save(image)
  return {'key':key,'asset_hash':h,'description':'Chaise de bureau pivotante','tags':['chaise','bureau'],'method':'human-visual','model':'test-reviewer','confidence':.9,'evidence':{'preview':str(image),'sha256':hashlib.sha256(image.read_bytes()).hexdigest()}}
 def annotate(self,a):self.put('a.json',[a]);return c.annotate(self.db,self.root/'a.json')
 def test_initial_counts_and_cached_rebuild(self):
  self.assertEqual(self.build()['inserted'],6);r=self.build();self.assertEqual(r['unchanged'],6);self.assertEqual(r['updated'],0)
 def test_single_change_invalidates_one(self):
  self.build();self.models[0]['name']='officedesk2';self.write();self.assertEqual(self.build()['updated'],1)
 def test_metadata_dependency_change(self):
  self.build();self.put('models/data/model-sizes.json',{'1':{'width':3},'2':{'width':2.5}});self.assertEqual(self.build()['updated'],1)
 def test_removed_record_removed_from_search(self):
  self.build();self.models.pop(0);self.write();self.assertEqual(self.build()['deleted'],1);self.assertEqual(c.search(self.db,'desk'),[])
 def test_namespaces_dont_collide_or_delete_other_game(self):
  self.build();c.build(self.db,self.root,'other');self.assertEqual(self.db.execute('SELECT count(*) FROM assets').fetchone()[0],12)
  self.models=[];self.write();self.build();self.assertEqual(len(c.search(self.db,'desk',game='other')),1)
 def test_same_texture_name_not_deduplicated(self):
  self.build();self.assertEqual(len(c.search(self.db,'wall',kind='texture')),2)
 def test_french_synonyms_accents(self):
  self.build();self.assertEqual(c.search(self.db,'bureaux')[0]['key'],'gta5:model:1')
 def test_substring_false_positives(self):
  self.build();self.assertEqual(c.search(self.db,'sheriff'),[]);self.assertEqual(c.search(self.db,'ordinateur'),[])
 def test_search_filter_unknown_size_excluded(self):
  self.build();self.assertEqual(len(c.search(self.db,'bureau',max_width=1.5)),1);self.assertEqual(c.search(self.db,'bureau',max_width=.5),[])
 def test_punctuation_query_safe(self):
  self.build();self.assertEqual(c.search(self.db,'" OR * ; --'),[])
 def test_visual_annotation_discovers_opaque_name(self):
  self.build();self.assertEqual(c.search(self.db,'chaise'),[]);self.annotate(self.annotation());self.assertEqual(c.search(self.db,'chaise')[0]['key'],'gta5:model:4')
 def test_stale_annotations_excluded(self):
  self.build();a=self.annotation();self.annotate(a);self.models[3]['name']='changed';self.write();self.build();self.assertEqual(c.search(self.db,'chaise'),[])
  with self.assertRaisesRegex(ValueError,'Stale'):self.annotate(a)
 def test_invalid_annotation_rolls_back(self):
  self.build();a=self.annotation();b=self.annotation('gta5:model:1');b['confidence']=float('nan');self.put('a.json',[a,b])
  with self.assertRaises(ValueError):c.annotate(self.db,self.root/'a.json')
  self.assertEqual(c.search(self.db,'chaise'),[])
 def test_annotation_requires_evidence(self):
  self.build();a=self.annotation();del a['evidence']
  with self.assertRaises(ValueError):self.annotate(a)
 def test_jobs_resume_excludes_completed(self):
  self.build();self.annotate(self.annotation());self.assertEqual(len(c.jobs(self.db,100)),5)
 def test_malformed_source_atomic(self):
  self.build();self.models[0]['name']='edited';self.models.append({'id':99});self.write()
  with self.assertRaises(ValueError):self.build()
  self.assertEqual(c.search(self.db,'desk')[0]['name'],'officedesk1')
 def test_missing_required_source_atomic(self):
  self.build();(self.root/'textures/data/textures.json').unlink()
  with self.assertRaises(ValueError):self.build()
  self.assertEqual(self.db.execute('SELECT count(*) FROM assets').fetchone()[0],6)
 def test_optional_metadata_missing(self):
  (self.root/'models/data/model-sizes.json').unlink();(self.root/'models/data/locations.json').unlink();self.assertEqual(self.build()['inserted'],6)
 def test_content_dedup_different_names_and_cache(self):
  r=self.root/'assets';r.mkdir();(r/'a.ydr').write_bytes(b'abc');(r/'b.ydr').write_bytes(b'abc');(r/'c.ydr').write_bytes(b'abd')
  stats=c.scan(self.db,r);self.assertEqual(stats['hashed'],3);self.assertEqual(stats['duplicateGroups'],1);self.assertEqual(c.scan(self.db,r)['cached'],3)
 def test_binary_invalidation_and_deleted(self):
  r=self.root/'assets';r.mkdir();f=r/'a.ytd';f.write_bytes(b'abc');c.scan(self.db,r);f.write_bytes(b'longer');self.assertEqual(c.scan(self.db,r)['hashed'],1);f.unlink();self.assertEqual(c.scan(self.db,r)['deleted'],1)
 def test_verify_detects_preserved_mtime_change(self):
  r=self.root/'assets';r.mkdir();f=r/'a.png';f.write_bytes(b'abc');c.scan(self.db,r);s=f.stat();old=self.db.execute('SELECT sha256 FROM files').fetchone()[0];f.write_bytes(b'xyz');os.utime(f,ns=(s.st_atime_ns,s.st_mtime_ns));c.scan(self.db,r,True);self.assertNotEqual(self.db.execute('SELECT sha256 FROM files').fetchone()[0],old)
 def test_scan_cleanup_does_not_touch_sibling_prefix(self):
  a=self.root/'a';ab=self.root/'ab';a.mkdir();ab.mkdir();(ab/'x.ybn').write_bytes(b'123');c.scan(self.db,ab);c.scan(self.db,a);self.assertEqual(self.db.execute('SELECT count(*) FROM files').fetchone()[0],1)


 def test_conflicting_duplicate_rejected(self):
  self.build();self.models.append(dict(self.models[0],name='other')) ;self.write()
  with self.assertRaisesRegex(ValueError,'Conflicting'):self.build()
  self.assertEqual(c.search(self.db,'desk')[0]['name'],'officedesk1')
 def test_identical_metadata_identity_collapsed(self):
  self.models.append(dict(self.models[0]));self.write();self.assertEqual(self.build()['inserted'],6)
 def test_partial_query_coverage_is_explicit(self):
  self.build();r=c.search(self.db,'bureau licorne')[0];self.assertEqual(r['matchedTerms'],['bureau']);self.assertEqual(r['queryCoverage'],.5)
 def test_pc_underscore_rule(self):
  self.models[3]['name']='PC_1';self.write();self.build();self.assertEqual(c.search(self.db,'ordinateur')[0]['key'],'gta5:model:4')
 def test_invalid_limit(self):
  self.build()
  with self.assertRaises(ValueError):c.search(self.db,'bureau',limit=-1)
 def test_scan_missing_root_fails(self):
  with self.assertRaises(ValueError):c.scan(self.db,self.root/'missing')

 def test_reordered_sources_noop(self):
  self.build();self.models.reverse();self.textures.reverse();self.write();self.assertEqual(self.build()['unchanged'],6)
 def test_invalid_jobs_limit(self):
  self.build()
  with self.assertRaises(ValueError):c.jobs(self.db,-1)

 def test_real_compound_names_not_computers(self):
  self.models=[dict(self.models[0],id=i,name=n) for i,n in enumerate(['NEWCOMP2_las2','imcomp1trk','LODCOMP2'])];self.write();self.build();self.assertEqual(c.search(self.db,'ordinateur'),[])
 def test_wc_in_asset_name_not_translated_to_toilet(self):
  self.models[3]['name']='wc_lift_SFSe';self.write();self.build();self.assertEqual(c.search(self.db,'toilettes'),[])

 def test_low_confidence_requeued_first(self):
  self.build();a=self.annotation();a['confidence']=.2;self.annotate(a);r=c.jobs(self.db,1);self.assertEqual(r[0]['key'],'gta5:model:4');self.assertEqual(r[0]['reason'],'low-confidence')
 def test_jobs_threshold_validation(self):
  self.build()
  with self.assertRaises(ValueError):c.jobs(self.db,10,float('nan'))

if __name__=='__main__'   :unittest.main(verbosity=2)
