"""End-to-end pipeline over a synthetic gta5 catalogue and synthetic evidence.

Proves the stages downstream of extraction — review packets, shortlists and the
semantic index — operate on the gta5 namespace, without needing GTA V, Blender or
a vision model.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import asset_catalog


def png(path, colour):
    from PIL import Image
    Image.new('RGBA', (16, 16), colour).save(path)
    return path


class Gta5Pipeline(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / 'models/data').mkdir(parents=True)
        (self.root / 'textures/data').mkdir(parents=True)
        (self.root / 'models/data/models.json').write_text(json.dumps({'models': [
            {'id': 'prop_bench_01a', 'name': 'prop_bench_01a', 'dff': 'prop_bench_01a',
             'txd': 'prop_bench_01a', 'source': 'x64a.rpf/v_bench.ytyp', 'tags': []},
            {'id': 'prop_chair_01a', 'name': 'prop_chair_01a', 'dff': 'prop_chair_01a',
             'txd': 'prop_chair_01a', 'source': 'x64a.rpf/v_chair.ytyp', 'tags': []}]}))
        (self.root / 'textures/data/textures.json').write_text(json.dumps({'textures': [
            {'name': 'bench_wood', 'txd': 'prop_bench_01a', 'source': 'x64a.rpf/b.ytd'}]}))
        self.db_path = self.root / 'catalog.sqlite'
        db = asset_catalog.connect(self.db_path)
        asset_catalog.build(db, self.root, game='gta5')
        db.commit()
        db.close()

    def run_module(self, module, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / module), *args],
            capture_output=True, text=True)

    def test_visual_prepare_accepts_gta5_overrides(self):
        image = png(self.root / 'front.png', (140, 90, 40, 255))
        keys = self.root / 'keys.json'
        keys.write_text(json.dumps(['gta5:model:prop_bench_01a']))
        overrides = self.root / 'overrides.json'
        overrides.write_text(json.dumps({'gta5:model:prop_bench_01a': [str(image)]}))

        result = self.run_module(
            'asset_catalog_visual.py', '--db', str(self.db_path), 'prepare',
            '--keys', str(keys), '--overrides', str(overrides),
            '--out', str(self.root / 'packets'))
        self.assertEqual(result.returncode, 0, result.stderr)

        # prepare writes each packet under its own content-addressed directory and
        # records the paths in latest.json; nothing is written at a fixed name.
        latest = json.loads((self.root / 'packets' / 'latest.json').read_text())
        self.assertEqual(latest['ready'], 1)
        self.assertEqual(latest['failed'], [])
        manifest = Path(latest['manifest'])
        packet = Path(latest['packet'])
        self.assertTrue(manifest.is_file())
        self.assertTrue(packet.is_file())

        # The packet is what a reviewer sees; it must not leak the asset identity,
        # or the review stops being blind.
        self.assertNotIn('gta5:model', packet.read_text())
        self.assertIn('gta5:model:prop_bench_01a', manifest.read_text())

    def test_shortlist_runs_over_gta5(self):
        # Shortlisting loads the semantic encoder, which is an optional extra.
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("install .[semantic] to exercise shortlisting")
        # --out is a directory: prepare fills it with latest.json and a
        # content-addressed query-packet.json, the same shape visual prepare uses.
        out = self.root / 'shortlist'
        result = self.run_module(
            'asset_catalog_shortlist.py', '--db', str(self.db_path), 'prepare',
            '--query', 'bench', '--game', 'gta5', '--out', str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        latest = out / 'latest.json'
        self.assertTrue(latest.is_file())
        report = json.loads(latest.read_text())
        self.assertIn('query_packet_id', report)
        packets = list(out.glob('*/query-packet.json'))
        self.assertEqual(len(packets), 1, packets)

    def test_batch_planner_accepts_gta5(self):
        # --out is a directory the planner fills with keys.json and plan.json.
        out = self.root / 'batch'
        result = self.run_module(
            'plan-asset-catalog-batch.py', '--db', str(self.db_path),
            '--game', 'gta5', '--limit', '5', '--out', str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((out / 'keys.json').is_file())
        self.assertTrue((out / 'plan.json').is_file())
        keys = json.loads((out / 'keys.json').read_text())
        self.assertTrue(all(k.startswith('gta5:') for k in keys), keys)

    def test_search_filters_by_game(self):
        db = asset_catalog.connect(self.db_path)
        self.assertTrue(asset_catalog.search(db, 'bench', game='gta5'))
        self.assertFalse(asset_catalog.search(db, 'bench', game='other'))


if __name__ == '__main__':
    unittest.main()
