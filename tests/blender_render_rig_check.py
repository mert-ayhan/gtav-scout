"""Exercises the renderer's camera rig and signal detection inside Blender.

Run by tests/test_gta5_renderer.py. Substitutes synthetic meshes for Sollumz
imports, so it proves everything except the import itself without needing GTA V:
that four views are produced, that a visible object is not reported blank, and
that an empty scene is.

blender -b --python tests/blender_render_rig_check.py -- --output DIR
"""
import argparse
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import importlib.util

spec = importlib.util.spec_from_file_location(
    'render_views', ROOT / 'scripts' / 'render-asset-catalog-views.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)

    failures = []

    # A solid object must render as visible evidence in all four views.
    renderer.clear_scene()
    bpy.ops.mesh.primitive_cube_add(size=2)
    cube = bpy.context.object
    folder = out / 'cube'
    folder.mkdir(exist_ok=True)
    views, low, high, triangles = renderer.frame_and_render(
        [cube], folder, size=96, samples=4)

    if len(views) != len(renderer.AZIMUTHS):
        failures.append('rendered %d views, expected %d' % (len(views), len(renderer.AZIMUTHS)))
    if [v['azimuthDegrees'] for v in views] != renderer.AZIMUTHS:
        failures.append('azimuths were %s' % [v['azimuthDegrees'] for v in views])
    for view in views:
        if not Path(view['path']).is_file():
            failures.append('missing render %s' % view['path'])
        if len(view['sha256']) != 64:
            failures.append('bad hash for %s' % view['path'])
    if all(v['signal']['uniform'] for v in views):
        failures.append('a lit cube was reported as a blank render')
    if triangles <= 0:
        failures.append('triangle count was %d' % triangles)
    if not (low[0] < high[0] and low[1] < high[1] and low[2] < high[2]):
        failures.append('bounds were degenerate: %s %s' % (low, high))

    # An empty scene has no geometry to frame, and must say so rather than
    # producing a confidently blank preview.
    renderer.clear_scene()
    bpy.ops.mesh.primitive_plane_add(size=0.0)
    degenerate = bpy.context.object
    try:
        renderer.frame_and_render([degenerate], out / 'flat', size=64, samples=1)
        failures.append('degenerate geometry did not raise')
    except ValueError:
        pass
    except Exception as error:
        failures.append('degenerate geometry raised %r' % error)

    (out / 'result.json').write_text(json.dumps({'failures': failures}, indent=2))
    print('RIG_CHECK', json.dumps({'failures': failures}), flush=True)


if __name__ == '__main__':
    main()
