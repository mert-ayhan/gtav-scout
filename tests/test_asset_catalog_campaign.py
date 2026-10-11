import hashlib, importlib.util, json, tempfile, unittest
from pathlib import Path
from PIL import Image
spec = importlib.util.spec_from_file_location('campaign', Path(__file__).parents[1]/'scripts/asset_catalog_campaign.py')
campaign = importlib.util.module_from_spec(spec); spec.loader.exec_module(campaign)

class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.packet = self.root/'packet.json'
        images = []
        for i in range(5):
            p = self.root/f'{i}.png'; Image.new('RGB',(8,8),(i,0,0)).save(p)
            images.append({'image_id':f'img_{i}','image_path':str(p),'image_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'private_name':'MUST NOT LEAK'})
        self.data = {'version':'visual-packet-v1','packet_id':'example','instructions':'Inspect','response_schema':{},'images':images,'private_query':'MUST NOT LEAK'}
        self.write()
    def write(self): self.packet.write_text(json.dumps(self.data))
    def test_disjoint_complete_blind_and_resume(self):
        out = self.root/'out'; r=campaign.split_packet(self.packet,out,2)
        ids=[]
        for batch in r['batches']:
            raw=Path(batch['packet']).read_text(); self.assertNotIn('MUST NOT LEAK',raw)
            ids += [i['image_id'] for i in json.loads(raw)['images']]
        self.assertEqual(ids,[f'img_{i}' for i in range(5)])
        self.assertEqual(r,campaign.split_packet(self.packet,out,2))
    def test_corrupt_evidence_fails_before_outputs(self):
        Path(self.data['images'][0]['image_path']).write_bytes(b'corrupted')
        with self.assertRaises(ValueError): campaign.split_packet(self.packet,self.root/'out')
        self.assertFalse((self.root/'out').exists())
    def test_duplicate_and_bounds_rejected(self):
        self.data['images'].append(self.data['images'][0]);self.write()
        with self.assertRaises(ValueError): campaign.split_packet(self.packet,self.root/'out')
        with self.assertRaises(ValueError): campaign.split_packet(self.packet,self.root/'out',0)
    def test_transparent_pixels_composite_on_light_background(self):
        p=Path(self.data['images'][0]['image_path'])
        im=Image.new('RGBA',(80,80),(0,0,0,0))
        for x in range(20,60):
            for y in range(20,60): im.putpixel((x,y),(255,0,0,255))
        im.save(p); before=p.read_bytes()
        self.data['images']=self.data['images'][:1]
        self.data['images'][0]['image_sha256']=hashlib.sha256(before).hexdigest(); self.write()
        campaign.split_packet(self.packet,self.root/'out',2)
        with Image.open(self.root/'out/batch-000/sheet-000.jpg') as sheet:
            # 80px image centered in 420x412 area: alpha border becomes gray.
            self.assertTrue(all(v>220 for v in sheet.getpixel((175,171))))
            red=sheet.getpixel((210,206));self.assertGreater(red[0],220);self.assertLess(red[1],30)
        self.assertEqual(p.read_bytes(),before)

    def test_existing_different_packet_preserved(self):
        out=self.root/'out'; campaign.split_packet(self.packet,out,2)
        self.data['packet_id']='changed';self.write()
        with self.assertRaises(ValueError):campaign.split_packet(self.packet,out,2)
        self.assertEqual(json.loads((out/'batch-000/packet.json').read_text())['packet_id'],'example')

if __name__=='__main__':unittest.main()
