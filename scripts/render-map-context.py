#!/usr/bin/env python3
"""Render a written .ymap in its real map surroundings, before and after.

blender -b --python scripts/render-map-context.py -- \
    --context CONTEXT.json --context-input CONTEXT_INPUT.json \
    --ymap FILE.ymap --ymap-input BUILD_INPUT.json \
    --site X,Y,Z --facing DEG --out DIR

CONTEXT.json lists the real map entities around the site (archetype, position,
world rotation as x,y,z,w, scale), as produced from `gtav-scout-extract nearby`.
CONTEXT_INPUT.json and BUILD_INPUT.json are `extract` batches holding the
drawables and decoded textures for those archetypes and for the build.

The AFTER pass does not trust the spec that produced the ymap. It reads the
written file with Sollumz — a reader independent of the CodeWalker code that
wrote it — and places each entity where that reader says it is. A render that
looks right is therefore evidence about the file itself.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector


def args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    parser.add_argument('--context-input', required=True)
    parser.add_argument('--ymap')
    parser.add_argument('--ymap-input', action='append', default=[])
    parser.add_argument('--plan-only', action='store_true',
                        help='Render a top-down orthographic plan of the site and stop')
    parser.add_argument('--plan-span', type=float, default=80.0)
    parser.add_argument('--site', required=True)
    parser.add_argument('--facing', type=float, default=0.0,
                        help='Heading the build faces, degrees; cameras stand in front of it')
    parser.add_argument('--out', required=True)
    parser.add_argument('--size', type=int, default=1600)
    parser.add_argument('--samples', type=int, default=96)
    parser.add_argument('--night', action='store_true', help='Moonlit preview with exported emissive shaders')
    parser.add_argument('--views', help='JSON list of {name, eye, target, lens} in world coordinates')
    parser.add_argument('--plan-markers', help='JSON list of {name, polygon: [[x,y],...]}')
    parser.add_argument('--context-blend', help='Reuse a saved before scene from an earlier context render')
    parser.add_argument('--empty-replacement-ymap', action='append', default=[],
                        help='Verified empty map replacing an entire context map; preserved in before views')
    return parser.parse_args(sys.argv[sys.argv.index('--') + 1:])


def jenkins(text):
    h = 0
    for c in text.lower().encode():
        h = (h + c) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    h = (h + (h << 15)) & 0xFFFFFFFF
    return h


def ensure_sollumz():
    if hasattr(bpy.types, 'SOLLUMZ_OT_import_assets'):
        return
    import addon_utils
    for module in [m.__name__ for m in addon_utils.modules() if 'sollumz' in m.__name__.lower()]:
        addon_utils.enable(module, default_set=False, persistent=True)
        if hasattr(bpy.types, 'SOLLUMZ_OT_import_assets'):
            return
    raise SystemExit('Sollumz is not available; see docs/blender-cli.md')


def bind_textures(meshes, textures):
    lowered = {k.lower(): v for k, v in textures.items()}
    seen = set()
    for obj in meshes:
        for slot in obj.material_slots:
            material = slot.material
            if material is None or material.name in seen or not material.use_nodes:
                continue
            seen.add(material.name)
            for node in material.node_tree.nodes:
                if node.type != 'TEX_IMAGE':
                    continue
                wanted = node.image.name if node.image else (node.label or node.name)
                stem = Path(str(wanted)).stem.lower()
                if len(stem) > 4 and stem[-4] == '.' and stem[-3:].isdigit():
                    stem = stem[:-4]
                path = lowered.get(stem)
                if path and Path(path).is_file():
                    node.image = bpy.data.images.load(str(path), check_existing=True)


class Library:
    """One imported copy of each drawable, instanced wherever it is placed."""

    def __init__(self):
        self.root = bpy.data.collections.new('drawable_library')
        bpy.context.scene.collection.children.link(self.root)
        self.collections = {}
        self.failed = {}

    def get(self, archetype, asset):
        if archetype in self.collections:
            return self.collections[archetype]
        if archetype in self.failed or asset is None:
            return None
        path = Path(asset['drawable']).resolve()
        before = set(bpy.data.objects)
        try:
            bpy.ops.sollumz.import_assets(directory=str(path.parent), files=[{'name': path.name}])
        except Exception as error:
            self.failed[archetype] = str(error)
            return None
        created = [o.name for o in bpy.data.objects if o not in before]
        keep = []
        for name in created:
            obj = bpy.data.objects.get(name)
            if obj is None:
                continue
            renderable = (obj.type == 'MESH' and obj.data and len(obj.data.vertices)
                          and str(getattr(obj, 'sollum_type', '')) == 'sollumz_drawable_model')
            if renderable:
                keep.append(name)
        # Bounds, lights and helpers go; the drawable models stay, at drawable-local
        # coordinates, which is exactly what an instance at the entity transform needs.
        for name in created:
            if name in keep:
                continue
            obj = bpy.data.objects.get(name)
            if obj is not None:
                bpy.data.objects.remove(obj, do_unlink=True)
        meshes = [bpy.data.objects[n] for n in keep if n in bpy.data.objects]
        if not meshes:
            self.failed[archetype] = 'no drawable model geometry'
            return None
        bind_textures(meshes, asset.get('textures', {}))
        collection = bpy.data.collections.new('lib_' + archetype)
        self.root.children.link(collection)
        for obj in meshes:
            world = obj.matrix_world.copy()
            obj.parent = None
            obj.matrix_world = world
            for existing in list(obj.users_collection):
                existing.objects.unlink(obj)
            collection.objects.link(obj)
        self.collections[archetype] = collection
        return collection

    def hide(self):
        layer = bpy.context.view_layer.layer_collection.children.get(self.root.name)
        if layer is not None:
            layer.exclude = True


def place(library, collection_name, archetype, asset, position, rotation_wxyz, scale):
    source = library.get(archetype, asset)
    if source is None:
        return None
    target = bpy.data.collections.get(collection_name)
    if target is None:
        target = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(target)
    instance = bpy.data.objects.new(archetype, None)
    instance.instance_type = 'COLLECTION'
    instance.instance_collection = source
    instance.matrix_world = Matrix.LocRotScale(Vector(position), Quaternion(rotation_wxyz), Vector(scale))
    target.objects.link(instance)
    return instance


def read_written_ymap(path):
    """Entities as Sollumz reads them from the file on disk."""
    path = Path(path).resolve()
    bpy.ops.sollumz.import_assets(directory=str(path.parent), files=[{'name': path.name}])
    container = bpy.context.scene.sz_maps_container
    maps = container.sz_maps if container else None
    rows = []
    for group in (maps.groups if maps else []):
        for ent in group.entities:
            rows.append({'archetype': ent.archetype_name, 'position': tuple(ent.position),
                         'rotation': tuple(ent.rotation),
                         'scale': (ent.scale_xy, ent.scale_xy, ent.scale_z)})
    return rows


def lighting(size, samples, night=False):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x = size
    scene.render.resolution_y = int(size * 0.62)
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'AgX' if 'AgX' in [
        t.identifier for t in scene.view_settings.bl_rna.properties['view_transform'].enum_items] else 'Filmic'
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes['Background']
    background.inputs[0].default_value = (0.52, 0.64, 0.82, 1)
    background.inputs[1].default_value = 0.045 if night else 0.9
    bpy.ops.object.light_add(type='SUN')
    sun = bpy.context.object
    sun.data.energy = 0.12 if night else 4.2
    sun.data.angle = math.radians(1.2)
    sun.data.color = (0.48, 0.62, 1.0) if night else (1.0, 0.95, 0.88)
    sun.rotation_euler = (math.radians(48), 0, math.radians(215))
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    scene.camera = camera
    camera.data.clip_end = 2000
    return camera


def set_emissive_time(night):
    """Preview the exported shader's time switch; no invented scene lights."""
    for mat in bpy.data.materials:
        props = getattr(mat, 'shader_properties', None)
        filename = getattr(props, 'filename', '') if props else ''
        if filename != 'emissivenight.sps' or not mat.use_nodes:
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'MIX_SHADER' and any(l.from_node.type == 'EMISSION' for l in node.inputs[1].links):
                node.inputs[0].default_value = 0.0 if night else 1.0


