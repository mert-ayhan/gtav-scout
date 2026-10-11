#!/usr/bin/env python3
"""Blender CLI textured static-drawable previews for GTA V. No orientation is assumed.

blender -b --python scripts/render-asset-catalog-views.py -- --input batch.json --output DIR

Input is the input.json written by `gtav-scout-extract extract`:
{"assets":[{"id":"gta5:model:...","model":"...","drawable":"/file.ydr",
"textures":{"texture_name":"/texture.png"},"sourceFiles":["/original.ytd"]}]}

A render that succeeded is evidence to look at, not a review.
"""
import argparse
import hashlib
import json
import math
import sys
import time
import traceback
from array import array
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from asset_catalog_image_signal import pixel_signal

AZIMUTHS = [45, 135, 225, 315]
ELEVATION = 25


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ensure_sollumz():
    """Enable Sollumz in this Blender session.

    Installing an extension enables it for the installing session only unless the
    preferences were saved, so a background render can find the add-on present but
    switched off. Enabling it here makes the renderer independent of how Blender
    was set up, and fails with a usable message when it is genuinely absent.
    """
    # bpy.ops.<name> is a lazy proxy that exists for any name, so hasattr on it says
    # nothing. The registered operator class is the real signal.
    def registered():
        return hasattr(bpy.types, 'SOLLUMZ_OT_import_assets')

    if registered():
        return
    import addon_utils
    candidates = [m.__name__ for m in addon_utils.modules()
                  if 'sollumz' in m.__name__.lower()]
    for module in candidates:
        try:
            addon_utils.enable(module, default_set=False, persistent=True)
        except Exception as error:
            print('SOLLUMZ_ENABLE_FAILED', module, error, flush=True)
            continue
        if registered():
            print('SOLLUMZ_ENABLED', module, flush=True)
            return
    raise SystemExit(
        'Sollumz is not available in this Blender. Install it from its release zip '
        '(see docs/blender-cli.md); modules seen: %s' % (candidates or 'none'))


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for collection in (bpy.data.meshes, bpy.data.materials, bpy.data.images,
                       bpy.data.cameras, bpy.data.lights, bpy.data.armatures,
                       bpy.data.collections):
        for block in list(collection):
            if block.users == 0:
                collection.remove(block)


RENDER_MESH = 'sollumz_drawable_model'
# Rockstar ships stand-in textures on assets that were never finished. Geometry
# wearing one renders confidently and shows nothing about the object, so it must
# not be reported as usable evidence.
PLACEHOLDER_TEXTURES = {'prop_remove', 'none', 'null', 'default'}


def import_drawable(path):
    """Import one drawable through Sollumz and return its renderable meshes.

    A fragment brings its physics bounds in as meshes too, and for a prop like a
    traffic light those outnumber the visual geometry: rendering everything shows
    collision boxes wearing placeholder materials rather than the object. Only
    drawable models are kept.

    Imported lights are deleted as well. They are the object's own game lighting,
    and previews are meant to be comparable to each other under one neutral rig.
    """
    before = set(bpy.data.objects)
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('No such drawable: %s' % path)
    result = bpy.ops.sollumz.import_assets(
        directory=str(path.parent), files=[{'name': path.name}])
    if 'FINISHED' not in result:
        raise ValueError('Sollumz import did not finish: %s' % (result,))

    # Work by name: removing an object invalidates every Python reference to it, so
    # deciding what to keep before deleting anything is the only safe order.
    created = [o.name for o in bpy.data.objects if o not in before]
    keep, drop = [], []
    for name in created:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        if obj.type == 'LIGHT':
            drop.append(name)
        elif obj.type == 'MESH' and obj.data is not None and len(obj.data.vertices):
            (keep if sollum_type(obj) == RENDER_MESH else drop).append(name)

    if not any(bpy.data.objects.get(n) for n in keep):
        # Nothing declared itself a drawable model. Render whatever meshes exist
        # rather than dropping the asset, and keep the lights out regardless.
        keep = [n for n in created
                if (bpy.data.objects.get(n) is not None
                    and bpy.data.objects[n].type == 'MESH'
                    and bpy.data.objects[n].data is not None
                    and len(bpy.data.objects[n].data.vertices))]
        drop = [n for n in created
                if bpy.data.objects.get(n) is not None
                and bpy.data.objects[n].type == 'LIGHT']

    for name in drop:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)

    meshes = [bpy.data.objects[n] for n in keep if n in bpy.data.objects]
    if not meshes:
        raise ValueError('Sollumz imported no mesh geometry')
    return meshes


def sollum_type(obj):
    value = getattr(obj, 'sollum_type', None)
    if value is None:
        value = obj.get('sollum_type')
    return str(value) if value is not None else ''


