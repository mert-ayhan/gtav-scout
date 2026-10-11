#!/usr/bin/env python3
"""Export new geometry from a build .blend as one custom GTA V drawable (.ydr).

blender -b --python examples/export_custom_drawable.py -- \
    --blend BUILD.blend --prefix stand_ --exclude stand_ground \
    --name gs_stand_frame --out DIR

Takes every object whose name starts with --prefix (game props imported through
Sollumz are left alone — the ymap places those by name), turns text into mesh,
gives every material a real texture, joins the result into one mesh and converts
it with Sollumz into a drawable whose textures are embedded. The mesh keeps the
build's origin, so the drawable's origin is the build's ground centre and a ymap
entity placed at the site puts it exactly where it was designed.

Sollumz maps a material's Base Colour image to DiffuseSampler; a flat colour with
no image would export as a missing texture, so each colour becomes a small PNG.
"""
import argparse
import sys
from pathlib import Path

import bpy


def args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blend', required=True)
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--exclude', action='append', default=[])
    parser.add_argument('--name', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--collision', action='store_true',
                        help='Embed a collision bound built from the same mesh')
    parser.add_argument('--collision-material', default='METAL_SOLID_MEDIUM',
                        help='GTA collision material for the embedded bound, e.g. CONCRETE')
    parser.add_argument('--collision-prefix',
                        help='Separate simplified collision meshes; their material names must be '
                             'GTA collision material names. Unknown names fail the export.')
    parser.add_argument('--emissive', default='',
                        help='Shader for materials that glow in the build, e.g. emissivenight.sps '
                             '(lit at night, as GTA signs are) or emissive.sps (always lit)')
    parser.add_argument('--emissive-strength', type=float, default=4.0)
    return parser.parse_args(sys.argv[sys.argv.index('--') + 1:])


def ensure_sollumz():
    if hasattr(bpy.types, 'SOLLUMZ_OT_import_assets'):
        return
    import addon_utils
    for module in [m.__name__ for m in addon_utils.modules() if 'sollumz' in m.__name__.lower()]:
        addon_utils.enable(module, default_set=False, persistent=True)
        if hasattr(bpy.types, 'SOLLUMZ_OT_import_assets'):
            return
    raise SystemExit('Sollumz is not available; see docs/blender-cli.md')


def select_only(objects, active=None):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active or (objects[0] if objects else None)


def material_colour(material):
    """The colour a flat material shows: its emission if it glows, else its base."""
    if not material or not material.use_nodes:
        return (0.5, 0.5, 0.5, 1.0), False
    bsdf = material.node_tree.nodes.get('Principled BSDF')
    if bsdf is None:
        return (0.5, 0.5, 0.5, 1.0), False
    strength = bsdf.inputs['Emission Strength'].default_value
    if strength > 0.5:
        return tuple(bsdf.inputs['Emission Color'].default_value), True
    return tuple(bsdf.inputs['Base Color'].default_value), False


def write_dds(path, colour, size=8):
    """An uncompressed 32-bit A8R8G8B8 DDS of one solid colour.

    Sollumz embeds only DDS images, and Blender cannot write DDS. The uncompressed
    layout is a fixed 128-byte header followed by raw BGRA pixels, so it is written
    directly rather than pulling in a converter.
    """
    import struct
    def srgb(c):  # material colours are linear; texture bytes are sRGB
        c = max(0.0, min(1.0, c))
        return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    r, g, b = (round(srgb(c) * 255) for c in colour[:3])
    header = struct.pack('<4sIIIIIII44sIIIIIIIIIIIII',
                         b'DDS ', 124,
                         0x1 | 0x2 | 0x4 | 0x1000 | 0x8,     # CAPS|HEIGHT|WIDTH|PIXELFORMAT|PITCH
                         size, size, size * 4, 0, 1, bytes(44),
                         32, 0x41, 0, 32,                     # pixel format: RGB | ALPHAPIXELS
                         0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000,
                         0x1000, 0, 0, 0, 0)                  # caps: TEXTURE
    pixel = bytes((b, g, r, 255))
    path.write_bytes(header + pixel * (size * size))


