#!/usr/bin/env python3
"""Assemble a Los Santos street-food stand from game props plus new geometry.

blender -b --python examples/build_street_food_stand.py -- --input INPUT.json --out DIR

Reads the batch `gtav-scout-extract extract` writes for the chosen props, imports
each through Sollumz, arranges them into a corner food stand, builds the canopy
frame, counter skirt and signboard as new geometry, and saves an editable .blend
beside rendered views.

Every prop was chosen by looking at its rendered preview, not at its name: the
counter is a trestle table on milk crates, the cooker is a vertical kebab grill,
and the awning strip is the market canopy valance.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

SIGN_TOP = 'LOS SANTOS'
SIGN_BOTTOM = 'STREET EATS'

# name, (x, y, z) of the footprint centre, z rotation in degrees, sit-on-ground,
# optional uniform scale for matching a prop to the built frame
LAYOUT = [
    ('prop_protest_table_01', (-0.80, 0.00, 0.00), 0, True),
    ('prop_protest_table_01', (0.80, 0.00, 0.00), 0, True),
    ('prop_kebab_grill', (1.95, 0.35, 0.00), 235, True),
    ('prop_bbq_4_l1', (-1.70, 0.95, 0.00), 0, True),
    ('v_med_cooler', (0.15, 1.25, 0.00), 180, True),
    ('prop_box_wood05a', (-2.05, 1.60, 0.00), 12, True),
    ('hei_prop_heist_wooden_box', (-2.05, 1.60, 0.90), -8, False),
    ('hei_prop_heist_wooden_box', (2.05, 1.55, 0.00), 20, True),
    ('v_ret_247_fruit', (-1.05, 0.02, 0.73), 0, False),
    ('prop_food_tray_02', (0.35, -0.10, 0.73), -14, False),
    ('prop_food_tray_02', (0.95, 0.05, 0.73), 8, False),
    ('sf_prop_sf_chair_stool_09a', (-0.55, -1.15, 0.00), 165, True),
    ('sf_prop_sf_chair_stool_09a', (0.70, -1.20, 0.00), 195, True),
    ('cs1_06_market_canopy_03', (0.00, -1.90, 2.26), 0, False, 1.75),
]

POSTS = [(-2.35, -1.45), (2.35, -1.45), (-2.35, 1.85), (2.35, 1.85)]
POST_HEIGHT = 2.45


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
                       bpy.data.cameras, bpy.data.lights, bpy.data.armatures,
                       bpy.data.curves):
        for block in list(collection):
            if block.users == 0:
                collection.remove(block)


def bounds(objects):
    points = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    return low, high


def import_prop(asset, textures):
    """Import one drawable and bind its decoded textures, as the renderer does."""
    path = Path(asset['drawable']).resolve()
    before = set(bpy.data.objects)
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
    meshes = [bpy.data.objects[n] for n in keep if n in bpy.data.objects]

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
                    node.interpolation = 'Closest'
    return meshes


def place(meshes, position, degrees, on_ground, collection, scale=1.0):
    """Move a prop so its footprint centre lands on `position`.

    Props arrive at their own game-space origin, which is rarely the base of the
    object, so placing by bounding box rather than by origin is what makes a
    layout predictable.
    """
    empty = bpy.data.objects.new('prop_root', None)
    collection.objects.link(empty)
    for obj in meshes:
        obj.parent = empty
        obj.matrix_parent_inverse = empty.matrix_world.inverted()
        for existing in list(obj.users_collection):
            existing.objects.unlink(obj)
        collection.objects.link(obj)

    empty.rotation_euler = (0, 0, math.radians(degrees))
    empty.scale = (scale, scale, scale)
    bpy.context.view_layer.update()

    low, high = bounds(meshes)
    centre = (low + high) / 2
    anchor = Vector((centre.x, centre.y, low.z if on_ground else low.z))
    empty.location = empty.location + (Vector(position) - anchor)
    bpy.context.view_layer.update()
    return empty


def material(name, colour, roughness=0.6, metallic=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = colour
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic
    return mat


def emissive(name, colour, strength=6.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = colour
    bsdf.inputs['Emission Color'].default_value = colour
    bsdf.inputs['Emission Strength'].default_value = strength
    return mat


def build_canopy(collection):
    """Posts, a beam frame and a striped fabric roof — all new geometry."""
    made = []
    steel = material('stand_steel', (0.30, 0.31, 0.33, 1), 0.4, 0.8)
    for index, (x, y) in enumerate(POSTS):
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.045, depth=POST_HEIGHT, vertices=16,
            location=(x, y, POST_HEIGHT / 2))
        post = bpy.context.object
        post.name = 'stand_post_%d' % (index + 1)
        post.data.materials.append(steel)
        made.append(post)

    for y in (-1.45, 1.85):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, y, POST_HEIGHT - 0.06))
        beam = bpy.context.object
        beam.name = 'stand_beam_%s' % ('front' if y < 0 else 'back')
        beam.scale = (4.78, 0.07, 0.07)
        bpy.ops.object.transform_apply(scale=True)
        beam.data.materials.append(steel)
        made.append(beam)

    # Roof: a shallow gable so it reads as fabric stretched over the frame.
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0.22, POST_HEIGHT + 0.12))
    roof = bpy.context.object
    roof.name = 'stand_canopy_roof'
    roof.scale = (5.02, 3.44, 0.05)
    bpy.ops.object.transform_apply(scale=True)
    roof.rotation_euler = (math.radians(-4), 0, 0)
    canvas = material('stand_canvas', (0.34, 0.055, 0.05, 1), 0.85, 0.0)
    roof.data.materials.append(canvas)
    made.append(roof)

    for part in made:
        for existing in list(part.users_collection):
            existing.objects.unlink(part)
        collection.objects.link(part)
    return made


def build_sign(collection):
    """A lit signboard hung from the front beam, with extruded lettering."""
    made = []
    board_y, board_z = -1.60, POST_HEIGHT - 0.62
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, board_y, board_z))
    board = bpy.context.object
    board.name = 'stand_signboard'
    board.scale = (2.60, 0.06, 0.62)
    bpy.ops.object.transform_apply(scale=True)
    board.data.materials.append(material('stand_sign_panel', (0.055, 0.06, 0.075, 1), 0.5))
    made.append(board)

    frame = material('stand_sign_frame', (0.78, 0.62, 0.20, 1), 0.35, 0.9)
    for z in (board_z + 0.335, board_z - 0.335):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, board_y, z))
        rail = bpy.context.object
        rail.name = 'stand_sign_rail'
        rail.scale = (2.64, 0.075, 0.05)
        bpy.ops.object.transform_apply(scale=True)
        rail.data.materials.append(frame)
        made.append(rail)

    letters = emissive('stand_sign_text', (1.0, 0.86, 0.42, 1), 7.0)
    accent = emissive('stand_sign_text_accent', (1.0, 0.45, 0.16, 1), 7.0)
    for text, z, size, mat in ((SIGN_TOP, board_z + 0.15, 0.24, letters),
                               (SIGN_BOTTOM, board_z - 0.20, 0.30, accent)):
        bpy.ops.object.text_add(location=(0, board_y - 0.05, z))
        body = bpy.context.object
        body.name = 'stand_sign_%s' % text.split()[0].lower()
        body.data.body = text
        body.data.size = size
        body.data.align_x = 'CENTER'
        body.data.align_y = 'CENTER'
        body.data.extrude = 0.012
        body.rotation_euler = (math.radians(90), 0, 0)
        body.data.materials.append(mat)
        made.append(body)

    # Two small lamps so the board reads as lit rather than glowing on its own.
    for x in (-1.5, 1.5):
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.07, depth=0.16, vertices=12,
            location=(x, board_y - 0.16, board_z + 0.44))
        lamp = bpy.context.object
        lamp.name = 'stand_sign_lamp'
        lamp.rotation_euler = (math.radians(58), 0, 0)
        lamp.data.materials.append(emissive('stand_lamp_glow', (1.0, 0.93, 0.78, 1), 24.0))
        made.append(lamp)

    for part in made:
        for existing in list(part.users_collection):
            existing.objects.unlink(part)
        collection.objects.link(part)
    return made


def build_counter_skirt(collection):
    """A painted board closing the front of the trestle counter."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -0.42, 0.34))
    skirt = bpy.context.object
    skirt.name = 'stand_counter_skirt'
    skirt.scale = (3.15, 0.05, 0.66)
    bpy.ops.object.transform_apply(scale=True)
    skirt.data.materials.append(material('stand_skirt_paint', (0.33, 0.07, 0.065, 1), 0.7))
    for existing in list(skirt.users_collection):
        existing.objects.unlink(skirt)
    collection.objects.link(skirt)
    return [skirt]


