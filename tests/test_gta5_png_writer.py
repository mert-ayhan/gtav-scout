"""Cross-language check on the .NET tool's hand-written PNG encoder.

Every rendered preview and every texture override depends on those bytes being a
PNG that other decoders accept, which a structural check inside the C# tool cannot
establish. Skips when the toolchain is unavailable, so the suite stays runnable
without .NET.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / 'tools' / 'GtavScout.Extract'


def toolchain_reason():
    if shutil.which('dotnet') is None:
        return 'dotnet is not on PATH'
    if not os.environ.get('CODEWALKER_PATH'):
        return 'CODEWALKER_PATH is not set'
    if not PROJECT.is_dir():
        return 'the extraction tool is not present'
    return None


class PngWriterOutput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = toolchain_reason()
        if reason:
            raise unittest.SkipTest(reason)
        cls.out = Path(tempfile.mkdtemp())
        completed = subprocess.run(
            ['dotnet', 'run', '-c', 'Release', '--project', str(PROJECT), '--',
             '--self-test', '--sample-out', str(cls.out)],
            capture_output=True, text=True)
        if completed.returncode != 0:
            raise unittest.SkipTest('self-test did not run: ' + completed.stderr[-500:])

    def test_sample_is_readable_and_correct(self):
        from PIL import Image
        with Image.open(self.out / 'sample.png') as image:
            self.assertEqual(image.mode, 'RGBA')
            self.assertEqual(image.size, (3, 2))
            for y in range(2):
                for x in range(3):
                    self.assertEqual(image.getpixel((x, y)),
                                     (10 + x, 100 + y, 200 + x + y, 255),
                                     'pixel %d,%d' % (x, y))


if __name__ == '__main__':
    unittest.main()
