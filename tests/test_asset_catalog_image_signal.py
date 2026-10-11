import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from asset_catalog_image_signal import pixel_signal

class SignalTests(unittest.TestCase):
    def test_uniform_gray_is_blank(self):
        self.assertTrue(pixel_signal([.6,.6,.6,1.]*100)['uniform'])
    def test_alpha_change_alone_is_not_visible_on_render(self):
        self.assertTrue(pixel_signal([.6,.6,.6,1.,.6,.6,.6,0.])['uniform'])
    def test_thin_low_contrast_geometry_not_discarded(self):
        values=[.6,.6,.6,1.]*10000;values[-4]=.605
        signal=pixel_signal(values)
        self.assertFalse(signal['uniform']);self.assertTrue(signal['low_signal'])
    def test_visible_patch_reports_fraction(self):
        signal=pixel_signal([.6,.6,.6,1.]*60+[1.,0.,0.,1.]*40)
        self.assertFalse(signal['uniform']);self.assertEqual(signal['foreground_fraction_vs_median'],.4)
    def test_nearly_blank_background_with_render_noise_flagged(self):
        signal=pixel_signal([144/255,144/255,144/255,1.]*980+[145/255,145/255,145/255,1.]*19+[138/255,141/255,141/255,1.])
        self.assertFalse(signal['uniform']);self.assertTrue(signal['low_signal'])
    def test_incomplete_pixel_rejected(self):
        with self.assertRaises(ValueError):pixel_signal([1,2])

if __name__=='__main__':unittest.main()