def texture_candidates(node):
    """Names this image node might be asking for, most specific first.

    Sollumz names its image nodes after the shader's texture parameter and, when it
    knows one, the referenced texture. Both spellings are tried rather than assuming
    one, and no partial match is invented: a texture that cannot be identified is
    reported missing.
    """
    names = []
    if node.image is not None:
        names.append(node.image.name)
        if getattr(node.image, 'filepath', ''):
            names.append(Path(bpy.path.abspath(node.image.filepath)).name)
    if node.label:
        names.append(node.label)
    names.append(node.name)
    seen, result = set(), []
    for name in names:
        stem = Path(str(name)).stem.lower()
        # Blender uniquifies duplicate datablock names with a ".001" suffix.
        if len(stem) > 4 and stem[-4] == '.' and stem[-3:].isdigit():
            stem = stem[:-4]
        if stem and stem not in seen:
            seen.add(stem)
            result.append(stem)
    return result


def apply_textures(objects, texture_paths):
    """Bind decoded PNGs to the materials Sollumz created.

    Sollumz does not read YTD, so its image nodes arrive without pixels. Missing
    textures are reported, never substituted with a stand-in that would read as
    material evidence.
    """
    available = {k.lower(): v for k, v in texture_paths.items()}
    missing, bound = set(), 0
    seen_materials = set()
    for obj in objects:
        for slot in obj.material_slots:
            material = slot.material
            if material is None or material.name in seen_materials:
                continue
            seen_materials.add(material.name)
            if not material.use_nodes:
                continue
            for node in material.node_tree.nodes:
                if node.type != 'TEX_IMAGE':
                    continue
                for stem in texture_candidates(node):
                    path = available.get(stem)
                    if path and Path(path).is_file():
                        node.image = bpy.data.images.load(str(path), check_existing=True)
                        node.interpolation = 'Closest'
                        bound += 1
                        break
                else:
                    candidates = texture_candidates(node)
                    missing.add(candidates[0] if candidates else node.name)
    return sorted(missing), bound


def placeholder_share(objects):
    """Fraction of the rendered surface that wears a stand-in texture.

    Reported by area rather than by material count: one placeholder material can
    cover a whole prop while a real one covers a bolt.
    """
    placeholder_names, total, flagged = set(), 0.0, 0.0
    for obj in objects:
        mesh = obj.data
        materials = list(mesh.materials)
        areas = [0.0] * max(len(materials), 1)
        for polygon in mesh.polygons:
            index = min(polygon.material_index, len(areas) - 1)
            areas[index] += polygon.area
        for index, material in enumerate(materials):
            if material is None:
                continue
            stems = set()
            if material.use_nodes:
                for node in material.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image is not None:
                        stems.add(Path(node.image.name).stem.lower())
            stems.add(Path(material.name).stem.lower())
            total += areas[index]
            hits = stems & PLACEHOLDER_TEXTURES
            if hits:
                flagged += areas[index]
                placeholder_names.update(hits)
    if total <= 0:
        return 0.0, []
    return flagged / total, sorted(placeholder_names)


def frame_and_render(objects, folder, size, samples):
    bpy.context.view_layer.update()
    points = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    low = Vector([min(v[i] for v in points) for i in range(3)])
    high = Vector([max(v[i] for v in points) for i in range(3)])
    centre = (low + high) / 2
    radius = max((v - centre).length for v in points)
    if radius < 1e-6:
        raise ValueError('Degenerate bounds')

    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.35, .35, .35, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = .8
    scene.view_settings.view_transform = 'Standard'

    bpy.ops.object.light_add(type='AREA',
                             location=centre + Vector((radius, -radius, radius * 3)))
    light = bpy.context.object
    light.data.energy = radius * radius * 180
    light.data.size = radius * 4

    bpy.ops.object.camera_add()
    camera = bpy.context.object
    scene.camera = camera
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = radius * 2.3
    camera.data.clip_end = max(1000, radius * 20)

    views = []
    elevation = math.radians(ELEVATION)
    for azimuth in AZIMUTHS:
        angle = math.radians(azimuth)
        camera.location = centre + Vector((
            math.cos(angle) * math.cos(elevation),
            math.sin(angle) * math.cos(elevation),
            math.sin(elevation))) * radius * 5
        camera.rotation_euler = (centre - camera.location).to_track_quat('-Z', 'Y').to_euler()
        path = folder / ('azimuth-%03d.png' % azimuth)
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)

        rendered = bpy.data.images.load(str(path), check_existing=False)
        pixels = array('f', [0]) * len(rendered.pixels)
        rendered.pixels.foreach_get(pixels)
        signal = pixel_signal(pixels, rendered.channels)
        bpy.data.images.remove(rendered)
        views.append({'azimuthDegrees': azimuth, 'elevationDegrees': ELEVATION,
                      'path': str(path), 'sha256': sha(path), 'signal': signal})

    triangles = sum(len(o.data.polygons) for o in objects)
    return views, list(low), list(high), triangles