def clear_line_of_sight(eye, target, margin=1.5):
    """Pull the camera in front of anything between it and the subject.

    Camera positions are computed from the site, not from the map, so one can land
    inside a building and render black. A ray from the subject back towards the
    eye finds the first surface in the way; the camera stops short of it.
    """
    eye, target = Vector(eye), Vector(target)
    direction = eye - target
    distance = direction.length
    if distance < 1e-3:
        return eye
    direction.normalize()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    start = target + direction * 0.5
    hit, location, *_ = bpy.context.scene.ray_cast(depsgraph, start, direction, distance=distance - 0.5)
    if not hit:
        return eye
    clamped = (location - target).length - margin
    print('CAMERA_CLAMPED', round(distance, 1), '->', round(clamped, 1), flush=True)
    return target + direction * max(clamped, 2.0)


def aim(camera, eye, target, lens):
    eye = clear_line_of_sight(eye, target)
    camera.location = eye
    camera.data.lens = lens
    camera.rotation_euler = (Vector(target) - Vector(eye)).to_track_quat('-Z', 'Y').to_euler()


def render_plan(library, a):
    """Top-down orthographic view for choosing a site, with the pixel mapping saved.

    A plan shows at once what bounding boxes only hint at: where the facade runs,
    which ground is paved, and what already stands on a spot.
    """
    camera = lighting(a.size, a.samples)
    library.hide()
    scene = bpy.context.scene
    scene.render.resolution_x = a.size
    scene.render.resolution_y = a.size
    sx, sy, sz = (float(v) for v in a.site.split(','))
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = a.plan_span
    camera.location = (sx, sy, sz + max(150, a.plan_span * 2))
    camera.rotation_euler = (0, 0, 0)
    # Light from nearly overhead so a plan is not half in shadow.
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT':
            obj.rotation_euler = (math.radians(18), 0, math.radians(200))
    out = Path(a.out).resolve()
    path = out / 'plan.png'
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'plan-context.blend'))
    (out / 'plan.json').write_text(json.dumps({
        'image': str(path), 'centre': [sx, sy], 'span': a.plan_span,
        'pixels': a.size, 'note': 'x right = +X, up = +Y'}))
    import subprocess
    root = Path(__file__).resolve().parent.parent
    python = next((p for p in (root / '.venv/Scripts/python.exe', root / '.venv/bin/python')
                   if p.is_file()), None)
    if python is not None:
        command = [str(python), str(root / 'scripts/annotate-map-plan.py'),
                   '--report', str(out / 'plan.json')]
        if a.plan_markers:
            command.extend(['--markers', a.plan_markers])
        subprocess.run(command, check=True)
    else:
        print('GRID_PENDING: run scripts/annotate-map-plan.py --report', out / 'plan.json', flush=True)
    print('PLAN', path, flush=True)


