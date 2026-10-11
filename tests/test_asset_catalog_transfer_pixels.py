import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import asset_catalog as c
import asset_catalog_transfer_pixels as t


class PixelTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=c.connect(self.root/'db.sqlite');self.addCleanup(self.db.close)
        self.image=self.root/'image.png';Image.new('RGBA',(8,8),'red').save(self.image)
        self.source=self.root/'fixture.txd';self.source.write_bytes(b'explicit synthetic source fixture')
        source={'path':str(self.source),'offset':0,'bytes':self.source.stat().st_size,'sha256':hashlib.sha256(self.source.read_bytes()).hexdigest()}
        self.rows=[]
        for i in range(3):
            key=f'gta5:texture:fixture{i}'
            payload={'record':{'name':'fixture','txd':f'fixture{i}','source':'fixture.img','width':8,'height':8},'hints':[]}
            digest=c.digest(payload)
            self.db.execute('INSERT INTO assets VALUES (?,?,?,?,?,?)',(key,'gta5','texture','fixture',digest,c.canonical(payload)))
            c.searchable(self.db,key,'fixture',payload,digest)
            self.rows.append({'key':key,'name':'fixture','txd':f'fixture{i}','archive':'fixture.img','expected':{'width':8,'height':8},'status':'resolved','pixelSha256':t.pixel_hash(self.image),'sources':[{'source':source,'matches':[{'pixelSha256':t.pixel_hash(self.image)}]}]})
        evidence={'image_path':str(self.image),'image_sha256':hashlib.sha256(self.image.read_bytes()).hexdigest()}
        asset=self.db.execute('SELECT * FROM assets ORDER BY key LIMIT 1').fetchone()
        self.db.execute('INSERT INTO annotations VALUES (?,?,?,?,?,?,?,?)',(asset['key'],asset['hash'],'Synthetic red fixture only','["synthetic"]','model-visual','test-fixture',.9,c.canonical(evidence)))
        self.db.commit();self.audit=self.root/'audit.json';self.write()
    def write(self):self.audit.write_text(json.dumps(self.rows))
    def count(self):return self.db.execute('SELECT COUNT(*) FROM annotations').fetchone()[0]
    def test_dry_run_never_writes_and_repeat_is_noop(self):
        self.assertEqual(t.transfer(self.db,self.audit)['eligible_transfers'],2);self.assertEqual(self.count(),1)
        report=t.transfer(self.db,self.audit,True)
        self.assertEqual(report['new_vision_inspections'],0);self.assertEqual(self.count(),3)
        self.assertEqual(t.transfer(self.db,self.audit,True)['eligible_transfers'],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM visual_pixel_transfers').fetchone()[0],2)
    def test_changed_source_rejected_before_any_annotation_write(self):
        self.source.write_bytes(b'corrupted')
        with self.assertRaises(ValueError):t.transfer(self.db,self.audit,True)
        self.assertEqual(self.count(),1)
    def test_changed_parent_image_rejected(self):
        Image.new('RGBA',(8,8),'blue').save(self.image)
        with self.assertRaises(ValueError):t.transfer(self.db,self.audit,True)
        self.assertEqual(self.count(),1)
    def test_wrong_occurrence_cannot_borrow_matching_name(self):
        self.rows[-1]['archive']='other.img';self.write()
        with self.assertRaises(ValueError):t.transfer(self.db,self.audit,True)
        self.assertEqual(self.count(),1)
    def test_nonmatching_pixels_do_not_transfer(self):
        for row in self.rows:row['pixelSha256']='not-the-observed-image'
        self.write();self.assertEqual(t.transfer(self.db,self.audit,True)['eligible_transfers'],0)
        self.assertEqual(self.count(),1)
    def test_native_view_identity_survives_review_montage(self):
        montage=self.root/'montage.png';Image.new('RGBA',(512,512),'red').save(montage)
        evidence={'image_path':str(montage),'image_sha256':hashlib.sha256(montage.read_bytes()).hexdigest(),'views':[{'path':str(self.image),'sha256':hashlib.sha256(self.image.read_bytes()).hexdigest()}]}
        self.db.execute('UPDATE annotations SET evidence=?',(c.canonical(evidence),));self.db.commit()
        self.assertEqual(t.transfer(self.db,self.audit,True)['eligible_transfers'],2)
    def test_parent_revision_or_deletion_invalidates_transfer(self):
        import asset_catalog_semantic as semantic
        t.transfer(self.db,self.audit,True)
        self.assertEqual(len(semantic.documents(self.db)),3)
        self.db.execute("UPDATE annotations SET description='revised synthetic observation' WHERE key='gta5:texture:fixture0'");self.db.commit()
        self.assertEqual(len(semantic.documents(self.db)),1)
        self.assertFalse(c.search(self.db,'synthetic'))
        self.db.execute("DELETE FROM annotations WHERE key='gta5:texture:fixture0'");self.db.commit()
        self.assertEqual(len(semantic.documents(self.db)),0)
    def test_parent_evidence_change_invalidates_transfer(self):
        import asset_catalog_semantic as semantic
        t.transfer(self.db,self.audit,True)
        self.image.write_bytes(b'changed evidence')
        self.assertEqual(len(semantic.documents(self.db)),0)
    def concurrent_change(self,sql):
        original=t.verify_source;changed=False
        def hook(source,cache):
            nonlocal changed
            original(source,cache)
            if not changed:
                changed=True
                other=c.connect(self.root/'db.sqlite')
                try:other.execute(sql);other.commit()
                finally:other.close()
        with patch.object(t,'verify_source',hook):
            with self.assertRaises(ValueError):t.transfer(self.db,self.audit,True)
        self.assertEqual(self.count(),1)
    def test_concurrent_parent_revision_is_rejected_under_write_lock(self):
        self.concurrent_change("UPDATE annotations SET description='changed concurrently' WHERE key='gta5:texture:fixture0'")
    def test_concurrent_target_metadata_change_rejected(self):
        self.concurrent_change("UPDATE assets SET hash='changed concurrently' WHERE key='gta5:texture:fixture1'")
    def test_pixel_diversification_retains_exact_occurrences(self):
        import asset_catalog_semantic as semantic
        t.transfer(self.db,self.audit,True)
        ranked=[{'key':f'gta5:texture:fixture{i}','kind':'texture'} for i in range(3)]
        grouped=semantic.diversify_texture_pixels(self.db,ranked)
        self.assertEqual(len(grouped),1);self.assertEqual(len(grouped[0]['equivalent_pixel_occurrences']),3)
        self.assertEqual(grouped[0]['key'],ranked[0]['key'])
        self.assertEqual(semantic.diversify_texture_pixels(self.db,grouped),grouped)
        self.db.execute("UPDATE annotations SET description='parent revision' WHERE key='gta5:texture:fixture0'");self.db.commit()
        self.assertEqual(len(semantic.diversify_texture_pixels(self.db,ranked)),3)
    def test_explicit_refresh_preserves_old_history(self):
        t.transfer(self.db,self.audit,True)
        self.db.execute("UPDATE annotations SET description='revised appearance' WHERE key='gta5:texture:fixture0'");self.db.commit()
        report=t.transfer(self.db,self.audit,True,refresh_stale=True)
        self.assertEqual(report['refreshed_stale_transfers'],2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM visual_pixel_transfers').fetchone()[0],4)
        self.assertEqual(self.db.execute("SELECT description FROM annotations WHERE key='gta5:texture:fixture1'").fetchone()[0],'revised appearance')
    def test_independent_visual_reviews_group_without_any_transfers(self):
        import asset_catalog_semantic as semantic
        parent=dict(self.db.execute("SELECT * FROM annotations WHERE key='gta5:texture:fixture0'").fetchone())
        for i in (1,2):
            asset=self.db.execute('SELECT * FROM assets WHERE key=?',(f'gta5:texture:fixture{i}',)).fetchone()
            self.db.execute('INSERT INTO annotations VALUES (?,?,?,?,?,?,?,?)',(asset['key'],asset['hash'],'Another actual-review fixture','["synthetic"]','model-visual','test-fixture',.9,parent['evidence']))
        self.db.commit();report=t.transfer(self.db,self.audit,True)
        self.assertEqual(report['eligible_transfers'],0);self.assertEqual(report['verified_direct_pixel_observations'],3)
        ranked=[{'key':f'gta5:texture:fixture{i}','kind':'texture'} for i in range(3)]
        self.assertEqual(len(semantic.diversify_texture_pixels(self.db,ranked)),1)


if __name__=='__main__':unittest.main()