def render_batch(assets, out, size, samples):
    recipe = {
        'rendererSha256': sha(__file__),
        'signalCheckerSha256': sha(ROOT / 'scripts/asset_catalog_image_signal.py'),
        'importer': 'Sollumz',
        'blender': bpy.app.version_string,
        'engine': 'CYCLES',
        'samples': samples,
        'resolution': size,
        'azimuthDegrees': AZIMUTHS,
        'elevationDegrees': ELEVATION,
        'textureFilter': 'Closest',
        'geometry': 'all mesh objects Sollumz creates; no inferred front',
    }
    report = {'recipe': recipe, 'assets': []}
    started = time.time()

    for asset in assets:
        record = {'id': asset['id'], 'model': asset.get('model', asset['id']),
                  'sourceExtraction': asset.get('sources', []), 'status': 'failed'}
        try:
            files = sorted(set([asset['drawable']]
                               + list(asset.get('textures', {}).values())
                               + asset.get('sourceFiles', [])))
            hashes = {str(Path(f).resolve()): sha(f) for f in files}
            fingerprint = hashlib.sha256(json.dumps(
                {'recipe': recipe, 'sources': hashes,
                 'textureMapping': asset.get('textures', {})},
                sort_keys=True).encode()).hexdigest()
            folder = out / fingerprint[:20]
            folder.mkdir(exist_ok=True)
            cache = folder / 'manifest.json'
            if cache.exists():
                prior = json.loads(cache.read_text())
                if (prior.get('fingerprint') == fingerprint
                        and len(prior.get('views', [])) == len(AZIMUTHS)
                        and all(Path(v['path']).is_file() and sha(v['path']) == v['sha256']
                                for v in prior['views'])):
                    prior.update({'id': asset['id'], 'model': record['model'], 'cacheHit': True})
                    report['assets'].append(prior)
                    print('ASSET_PREVIEW', record['id'], prior.get('status'), 'cached', flush=True)
                    continue

            clear_scene()
            objects = import_drawable(asset['drawable'])
            missing, bound = apply_textures(objects, asset.get('textures', {}))
            views, low, high, triangles = frame_and_render(objects, folder, size, samples)

            blank = all(v['signal']['uniform'] for v in views)
            low_signal = all(v['signal']['low_signal'] for v in views)
            share, placeholders = placeholder_share(objects)
            record.update({
                'status': ('blank_render' if blank else
                           'low_signal_render' if low_signal else
                           'placeholder_texture' if share > 0.5 else
                           'incomplete_textures' if missing else 'ready'),
                'placeholderTextureShare': round(share, 3),
                'placeholderTextures': placeholders,
                'cacheHit': False, 'fingerprint': fingerprint, 'sourceSha256': hashes,
                'missingTextures': missing, 'boundTextures': bound,
                'boundsMin': low, 'boundsMax': high,
                'triangles': triangles, 'views': views, 'recipe': recipe})
            if blank:
                record['error'] = ('All four views are uniform; this render provides no '
                                   'visible object evidence. Another preview/context is required.')
            elif share > 0.5:
                record['warning'] = (
                    'Most of this object is textured with a Rockstar stand-in (%s). The '
                    'render is faithful to the files, but shows the placeholder rather '
                    'than a finished appearance, so it is not evidence of how the object '
                    'looks. Treat the asset as unfinished in this game build.'
                    % ', '.join(placeholders))
            elif low_signal:
                record['warning'] = ('All four views have very low signal; may be invisible '
                                     'effect geometry, background noise, or a thin/low-contrast '
                                     'object. Requires actual visual review/context, not '
                                     'automatic rejection.')
            cache.write_text(json.dumps(record, indent=2) + '\n')
        except Exception as error:
            record['error'] = str(error)
            record['traceback'] = traceback.format_exc()

        report['assets'].append(record)
        (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
        print('ASSET_PREVIEW', record['id'], record['status'], flush=True)

    report['seconds'] = round(time.time() - started, 2)
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--size', type=int, default=384)
    parser.add_argument('--samples', type=int, default=12)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])

    ensure_sollumz()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    payload = json.loads(Path(args.input).read_text())
    report = render_batch(payload['assets'], out, args.size, args.samples)
    print('PREVIEW_BATCH', json.dumps({
        'assets': len(report['assets']), 'seconds': report['seconds'],
        'manifest': str(out / 'manifest.json')}), flush=True)


if __name__ == '__main__':
    main()