def main():
    a = args()
    ensure_sollumz()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    if a.context_blend:
        bpy.ops.wm.open_mainfile(filepath=str(Path(a.context_blend).resolve()))
        for obj in list(bpy.data.objects):
            if obj.type in ('CAMERA', 'LIGHT'):
                bpy.data.objects.remove(obj, do_unlink=True)
    else:
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)

    context = json.loads(Path(a.context).read_text())
    context_assets = {x['model']: x for x in json.loads(Path(a.context_input).read_text())['assets']}
    build_assets = {}
    for path in a.ymap_input:
        for x in json.loads(Path(path).read_text())['assets']:
            build_assets[x['model']] = x
    by_hash = {jenkins(name): name for name in build_assets}

    library = Library()
    placed_context = len(bpy.data.collections['map_context'].objects) if a.context_blend else 0
    if not a.context_blend:
        # Do not reevaluate thousands of already placed collection instances on
        # every subsequent asset import. Reveal the complete context once loaded.
        target = bpy.data.collections.new('map_context')
        bpy.context.scene.collection.children.link(target)
        context_layer = bpy.context.view_layer.layer_collection.children[target.name]
        context_layer.exclude = True
        for ent in context['entities']:
            x, y, z, w = ent['rotation']
            if place(library, 'map_context', ent['archetype'], context_assets.get(ent['archetype']),
                     ent['position'], (w, x, y, z), ent['scale']):
                placed_context += 1
        context_layer.exclude = False

    if a.plan_only:
        render_plan(library, a)
        return

    library.hide()
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'before-context.blend'))

    removed_context = []
    for replacement in a.empty_replacement_ymap:
        if read_written_ymap(replacement):
            raise ValueError('--empty-replacement-ymap must contain no entities')
        owner = Path(replacement).name
        original_rows = [e for e in context['entities'] if e.get('ymap') == owner]
        for obj in bpy.data.collections['map_context'].objects:
            if any((obj.location-Vector(e['position'])).length < .02 and
                   obj.instance_collection and obj.instance_collection.name == 'lib_'+e['archetype']
                   for e in original_rows):
                removed_context.append(obj)
    written = read_written_ymap(a.ymap)
    resolved, unresolved = [], []
    for ent in written:
        name = ent['archetype']
        if name.lower().startswith('hash_'):
            name = by_hash.get(int(name[5:], 16), name)
        if name not in build_assets:
            unresolved.append(ent['archetype'])
            continue
        resolved.append((name, ent))

    camera = lighting(a.size, a.samples, a.night)
    library.hide()

    sx, sy, sz = (float(v) for v in a.site.split(','))
    site = Vector((sx, sy, sz))
    face = math.radians(a.facing)
    front = Vector((math.sin(face), -math.cos(face), 0))   # the build's local -Y
    side = Vector((math.cos(face), math.sin(face), 0))
    views = [
        ('street', site + front * 9.5 + side * 3.2 + Vector((0, 0, 1.65)), site + Vector((0, 0, 1.0)), 30),
        ('plaza', site + front * 12 - side * 16 + Vector((0, 0, 7.0)), site + Vector((0, 0, 1.2)), 34),
        ('overview', site + front * 38 + side * 18 + Vector((0, 0, 30)), site + Vector((0, 0, 4)), 32),
    ]
    if a.views:
        views = [(v['name'], Vector(v['eye']), Vector(v['target']), v.get('lens',35))
                 for v in json.loads(Path(a.views).read_text())]
    # Resolve camera occlusion once against the before scene so pairs share a camera.
    views = [(name, clear_line_of_sight(eye,target), target,lens) for name,eye,target,lens in views]

    after = bpy.data.collections.new('ymap_build')
    bpy.context.scene.collection.children.link(after)
    after_layer = bpy.context.view_layer.layer_collection.children[after.name]

    def render(tag):
        set_emissive_time(a.night)
        for view, eye, target, lens in views:
            camera.location = eye
            camera.data.lens = lens
            camera.rotation_euler = (Vector(target)-Vector(eye)).to_track_quat('-Z','Y').to_euler()
            path = out / ('%s-%s.png' % (view, tag))
            bpy.context.scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            print('VIEW', path, flush=True)

    after_layer.exclude = True
    render('before')
    after_layer.exclude = False
    for obj in removed_context:
        obj.hide_render = True
    placed_build = 0
    for name, ent in resolved:
        if place(library, 'ymap_build', name, build_assets[name], ent['position'],
                 ent['rotation'], ent['scale']):
            placed_build += 1
    library.hide()
    render('after')

    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'map-context.blend'))
    (out / 'sollumz-read.json').write_text(json.dumps(written, indent=2))
    (out / 'render-report.json').write_text(json.dumps({
        'contextEntities':len(context['entities']), 'contextPlaced':placed_context,
        'ymapEntitiesRead':len(written), 'buildPlaced':placed_build,
        'unresolved':unresolved, 'libraryFailures':library.failed, 'night':a.night,
        'removedContextEntities':len(removed_context),
        'views':[{'name':n,'eye':list(e),'target':list(t),'lens':l} for n,e,t,l in views]},indent=2))
    print('CONTEXT_DONE', json.dumps({
        'contextEntities': len(context['entities']), 'contextPlaced': placed_context,
        'ymapEntitiesRead': len(written), 'buildPlaced': placed_build,
        'unresolved': unresolved, 'libraryFailures': library.failed}), flush=True)


if __name__ == '__main__':
    main()
