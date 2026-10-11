"""Generate original toy images and metadata, never GTA data or benchmark evidence."""
import argparse, hashlib, json
from pathlib import Path
from PIL import Image, ImageDraw
import asset_catalog as catalog

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='output/demo');a=p.parse_args();root=Path(a.out).resolve()
    if root.exists():p.error('Choose a fresh output directory')
    root.mkdir(parents=True)
    records=[];overrides={};descriptions={}
    for ident,name,description,color,shape in [(1,'item_x01','Red wooden chair with a tall back and four legs.','firebrick','chair'),(2,'item_x02','Blue rectangular office desk with two supporting legs.','steelblue','desk')]:
        im=Image.new('RGB',(384,384),'#ece8df');d=ImageDraw.Draw(im)
        if shape=='chair':
            d.rectangle((125,75,255,205),fill=color);d.rectangle((110,195,270,222),fill=color)
            for x in [120,240]:d.rectangle((x,220,x+15,325),fill=color)
        else:
            d.rectangle((60,155,325,185),fill=color)
            for x in [80,285]:d.rectangle((x,185,x+15,325),fill=color)
        path=root/f'{name}.png';im.save(path)
        records.append({'id':ident,'name':name,'txd':'synthetic','tags':[]})
        overrides[f'sa:model:{ident}']=[str(path)];descriptions[f'sa:model:{ident}']=description
    for name,data in [('models/data/models.json',{'models':records}),('textures/data/textures.json',{'textures':[]}),('keys.json',list(overrides)),('overrides.json',overrides)]:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,indent=2)+'\n')
    db=catalog.connect(root/'catalog.sqlite');catalog.build(db,root)
    annotations=[]
    for key,description in descriptions.items():
        path=Path(overrides[key][0]);h=db.execute('SELECT hash FROM assets WHERE key=?',(key,)).fetchone()[0]
        annotations.append({'key':key,'asset_hash':h,'description':description,'tags':[description.split()[0].lower()], 'method':'curated-context','model':'synthetic-fixture-generator','confidence':1,
                            'evidence':{'preview':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'limitations':'Known synthetic construction; no human/model review or GTA relevance benchmark.'}})
    target=root/'synthetic-annotations.json';target.write_text(json.dumps(annotations,indent=2)+'\n');catalog.annotate(db,target);db.close()
    print(json.dumps({'root':str(root),'database':str(root/'catalog.sqlite'),'assets':len(records),'synthetic':True},indent=2))
if __name__=='__main__':main()