def textured_material(source, texture_dir):
    """A copy of `source` whose Base Colour comes from a small solid-colour texture."""
    colour, glows = material_colour(source)
    name = 'gs_' + source.name.replace('.', '_')
    path = texture_dir / (name + '.dds')
    write_dds(path, colour)
    image = bpy.data.images.load(str(path), check_existing=True)
    image.name = name

    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = nodes['Principled BSDF']
    node = nodes.new('ShaderNodeTexImage')
    node.image = image
    links.new(node.outputs['Color'], bsdf.inputs['Base Color'])
    return material, glows


def main():
    a = args()
    out = Path(a.out).resolve()
    texture_dir = out / 'textures'
    texture_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.open_mainfile(filepath=str(Path(a.blend).resolve()))
    ensure_sollumz()
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    parts = [o for o in bpy.data.objects
             if o.name.startswith(a.prefix) and o.name not in a.exclude
             and not (a.collision_prefix and o.name.startswith(a.collision_prefix))
             and o.type in ('MESH', 'CURVE', 'FONT')]
    collision_parts = [o for o in bpy.data.objects if a.collision_prefix
                       and o.name.startswith(a.collision_prefix) and o.type == 'MESH']
    if a.collision_prefix and not collision_parts:
        raise SystemExit('No simplified collision meshes match --collision-prefix')
    if not parts:
        raise SystemExit('No objects start with %r' % a.prefix)

    # Text, curves and modifiers become plain mesh, in world space around the origin.
    for obj in parts:
        obj.parent = None
    select_only(parts)
    bpy.ops.object.convert(target='MESH')
    parts = [o for o in bpy.context.selected_objects if o.type == 'MESH']
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    replaced, glowing = {}, []
    for obj in parts:
        # Sollumz exports the channels its shaders read by fixed names: UV map
        # "UVMap 0" and vertex colours "Color 1". GTA uses vertex colour for baked
        # lighting, so it is filled white (fully lit) rather than left absent.
        uv = obj.data.uv_layers[0] if obj.data.uv_layers else obj.data.uv_layers.new()
        uv.name = 'UVMap 0'
        for extra in list(obj.data.uv_layers)[1:]:
            obj.data.uv_layers.remove(extra)
        colours = obj.data.color_attributes.get('Color 1') or obj.data.color_attributes.new(
            name='Color 1', type='BYTE_COLOR', domain='CORNER')
        for item in colours.data:
            item.color = (1.0, 1.0, 1.0, 1.0)
        for slot in obj.material_slots:
            source = slot.material
            if source is None:
                continue
            if source.name not in replaced:
                replaced[source.name] = textured_material(source, texture_dir)
            material, glows = replaced[source.name]
            slot.material = material
            if glows:
                glowing.append(material.name)

    select_only(parts, parts[0])
    bpy.ops.object.join()
    mesh = bpy.context.view_layer.objects.active
    mesh.name = a.name + '_model'

    # The build scene also holds the imported game props, including their leftover
    # Sollumz drawable roots. Reduce it to this one mesh before converting, so the
    # drawable Sollumz creates is the only one and nothing else can be exported.
    keep_names = {mesh.name} | {o.name for o in collision_parts}
    for name in [o.name for o in bpy.data.objects if o.name not in keep_names]:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)

    scene = bpy.context.scene
    scene.center_drawable_to_selection = False     # keep the build's origin
    scene.create_seperate_drawables = False
    scene.auto_create_embedded_col = bool(a.collision and not a.collision_prefix)

    select_only([mesh])
    bpy.ops.sollumz.converttodrawable()
    drawables = [o for o in bpy.data.objects
                 if str(getattr(o, 'sollum_type', '')) == 'sollumz_drawable']
    if len(drawables) != 1:
        raise SystemExit('Expected one drawable after conversion, found %d' % len(drawables))
    drawable = drawables[0]
    drawable.name = a.name

    models = [o for o in bpy.data.objects
              if str(getattr(o, 'sollum_type', '')) == 'sollumz_drawable_model']
    select_only(models)
    bpy.ops.sollumz.autoconvertmaterials()

    # Sollumz builds the embedded bound from a copy of the visual mesh and leaves the
    # visual materials on it, which it then refuses to export ("only collision
    # materials are supported"). Give the bound one real collision material instead.
    collision = []
    if collision_parts:
        import importlib
        ybn = importlib.import_module('bl_ext.user_default.sollumz.ybn.collision_materials')
        helper = importlib.import_module('bl_ext.user_default.sollumz.tools.boundhelper')
        types = importlib.import_module('bl_ext.user_default.sollumz.sollumz_properties')
        names = [m.name for m in ybn.collisionmats]
        mapped = {}
        for obj in collision_parts:
            obj.hide_set(False)
            obj.hide_render = False
            if not obj.data.materials:
                raise SystemExit('Collision mesh has no material: ' + obj.name)
            for slot in obj.material_slots:
                key = slot.material.name.split('.')[0] if slot.material else ''
                if key not in names:
                    raise SystemExit('Unknown GTA collision material: ' + key)
                if key not in mapped:
                    mapped[key] = ybn.create_collision_material_from_index(names.index(key))
                slot.material = mapped[key]
        select_only(collision_parts)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        bpy.ops.object.join()
        simplified = bpy.context.object
        composite = helper.convert_objs_to_single_composite(
            [simplified], types.SollumType.BOUND_GEOMETRYBVH, scene.sz_default_flag_preset_name)
        composite.parent = drawable
        collision.append(simplified.name)
    elif a.collision:
        import importlib
        ybn = importlib.import_module('bl_ext.user_default.sollumz.ybn.collision_materials')
        names = [m.name for m in ybn.collisionmats]
        index = names.index(a.collision_material) if a.collision_material in names else names.index('CONCRETE')
        solid = ybn.create_collision_material_from_index(index)
        for obj in drawable.children_recursive:
            if obj.type == 'MESH' and str(getattr(obj, 'sollum_type', '')).startswith('sollumz_bound'):
                obj.data.materials.clear()
                obj.data.materials.append(solid)
                collision.append(obj.name)

    # Auto-conversion makes every material default.sps, which does not glow. Put the
    # materials that glowed in the build onto an emissive shader, so a lit sign is
    # still lit in game rather than flat paint.
    emissive = []
    if a.emissive:
        import importlib
        converter = importlib.import_module(
            'bl_ext.user_default.sollumz.ydr.operators.materials').MaterialConverter
        for model in models:
            for slot in model.material_slots:
                material = slot.material
                if material is None or not any(material.name.startswith(g + '_') for g in glowing):
                    continue
                converted = converter(model, material).convert(a.emissive)
                node = converted.node_tree.nodes.get('emissiveMultiplier')
                if node is not None and hasattr(node, 'set'):
                    node.set(0, a.emissive_strength)
                emissive.append(converted.name)

    # Embed every texture in the drawable, so no separate .ytd has to travel with it.
    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and hasattr(node, 'texture_properties'):
                node.texture_properties.embedded = True

    select_only([drawable] + list(drawable.children_recursive))
    # The scene now holds only this drawable, so exporting everything is exact.
    result = bpy.ops.sollumz.export_assets(directory=str(out), direct_export=True,
                                           use_custom_settings=True, limit_to_selected=False)
    written = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.suffix in ('.ydr', '.ytd', '.ybn'))
    bpy.ops.wm.save_as_mainfile(filepath=str(out / (a.name + '.blend')))
    print('EXPORT_DONE', {'result': list(result), 'written': written,
                          'materials': len(replaced), 'glowing': glowing, 'emissive': emissive, 'collision': collision,
                          'triangles': sum(len(o.data.polygons) for o in drawable.children_recursive
                                           if o.type == 'MESH')}, flush=True)


if __name__ == '__main__':
    main()
