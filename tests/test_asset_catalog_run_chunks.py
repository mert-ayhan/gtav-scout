import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
import asset_catalog_run_chunks as runner


class ChunkRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root/'view.png'
        Image.new('RGB', (16, 16), 'white').save(self.image)
        self.view = {'path': str(self.image), 'sha256': hashlib.sha256(self.image.read_bytes()).hexdigest()}

    def asset(self, status='ready'):
        return {'id': 'gta5:model:1', 'status': status, 'views': [self.view.copy() for _ in range(4)]}

    def test_failed_geometry_is_not_sent_to_review(self):
        self.assertEqual({}, runner.evidence_overrides({'assets': [self.asset('failed')]}))

    def test_incomplete_materials_keep_geometry_evidence(self):
        result = runner.evidence_overrides({'assets': [self.asset('incomplete_textures')]})
        self.assertEqual(result, {'gta5:model:1': [str(self.image)]*4})

    def test_corrupt_or_partial_evidence_rejected(self):
        item = self.asset()
        item['views'].pop()
        with self.assertRaises(ValueError):
            runner.evidence_overrides({'assets': [item]})
        self.image.write_bytes(b'corrupted')
        with self.assertRaises(ValueError):
            runner.evidence_overrides({'assets': [self.asset()]})

    def test_process_failure_cannot_reuse_old_manifest(self):
        with patch.object(runner.subprocess, 'run') as run:
            run.return_value.returncode = 1
            with self.assertRaises(RuntimeError):
                runner.run_chunk(self.root, self.root/'db.sqlite', 'blender',reserve_bytes=0)
        journal = [json.loads(line) for line in (self.root/'runs.jsonl').read_text().splitlines()]
        self.assertEqual(journal[-1]['stage'], 'render_process_failed')
        self.assertFalse((self.root/'ready.json').exists())
    def test_storage_reserve_prevents_renderer_start(self):
        with patch.object(runner.shutil,'disk_usage') as usage,patch.object(runner.subprocess,'run') as run:
            usage.return_value.free=100
            with self.assertRaisesRegex(RuntimeError,'Storage reserve'):
                runner.run_chunk(self.root,self.root/'db.sqlite','blender',reserve_bytes=200)
            run.assert_not_called()

    def test_journal_preserves_prior_attempts(self):
        path = self.root/'runs.jsonl'
        runner.record(path, {'stage': 'first'})
        runner.record(path, {'stage': 'second'})
        self.assertEqual([json.loads(line)['stage'] for line in path.read_text().splitlines()], ['first', 'second'])


if __name__ == '__main__':
    unittest.main()
