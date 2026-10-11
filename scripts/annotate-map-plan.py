"""Add a coordinate grid to a map plan, using the catalogue Python environment."""
import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def annotate(report, markers=None):
    meta = json.loads(Path(report).read_text())
    path = Path(meta['image'])
    im = Image.open(path).convert('RGB')
    draw = ImageDraw.Draw(im)
    size, span = im.width, meta['span']
    sx, sy = meta['centre']
    try:
        font = ImageFont.truetype('arial.ttf', max(14, size // 80))
    except OSError:
        font = ImageFont.load_default(size=max(14, size // 80))
    def pixel(x, y):
        return ((x-sx)/span*size+size/2, size/2-(y-sy)/span*size)
    step = 10 if span <= 150 else 25
    for x in range(math.ceil((sx-span/2)/step)*step, math.ceil(sx+span/2), step):
        px, _ = pixel(x, sy)
        draw.line((px, 0, px, size), fill=(175,175,175), width=1)
        draw.text((px+3, 5), str(x), font=font, fill='yellow', stroke_width=1, stroke_fill='black')
    for y in range(math.ceil((sy-span/2)/step)*step, math.ceil(sy+span/2), step):
        _, py = pixel(sx, y)
        draw.line((0, py, size, py), fill=(175,175,175), width=1)
        draw.text((3, py+3), str(y), font=font, fill='yellow', stroke_width=1, stroke_fill='black')
    if markers:
        for marker in json.loads(Path(markers).read_text()):
            pts = [pixel(*p) for p in marker['polygon']]
            colour = marker.get('colour', '#51ffd2')
            draw.line(pts+[pts[0]], fill=colour, width=5)
            draw.text(pts[0], marker['name'], font=font, fill=colour, stroke_width=2, stroke_fill='black')
    result = path.with_name('plan-grid.png')
    im.save(result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    parser.add_argument('--markers')
    args = parser.parse_args()
    print(annotate(args.report, args.markers))
