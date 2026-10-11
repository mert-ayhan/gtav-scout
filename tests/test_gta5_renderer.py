"""Renderer checks that do not need GTA V.

The Sollumz import is the only part of the renderer these cannot reach; everything
around it — the four-view camera rig, blank-render detection, degenerate-bounds
rejection and the batch bookkeeping — is exercised here. Blender-dependent checks
skip when Blender is not configured.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RENDERER = ROOT / 'scripts' / 'render-asset-catalog-views.py'


def find_blender():
    """BLENDER_PATH wins; otherwise fall back to a blender on PATH."""
    configured = os.environ.get('BLENDER_PATH')
    if configured and Path(configured).is_file():
        return configured
    return shutil.which('blender')


class RendererSource(unittest.TestCase):
    """Checks that need neither Blender nor the game."""

    def test_renderer_exists_and_declares_the_rig(self):
        self.assertTrue(RENDERER.is_file(), 'scripts/render-asset-catalog-views.py is missing')
        source = RENDERER.read_text()
        self.assertIn('AZIMUTHS = [45, 135, 225, 315]', source)
        self.assertIn('ELEVATION = 25', source)
        self.assertIn('sollumz.import_assets', source)

    def test_batch_shape_matches_the_extractor(self):
        root = Path(tempfile.mkdtemp())
        (root / 'a.ydr').write_bytes(b'not-a-real-drawable')
        (root / 'wood.png').write_bytes(b'not-a-real-png')
        payload = {'assets': [{
            'id': 'gta5:model:prop_bench_01a',
            'model': 'prop_bench_01a',
            'drawable': str(root / 'a.ydr'),
            'textures': {'wood': str(root / 'wood.png')},
            'sourceFiles': [str(root / 'a.ydr')],
            'sources': [{'path': 'x64a.rpf/a.ydr', 'entry': 'a.ydr',
                         'bytes': 19, 'sha256': '0' * 64}],
        }], 'failures': [], 'decodeRecipe': {'output': 'PNG RGBA native resolution'}}
        (root / 'input.json').write_text(json.dumps(payload))

        asset = json.loads((root / 'input.json').read_text())['assets'][0]
        for field in ('id', 'model', 'drawable', 'textures', 'sourceFiles', 'sources'):
            self.assertIn(field, asset)
        self.assertTrue(Path(asset['drawable']).is_file())
        self.assertTrue(all(Path(p).is_file() for p in asset['textures'].values()))


class RenderRig(unittest.TestCase):
    """Drives the real camera rig inside Blender on synthetic geometry."""

    def test_rig_renders_four_views_and_detects_blanks(self):
        blender = find_blender()
        if not blender:
            raise unittest.SkipTest('Blender not found; set BLENDER_PATH')
        out = Path(tempfile.mkdtemp())
        completed = subprocess.run(
            [blender, '-b', '--python', str(ROOT / 'tests' / 'blender_render_rig_check.py'),
             '--', '--output', str(out)],
            capture_output=True, text=True)
        result = out / 'result.json'
        self.assertTrue(result.is_file(),
                        'rig check produced no result:\n' + completed.stdout[-2000:]
                        + '\n' + completed.stderr[-2000:])
        self.assertEqual(json.loads(result.read_text())['failures'], [])


if __name__ == '__main__':
    unittest.main()
