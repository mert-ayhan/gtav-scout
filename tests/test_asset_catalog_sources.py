import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import asset_catalog_sources as sources


class ToolCommand(unittest.TestCase):
    def setUp(self):
        # tool_command falls back to CODEWALKER_PATH, so these must not depend on
        # whether the developer happens to have it exported.
        patch = mock.patch.dict(os.environ, {}, clear=False)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop('CODEWALKER_PATH', None)

    def test_asset_root_selects_the_directory_source(self):
        argv = sources.tool_command(out='/out/snap', asset_root='/assets',
                                    codewalker_path='/cw', dotnet='dotnet')
        self.assertEqual(argv[0], 'dotnet')
        self.assertIn('inventory', argv)
        self.assertIn('--asset-root', argv)
        self.assertIn('/assets', argv)
        self.assertNotIn('--game-root', argv)
        self.assertIn('/out/snap', argv)

    def test_game_root_selects_the_rpf_source(self):
        argv = sources.tool_command(out='/out/snap', game_root='/games/GTAV',
                                    codewalker_path='/cw')
        self.assertIn('--game-root', argv)
        self.assertIn('/games/GTAV', argv)
        self.assertNotIn('--asset-root', argv)

    def test_exactly_one_source_is_required(self):
        with self.assertRaises(ValueError):
            sources.tool_command(out='/out/snap', codewalker_path='/cw')
        with self.assertRaises(ValueError):
            sources.tool_command(out='/out/snap', asset_root='/a',
                                 game_root='/g', codewalker_path='/cw')

    def test_missing_codewalker_path_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            sources.tool_command(out='/out/snap', asset_root='/assets',
                                 codewalker_path=None)
        self.assertIn('CODEWALKER_PATH', str(caught.exception))


class ValidateSnapshot(unittest.TestCase):
    ALL = ('models/data/models.json', 'models/data/model-sizes.json',
           'models/data/locations.json', 'textures/data/textures.json')

    def snapshot(self, report, files=ALL):
        root = Path(tempfile.mkdtemp())
        for name in files:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{}')
        (root / 'source-report.json').write_text(json.dumps(report))
        return root

    def report(self, **overrides):
        base = {'adapter': 'gta5-legacy-v1', 'models': 12, 'textures': 34,
                'placedArchetypes': 5, 'failures': []}
        base.update(overrides)
        return base

    def test_complete_snapshot_returns_the_report(self):
        report = self.report()
        self.assertEqual(sources.validate_snapshot(self.snapshot(report)), report)

    def test_empty_model_snapshot_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            sources.validate_snapshot(self.snapshot(self.report(models=0)))
        self.assertIn('no models', str(caught.exception))

    def test_empty_texture_snapshot_is_rejected(self):
        with self.assertRaises(ValueError):
            sources.validate_snapshot(self.snapshot(self.report(textures=0)))

    def test_missing_file_is_rejected(self):
        present = tuple(n for n in self.ALL if n != 'textures/data/textures.json')
        with self.assertRaises(ValueError) as caught:
            sources.validate_snapshot(self.snapshot(self.report(), files=present))
        self.assertIn('textures/data/textures.json', str(caught.exception))

    def test_wrong_adapter_is_rejected(self):
        with self.assertRaises(ValueError):
            sources.validate_snapshot(self.snapshot(self.report(adapter='classic-pc-sa-v1')))

    def test_missing_report_is_rejected(self):
        root = Path(tempfile.mkdtemp())
        with self.assertRaises(ValueError):
            sources.validate_snapshot(root)


if __name__ == '__main__':
    unittest.main()
