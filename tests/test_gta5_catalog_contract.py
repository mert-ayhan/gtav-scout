"""The catalogue contract the .NET inventory command must satisfy.

No GTA V needed: these assert that the record shapes the scanners emit are ones
`asset_catalog.records()` accepts, and that they carry the meaning the scanners
intend.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import asset_catalog

MODELS = {'models': [
    {'id': 'prop_bench_01a', 'name': 'prop_bench_01a', 'dff': 'prop_bench_01a',
     'txd': 'prop_bench_01a', 'drawableDict': '0',
     'source': 'x64a.rpf/levels/gta5/props.rpf/v_bench.ytyp',
     'section': 'CBaseArchetypeDef', 'lodDist': 120.0, 'tags': []},
    {'id': 'prop_bench_02a', 'name': 'prop_bench_02a', 'dff': 'prop_bench_02a',
     'txd': 'prop_streetlights', 'drawableDict': 'v_bench_dict',
     'source': 'x64a.rpf/levels/gta5/props.rpf/v_bench.ytyp',
     'section': 'CTimeArchetypeDef', 'lodDist': 60.0, 'tags': []},
]}
TEXTURES = {'textures': [
    {'name': 'bench_wood', 'txd': 'prop_bench_01a',
     'source': 'x64a.rpf/levels/gta5/props.rpf/prop_bench_01a.ytd',
     'width': 512, 'height': 512, 'format': 'D3DFMT_DXT1'},
]}
SIZES = {'prop_bench_01a': {'width': 1.8, 'height': 0.9, 'depth': 0.6}}
LOCATIONS = {'locations': {'prop_bench_01a': {
    'ipls': ['hw1_08.ymap'],
    'locs': [{'x': 1.5, 'y': -2.0, 'z': 30.25, 'i': 0}],
    'count': 1}}}


def snapshot(models=MODELS, textures=TEXTURES, sizes=SIZES, locations=LOCATIONS):
    root = Path(tempfile.mkdtemp())
    (root / 'models/data').mkdir(parents=True)
    (root / 'textures/data').mkdir(parents=True)
    for name, value in [('models/data/models.json', models),
                        ('textures/data/textures.json', textures),
                        ('models/data/model-sizes.json', sizes),
                        ('models/data/locations.json', locations)]:
        (root / name).write_text(json.dumps(value))
    return root


class Gta5CatalogContract(unittest.TestCase):
    def setUp(self):
        self.root = snapshot()

    def payloads(self):
        return {r[0]: r[4] for r in asset_catalog.records(self.root, 'gta5')}

    def test_records_produce_gta5_identities(self):
        keys = [r[0] for r in asset_catalog.records(self.root, 'gta5')]
        self.assertIn('gta5:model:prop_bench_01a', keys)
        self.assertIn(
            'gta5:texture:' + asset_catalog.canonical(
                ['x64a.rpf/levels/gta5/props.rpf/prop_bench_01a.ytd',
                 'prop_bench_01a', 'bench_wood']),
            keys)

    def test_archetype_bounds_become_dimensions(self):
        self.assertEqual(self.payloads()['gta5:model:prop_bench_01a']['dimensions'],
                         {'width': 1.8, 'height': 0.9, 'depth': 0.6})

    def test_archetype_without_bounds_has_no_dimensions(self):
        self.assertIsNone(self.payloads()['gta5:model:prop_bench_02a']['dimensions'])

    def test_ymap_placements_are_carried(self):
        placements = self.payloads()['gta5:model:prop_bench_01a']['placements']
        self.assertEqual(placements['count'], 1)
        self.assertEqual(placements['ipls'], ['hw1_08.ymap'])
        self.assertEqual(placements['examples'][0]['z'], 30.25)

    def test_build_ingests_the_snapshot(self):
        db = asset_catalog.connect(self.root / 'catalog.sqlite')
        asset_catalog.build(db, self.root, game='gta5')
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM assets WHERE game='gta5'").fetchone()[0], 3)

    def test_search_finds_an_archetype_by_name(self):
        db = asset_catalog.connect(self.root / 'catalog.sqlite')
        asset_catalog.build(db, self.root, game='gta5')
        hits = [r['key'] for r in asset_catalog.search(db, 'bench')]
        self.assertIn('gta5:model:prop_bench_01a', hits)


class Gta5ArchetypeOverrides(unittest.TestCase):
    """The scanner must resolve name collisions itself: the core rejects them."""

    def test_conflicting_duplicate_identity_is_rejected(self):
        root = snapshot(models={'models': [
            dict(MODELS['models'][0]),
            dict(MODELS['models'][0], txd='other_dictionary'),
        ]})
        with self.assertRaises(ValueError):
            list(asset_catalog.records(root, 'gta5'))


class Gta5Vehicles(unittest.TestCase):
    """Vehicles come from vehicles.meta, not a YTYP, but reach the catalogue as models."""

    VEHICLE = {'models': [
        {'id': 'prairie', 'name': 'prairie', 'nameResolved': True, 'dff': 'prairie',
         'txd': 'prairie', 'drawableDict': '0', 'source': 'vehicles.meta',
         'section': 'CVehicleModelInfo', 'vehicleMake': 'BOLLOKAN',
         'vehicleClass': 'VC_COMPACT', 'vehicleType': 'VEHICLE_TYPE_CAR',
         'gameName': 'PRAIRIE', 'handlingId': 'PRAIRIE',
         'tags': ['bollokan', 'prairie', 'compact', 'car']},
    ]}

    def catalogue(self):
        root = snapshot(models=self.VEHICLE, textures={'textures': []},
                        sizes={'prairie': {'width': 1.83, 'height': 1.15, 'depth': 4.37}},
                        locations={'locations': {}})
        db = asset_catalog.connect(root / 'catalog.sqlite')
        asset_catalog.build(db, root, game='gta5')
        return db

    def test_vehicle_is_indexed_as_a_model(self):
        db = self.catalogue()
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM assets WHERE kind='model'").fetchone()[0], 1)

    def test_vehicle_is_searchable_by_its_make(self):
        # "prairie" never says Bollokan, so the make has to reach the index as a tag.
        hits = [r['key'] for r in asset_catalog.search(self.catalogue(), 'bollokan')]
        self.assertIn('gta5:model:prairie', hits)

    def test_vehicle_is_searchable_by_class(self):
        hits = [r['key'] for r in asset_catalog.search(self.catalogue(), 'compact')]
        self.assertIn('gta5:model:prairie', hits)

    def test_vehicle_carries_measured_dimensions(self):
        root = snapshot(models=self.VEHICLE, textures={'textures': []},
                        sizes={'prairie': {'width': 1.83, 'height': 1.15, 'depth': 4.37}},
                        locations={'locations': {}})
        payload = {r[0]: r[4] for r in asset_catalog.records(root, 'gta5')}
        self.assertEqual(payload['gta5:model:prairie']['dimensions']['depth'], 4.37)


class Gta5TextureOccurrences(unittest.TestCase):
    def test_same_name_in_two_dictionaries_is_two_identities(self):
        root = snapshot(models={'models': []}, textures={'textures': [
            {'name': 'wood', 'txd': 'a', 'source': 'x64a.rpf/a.ytd'},
            {'name': 'wood', 'txd': 'b', 'source': 'x64b.rpf/b.ytd'},
        ]})
        keys = [r[0] for r in asset_catalog.records(root, 'gta5')]
        self.assertEqual(len(keys), 2)
        self.assertEqual(len(set(keys)), 2)


if __name__ == '__main__':
    unittest.main()
