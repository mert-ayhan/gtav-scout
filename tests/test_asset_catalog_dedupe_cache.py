import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import asset_catalog_dedupe_cache as d
class DedupeTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
  self.a=self.root/'a/sources/hash/a.ydr';self.b=self.root/'b/sources/hash/b.ydr'
  for p in (self.a,self.b):p.parent.mkdir(parents=True);p.write_bytes(b'synthetic DFF test bytes')
 def test_plan_apply_and_repeat_preserve_paths(self):
  self.assertEqual(d.dedupe(self.root)['duplicatePaths'],1);self.assertNotEqual(self.a.stat().st_ino,self.b.stat().st_ino)
  self.assertEqual(d.dedupe(self.root,True)['duplicatePaths'],1);self.assertEqual(self.a.stat().st_ino,self.b.stat().st_ino);self.assertEqual(self.b.read_bytes(),b'synthetic DFF test bytes');self.assertEqual(d.dedupe(self.root,True)['duplicatePaths'],0)
 def test_outside_sources_and_symlinks_excluded(self):
  p=self.root/'user.ydr';p.write_bytes(self.a.read_bytes());self.b.unlink()
  # Windows refuses symlink creation without Developer Mode or admin rights.
  try:self.b.symlink_to(p)
  except OSError as error:raise unittest.SkipTest('Cannot create symlinks here: %s'%error) from error
  self.assertEqual(d.dedupe(self.root,True)['duplicatePaths'],0);self.assertTrue(self.b.is_symlink());self.assertNotEqual(p.stat().st_ino,self.a.stat().st_ino)
 def test_different_bytes_never_linked(self):
  self.b.write_bytes(b'different bytes');self.assertEqual(d.dedupe(self.root,True)['duplicatePaths'],0)
if __name__=='__main__':unittest.main()
