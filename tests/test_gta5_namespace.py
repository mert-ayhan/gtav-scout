import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import asset_catalog_visual


def row(game, kind, record):
    return {'game': game, 'kind': kind, 'payload': json.dumps({'record': record})}


class Gta5Namespace(unittest.TestCase):
    def setUp(self):
        os.environ['ASSET_PREVIEW_BASE_URL'] = 'https://example.invalid/previews'
        self.addCleanup(os.environ.pop, 'ASSET_PREVIEW_BASE_URL', None)

    def test_gta5_model_preview_is_namespaced(self):
        url = asset_catalog_visual.preview_source(
            row('gta5', 'model', {'id': 'prop_bench_01a', 'name': 'prop_bench_01a'}))
        self.assertEqual(
            url, 'https://example.invalid/previews/gta5/thumbnails/prop_bench_01a.png')

    def test_gta5_texture_preview_sanitises_names(self):
        url = asset_catalog_visual.preview_source(
            row('gta5', 'texture', {'txd': 'prop_bench_01a', 'name': 'bench_wood+d'}))
        self.assertEqual(
            url,
            'https://example.invalid/previews/gta5/textures/prop_bench_01a__bench_wood_d.png')

    def test_unknown_game_still_rejected(self):
        with self.assertRaises(ValueError):
            asset_catalog_visual.preview_source(
                row('gta6', 'model', {'id': 'x', 'name': 'x'}))

    def test_shortlist_accepts_gta5(self):
        import asset_catalog_shortlist
        parser = asset_catalog_shortlist.build_parser()
        args = parser.parse_args(['--db', 'x.sqlite', 'prepare', '--query', 'bench',
                                  '--game', 'gta5', '--out', 'o.json'])
        self.assertEqual(args.game, 'gta5')

    def test_shortlist_rejects_san_andreas(self):
        import asset_catalog_shortlist
        parser = asset_catalog_shortlist.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(['--db', 'x.sqlite', 'prepare', '--query', 'bench',
                               '--game', 'sa', '--out', 'o.json'])


if __name__ == '__main__':
    unittest.main()
