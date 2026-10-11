#!/usr/bin/env python3
"""Turn the stock Prairie into an LSPD patrol car.

blender -b --python examples/build_police_prairie.py -- --input INPUT.json --out DIR

Reads the batch `gtav-scout-extract extract --drawable prairie --drawable police`
writes, imports the Prairie through Sollumz, repaints it in the black-and-white
LSPD scheme, applies the game's own door decal sheet, builds a roof lightbar from
new geometry, and saves an editable .blend beside rendered views.

Nothing here is invented about the game: the decal and badge textures are the
ones the police vehicle itself ships with, and the paint colours are applied to
the material slots Sollumz marks [PRIMARY], which is where a vehicle's body
colour goes.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

BLACK = (0.020, 0.021, 0.024, 1.0)
WHITE = (0.780, 0.790, 0.800, 1.0)
# Doors and front wings carry the white panels of the classic black-and-white car.
WHITE_PANELS = ('door_dside_f', 'door_pside_f', 'door_dside_r', 'door_pside_r')


def ensure_sollumz():
    if hasattr(bpy.types, 'SOLLUMZ_OT_import_assets'):
        return
    import addon_utils
    for module in [m.__name__ for m in addon_utils.modules() if 'sollumz' in m.__name__.lower()]:
        addon_utils.enable(module, default_set=False, persistent=True)
        if hasattr(bpy.types, 'SOLLUMZ_OT_import_assets'):
            return
    raise SystemExit('Sollumz is not available; see docs/blender-cli.md')


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for collection in (bpy.data.meshes, bpy.data.materials, bpy.data.images,
                       bpy.data.cameras, bpy.data.lights, bpy.data.armatures):
        for block in list(collection):
            if block.users == 0:
                collection.remove(block)


def import_vehicle(path):
    before = set(bpy.data.objects)
    path = Path(path).resolve()
    bpy.ops.sollumz.import_assets(directory=str(path.parent), files=[{'name': path.name}])
    created = [o.name for o in bpy.data.objects if o not in before]
    keep, drop = [], []
    for name in created:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        if obj.type == 'LIGHT':
            drop.append(name)
        elif obj.type == 'MESH' and obj.data and len(obj.data.vertices):
            target = keep if str(getattr(obj, 'sollum_type', '')) == 'sollumz_drawable_model' else drop
            target.append(name)
    for name in drop:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
    return [bpy.data.objects[n] for n in keep if n in bpy.data.objects]


def paint(name, colour, roughness=0.25, metallic=0.55):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = colour
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic
    return material


def emissive(name, colour, strength=12.0):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = colour
    bsdf.inputs['Roughness'].default_value = 0.1
    bsdf.inputs['Emission Color'].default_value = colour
    bsdf.inputs['Emission Strength'].default_value = strength
    return material


def decal_material(name, texture_path):
    """Alpha-blended decal using the game's own signage sheet."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = nodes['Principled BSDF']
    bsdf.inputs['Roughness'].default_value = 0.35
    image = nodes.new('ShaderNodeTexImage')
    image.image = bpy.data.images.load(str(texture_path), check_existing=True)
    image.interpolation = 'Closest'
    mapping = nodes.new('ShaderNodeMapping')
    coords = nodes.new('ShaderNodeTexCoord')
    links.new(coords.outputs['UV'], mapping.inputs['Vector'])
    links.new(mapping.outputs['Vector'], image.inputs['Vector'])
    links.new(image.outputs['Color'], bsdf.inputs['Base Color'])
    return material, mapping


def repaint(meshes, black, white):
    """Swap the body-colour slots for the livery, leaving glass and trim alone."""
    repainted = 0
    for obj in meshes:
        wants_white = any(obj.name.lower().startswith(p) for p in WHITE_PANELS)
        for slot in obj.material_slots:
            if slot.material is None or '[PRIMARY]' not in slot.material.name:
                continue
            slot.material = white if wants_white else black
            repainted += 1
    return repainted


