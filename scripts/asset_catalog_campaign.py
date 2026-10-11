#!/usr/bin/env python3
"""Split a public visual packet into disjoint, resumable reviewer packets.

Only the public packet is read: no asset identities, names or evaluation queries.
This prepares work for vision reviewers; it never generates annotations.
"""
import argparse, hashlib, json
from pathlib import Path
from PIL import Image, ImageDraw


def split_packet(packet_path, out, batch_size=80, per_page=12):
    if not 1 <= batch_size <= 240 or not 1 <= per_page <= 16:
        raise ValueError('batch_size must be 1..240 and per_page 1..16')
    packet = json.loads(Path(packet_path).read_text())
    images = packet['images']
    ids = [item['image_id'] for item in images]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate image IDs')
    # Fail before writing anything if evidence is missing or has changed.
    for item in images:
        data = Path(item['image_path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != item['image_sha256']:
            raise ValueError('Image evidence hash mismatch')
        with Image.open(item['image_path']) as im:
            im.verify()
    out = Path(out)
    batches = []
    for start in range(0, len(images), batch_size):
        items = images[start:start+batch_size]
        folder = out / f'batch-{start // batch_size:03}'
        public = {key: packet[key] for key in ('version', 'packet_id', 'instructions', 'response_schema')}
        public['images'] = [{key: item[key] for key in ('image_id', 'image_path', 'image_sha256')} for item in items]
        for image,item in zip(public['images'],items):
            if 'pixel_properties' in item:image['pixel_properties']=item['pixel_properties']
        target = folder / 'packet.json'
        if target.exists() and json.loads(target.read_text()) != public:
            raise ValueError('Different packet already exists; use a new output directory')
        batches.append((folder, public))
    for folder, public in batches:
        folder.mkdir(parents=True, exist_ok=True)
        (folder/'packet.json').write_text(json.dumps(public, indent=2)+'\n')
        items = public['images']
        for start in range(0, len(items), per_page):
            page = items[start:start+per_page]
            cols = min(3, len(page)); rows = (len(page)+cols-1)//cols
            canvas = Image.new('RGB', (cols*420, rows*448), '#eeeeee')
            draw = ImageDraw.Draw(canvas)
            for i, item in enumerate(page):
                with Image.open(item['image_path']) as original:
                    rgba = original.convert('RGBA')
                    background = Image.new('RGBA', rgba.size, (238, 238, 238, 255))
                    im = Image.alpha_composite(background, rgba).convert('RGB')
                    im.thumbnail((416, 412))
                x = (i % cols)*420; y = (i // cols)*448
                canvas.paste(im, (x+(420-im.width)//2, y+(412-im.height)//2))
                draw.text((x+4, y+418), item['image_id'], fill='black')
            canvas.save(folder/f'sheet-{start//per_page:03}.jpg', quality=92)
    report = {'packet_id': packet['packet_id'], 'images': len(images),
              'batches': [{'packet': str((folder/'packet.json').resolve()), 'images': len(public['images'])} for folder, public in batches],
              'annotation_status': 'Prepared only. Actual visual reviews and evidence-bound import still required.'}
    out.mkdir(parents=True, exist_ok=True)
    (out/'dispatch.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--batch-size', type=int, default=80)
    parser.add_argument('--per-page', type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(split_packet(args.packet, args.out, args.batch_size, args.per_page), indent=2))

if __name__ == '__main__':
    main()