def build_ground(collection, radius):
    bpy.ops.mesh.primitive_plane_add(size=radius * 8, location=(0, 0, 0))
    ground = bpy.context.object
    ground.name = 'stand_ground'
    ground.data.materials.append(material('stand_asphalt', (0.075, 0.076, 0.080, 1), 0.85))
    for existing in list(ground.users_collection):
        existing.objects.unlink(ground)
    collection.objects.link(ground)
    return ground


def studio(objects, size, samples):
    low, high = bounds(objects)
    centre = (low + high) / 2
    radius = (high - low).length / 2

    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x = size
    scene.render.resolution_y = int(size * 0.68)
    scene.render.image_settings.file_format = 'PNG'
    scene.world.use_nodes = True
    # Dusk sky, so the sign and lamps carry the scene.
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (0.045, 0.055, 0.085, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = 1.0
    scene.view_settings.view_transform = 'Filmic'

    bpy.ops.object.light_add(type='AREA', location=(centre.x + 2.0, centre.y - 2.6, centre.z + 2.8))
    key = bpy.context.object
    key.data.energy = 620
    key.data.size = 3.0
    key.data.color = (1.0, 0.88, 0.72)
    key.rotation_euler = (centre - key.location).to_track_quat('-Z', 'Y').to_euler()

    bpy.ops.object.light_add(type='AREA', location=(centre.x - 3.2, centre.y + 1.4, centre.z + 2.2))
    fill = bpy.context.object
    fill.data.energy = 260
    fill.data.size = 4.0
    fill.data.color = (0.62, 0.72, 1.0)
    fill.rotation_euler = (centre - fill.location).to_track_quat('-Z', 'Y').to_euler()

    bpy.ops.object.camera_add()
    camera = bpy.context.object
    scene.camera = camera
    camera.data.lens = 44
    return centre, radius, camera


def render_views(centre, radius, camera, out, views):
    for name, azimuth, elevation, distance, height in views:
        angle, tilt = math.radians(azimuth), math.radians(elevation)
        camera.location = Vector((
            centre.x + math.cos(angle) * math.cos(tilt) * radius * distance,
            centre.y + math.sin(angle) * math.cos(tilt) * radius * distance,
            centre.z + math.sin(tilt) * radius * distance * height))
        target = Vector((centre.x, centre.y, centre.z * 0.86))
        camera.rotation_euler = (target - camera.location).to_track_quat('-Z', 'Y').to_euler()
        path = out / ('%s.png' % name)
        bpy.context.scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        print('VIEW', path, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--size', type=int, default=1200)
    parser.add_argument('--samples', type=int, default=110)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])

    ensure_sollumz()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    assets = {a['model']: a for a in json.loads(Path(args.input).read_text())['assets']}

    clear_scene()
    stand = bpy.data.collections.new('street_food_stand')
    bpy.context.scene.collection.children.link(stand)

    placed, missing = [], []
    for entry in LAYOUT:
        name, position, degrees, on_ground = entry[:4]
        scale = entry[4] if len(entry) > 4 else 1.0
        asset = assets.get(name)
        if asset is None:
            missing.append(name)
            continue
        meshes = import_prop(asset, asset.get('textures', {}))
        if not meshes:
            missing.append(name)
            continue
        place(meshes, position, degrees, on_ground, stand, scale)
        placed.extend(meshes)

    built = build_canopy(stand) + build_sign(stand) + build_counter_skirt(stand)
    subject = placed + built
    low, high = bounds(subject)
    build_ground(stand, (high - low).length)

    centre, radius, camera = studio(subject, args.size, args.samples)

    blend = out / 'street_food_stand.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    print('BLEND', blend, flush=True)

    render_views(centre, radius, camera, out, [
        ('street-food-stand-hero', 252, 7, 2.45, 1.0),
        ('street-food-stand-counter', 288, 5, 1.85, 1.0),
        ('street-food-stand-side', 198, 7, 2.3, 1.0),
        ('street-food-stand-above', 250, 34, 2.2, 1.0),
    ])

    print('BUILD_DONE', json.dumps({
        'propsPlaced': len(LAYOUT) - len(missing), 'propMeshes': len(placed),
        'newGeometry': len(built), 'missing': missing, 'blend': str(blend)}), flush=True)


if __name__ == '__main__':
    main()