def add_wheels(meshes, collection):
    """Give the car four wheels.

    A vehicle drawable ships one visual wheel; the game instances the rest onto
    bones at runtime, so an imported car stands on a single tyre. The four hub
    meshes are present though, and their centres are exactly where the wheels
    belong, so the visual wheel is copied onto each and mirrored for the right side.
    """
    source = next((o for o in meshes if o.name.lower().startswith('wheel_lf')), None)
    if source is None:
        return []
    origin, _ = bounds([source])
    _, source_high = bounds([source])
    source_centre = (origin + source_high) / 2

    made = []
    for corner in ('lf', 'lr', 'rf', 'rr'):
        hub = next((o for o in meshes if o.name.lower() == 'hub_' + corner), None)
        if hub is None:
            continue
        low, high = bounds([hub])
        target = (low + high) / 2
        if corner == 'lf':
            continue  # already in place
        copy = source.copy()
        copy.data = source.data.copy()
        copy.name = 'wheel_%s_visual' % corner
        collection.objects.link(copy)
        if corner.startswith('r'):
            copy.scale.x = -1
        copy.location = copy.location + (target - source_centre)
        made.append(copy)
    return made


def roof_peak(meshes):
    """World point at the top of the cabin, used to seat the lightbar."""
    shell = [o for o in meshes if o.name.lower() in ('bodyshell', 'chassis')] or meshes
    best = None
    for obj in shell:
        matrix = obj.matrix_world
        for vertex in obj.data.vertices:
            point = matrix @ vertex.co
            if best is None or point.z > best.z:
                best = point
    return best


def bounds(objects):
    points = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    return low, high


def build_lightbar(roof_centre, width, collection):
    """A low-profile bar of alternating red and blue lenses on a dark housing."""
    parts = []
    bpy.ops.mesh.primitive_cube_add(size=1, location=roof_centre + Vector((0, 0, 0.035)))
    housing = bpy.context.object
    housing.name = 'lspd_lightbar_housing'
    housing.scale = (width * 0.5, 0.11, 0.035)
    bpy.ops.object.transform_apply(scale=True)
    bevel = housing.modifiers.new('bevel', 'BEVEL')
    bevel.width = 0.012
    bevel.segments = 3
    housing.data.materials.append(paint('lspd_lightbar_shell', (0.02, 0.02, 0.02, 1), 0.35, 0.4))
    parts.append(housing)

    red = emissive('lspd_lens_red', (0.85, 0.03, 0.03, 1))
    blue = emissive('lspd_lens_blue', (0.03, 0.10, 0.90, 1))
    segments = 6
    span = width * 0.86
    for index in range(segments):
        offset = -span / 2 + span * (index + 0.5) / segments
        bpy.ops.mesh.primitive_cube_add(
            size=1, location=roof_centre + Vector((offset, 0, 0.078)))
        lens = bpy.context.object
        lens.name = 'lspd_lightbar_lens_%d' % (index + 1)
        lens.scale = (span / segments * 0.42, 0.085, 0.026)
        bpy.ops.object.transform_apply(scale=True)
        lens.data.materials.append(red if index % 2 == 0 else blue)
        parts.append(lens)

    # Two short feet so the bar reads as mounted rather than floating.
    for side in (-1, 1):
        bpy.ops.mesh.primitive_cube_add(
            size=1, location=roof_centre + Vector((side * width * 0.30, 0, -0.01)))
        foot = bpy.context.object
        foot.name = 'lspd_lightbar_foot_%s' % ('l' if side < 0 else 'r')
        foot.scale = (0.10, 0.09, 0.03)
        bpy.ops.object.transform_apply(scale=True)
        foot.data.materials.append(bpy.data.materials['lspd_lightbar_shell'])
        parts.append(foot)

    for part in parts:
        for existing in list(part.users_collection):
            existing.objects.unlink(part)
        collection.objects.link(part)
    return parts


def build_door_decals(meshes, texture_path, collection):
    """Place the game's LSPD door sheet on both front doors."""
    doors = [o for o in meshes if o.name.lower().startswith(('door_dside_f', 'door_pside_f'))]
    made = []
    for door in doors:
        low, high = bounds([door])
        centre = (low + high) / 2
        outward = 1 if centre.x > 0 else -1
        bpy.ops.mesh.primitive_plane_add(size=1)
        decal = bpy.context.object
        decal.name = 'lspd_door_decal_%s' % ('r' if outward > 0 else 'l')
        decal.rotation_euler = (math.radians(90), 0, math.radians(90 * outward))
        decal.scale = (0.92, 0.46, 1.0)
        bpy.ops.object.transform_apply(scale=True)
        decal.location = Vector((high.x + 0.012 if outward > 0 else low.x - 0.012,
                                 centre.y, centre.z - 0.06))
        material, mapping = decal_material('lspd_door_sign_%s' % decal.name[-1], texture_path)
        # Frame the badge and lettering band rather than the whole sheet.
        mapping.inputs['Location'].default_value = (0.02, 0.05, 0.0)
        mapping.inputs['Scale'].default_value = (1.0, 0.62, 1.0)
        decal.data.materials.append(material)
        for existing in list(decal.users_collection):
            existing.objects.unlink(decal)
        collection.objects.link(decal)
        made.append(decal)
    return made


def studio(objects, size, samples):
    low, high = bounds(objects)
    centre = (low + high) / 2
    radius = max((Vector(p) - centre).length
                 for p in [low, high, Vector((low.x, high.y, low.z)), Vector((high.x, low.y, high.z))])

    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x = size
    scene.render.resolution_y = int(size * 0.72)
    scene.render.image_settings.file_format = 'PNG'
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (0.22, 0.23, 0.25, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = 1.0
    scene.view_settings.view_transform = 'Filmic'

    bpy.ops.mesh.primitive_plane_add(size=radius * 20, location=(centre.x, centre.y, low.z))
    ground = bpy.context.object
    ground.name = 'studio_ground'
    ground.data.materials.append(paint('studio_ground', (0.10, 0.10, 0.11, 1), 0.6, 0.0))

    for offset, energy, sun_size in (((1, -1, 1.4), 5.0, 0.03), ((-1.2, 0.8, 1.0), 2.0, 0.2)):
        bpy.ops.object.light_add(type='SUN', location=centre + Vector(offset) * radius * 3)
        light = bpy.context.object
        light.data.energy = energy
        light.data.angle = sun_size
        light.rotation_euler = (centre - light.location).to_track_quat('-Z', 'Y').to_euler()

    bpy.ops.object.camera_add()
    camera = bpy.context.object
    scene.camera = camera
    camera.data.lens = 62
    return centre, radius, camera


def render_views(centre, radius, camera, out, views, size, samples):
    written = []
    for name, azimuth, elevation, distance in views:
        angle, tilt = math.radians(azimuth), math.radians(elevation)
        camera.location = centre + Vector((
            math.cos(angle) * math.cos(tilt),
            math.sin(angle) * math.cos(tilt),
            math.sin(tilt))) * radius * distance
        camera.rotation_euler = (centre - camera.location).to_track_quat('-Z', 'Y').to_euler()
        path = out / ('%s.png' % name)
        bpy.context.scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        written.append(path)
        print('VIEW', path, flush=True)
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--size', type=int, default=1100)
    parser.add_argument('--samples', type=int, default=96)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])

    ensure_sollumz()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    assets = {a['model']: a for a in json.loads(Path(args.input).read_text())['assets']}

    clear_scene()
    build = bpy.data.collections.new('lspd_prairie')
    bpy.context.scene.collection.children.link(build)

    body = import_vehicle(assets['prairie']['drawable'])
    black = paint('lspd_body_black', BLACK, 0.22, 0.6)
    white = paint('lspd_body_white', WHITE, 0.28, 0.35)
    repainted = repaint(body, black, white)

    wheels = add_wheels(body, build)

    low, high = bounds(body)
    peak = roof_peak(body)
    roof = Vector((0.0, peak.y, high.z))
    bar = build_lightbar(roof, (high.x - low.x) * 0.74, build)

    sheet = assets['police']['textures'].get('policenew_sign_1')
    decals = build_door_decals(body, sheet, build) if sheet else []

    everything = body + wheels + bar + decals
    centre, radius, camera = studio(everything, args.size, args.samples)

    blend = out / 'lspd_prairie.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    print('BLEND', blend, flush=True)

    views = [('lspd-prairie-front-quarter', 55, 16, 2.6),
             ('lspd-prairie-rear-quarter', 215, 18, 2.6),
             ('lspd-prairie-side', 180, 6, 2.7),
             ('lspd-prairie-top', 90, 62, 2.4)]
    render_views(centre, radius, camera, out, views, args.size, args.samples)

    print('BUILD_DONE', json.dumps({
        'bodyMeshes': len(body), 'repaintedSlots': repainted, 'wheelsAdded': len(wheels),
        'lightbarParts': len(bar), 'decals': len(decals), 'blend': str(blend)}), flush=True)


if __name__ == '__main__':
    main()
