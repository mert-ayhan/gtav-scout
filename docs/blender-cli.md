# Blender preview workflow

## Building preview additions

`scripts/render-map-context.py --night` uses a dim cool environment and switches
imported `emissivenight.sps` surfaces on. It is a Blender approximation of the
shader's time switch, not an in-game lighting measurement. `--views FILE.json`
accepts a list of `{name, eye: [x,y,z], target: [x,y,z], lens}` camera definitions;
before and after use the same resolved camera positions. Plan renders also write
`plan-grid.png`; `--plan-markers FILE.json` accepts a list of `{name, polygon:
[[x,y],...]}` annotations.

`--context-blend FILE.blend` reuses a saved before scene to avoid importing the
same surrounding assets again. `--empty-replacement-ymap FILE.ymap` accepts a
replacement containing no entities, checks it through Sollumz, and hides its
original context entities only in the after views. It does not implement partial
map replacement; use it only when the entire original map has been emptied.

`examples/export_custom_drawable.py --collision-prefix col_` uses separate
simplified meshes instead of duplicating visual geometry. Each collision mesh
material must be named after a Sollumz GTA collision material, such as `CONCRETE`,
`TARMAC`, `GLASS_OPAQUE` or `METAL_SOLID_MEDIUM`. Faces retain their material
assignments through joining. An empty selection or unknown material is an error.
The bound is embedded in the drawable; confirm its tree and material indices with
`inspect`, and perform the in-game collision checks in `manual-verification.md`.

Previews are evidence for a human or agent to look at. A render that succeeded is
not a review, and a filename is not a description.

## Requirements

- Blender 4.2 or newer with [Sollumz](https://github.com/Sollumz/Sollumz) enabled.
  Sollumz is GPL-3 and is installed separately; it is not bundled here. Verified
  working with Sollumz 2.9.0 on Blender 5.2.1.
- A catalogue snapshot (see `docs/manual-verification.md`).
- `CODEWALKER_PATH` pointing at a built CodeWalker checkout.

Install Sollumz from its release zip. It needs Python dependencies of its own, and
until they are installed it registers a single operator — `install_dependencies` —
so an import will fail with "could not be found". Install, install its
dependencies, then save preferences so later sessions keep it enabled:

    blender -b --python-expr "
    import bpy, addon_utils
    bpy.ops.extensions.package_install_files(
        filepath=r'<PATH TO>\Sollumz.zip', repo='user_default', enable_on_install=True)
    for m in [x.__name__ for x in addon_utils.modules() if 'sollumz' in x.__name__.lower()]:
        addon_utils.enable(m, default_set=True, persistent=True)
    bpy.ops.sollumz.install_dependencies()
    bpy.ops.wm.save_userpref()"

Then verify in a *fresh* Blender, because the dependencies only take effect on
reload:

    blender -b --python-expr "
    import bpy
    print('READY', hasattr(bpy.types, 'SOLLUMZ_OT_import_assets'))"

`READY True` means it is usable. Checking `hasattr(bpy.ops.sollumz, ...)` instead
is useless: `bpy.ops.<name>` is a lazy proxy that answers yes for any name.

The renderer enables the add-on itself if preferences were not saved, but it cannot
install the dependencies for you.

## Extract, then render

    dotnet run -c Release --project tools/GtavScout.Extract -- extract \
      --asset-root "<EXPORT DIR>" --catalog-root output/gta5-source \
      --out output/gta5-extract --id prop_bench_01a --id prop_chair_01a

    blender -b --python scripts/render-asset-catalog-views.py -- \
      --input output/gta5-extract/input.json --output output/gta5-previews

Each asset gets four orthographic views at azimuths 45/135/225/315 and 25°
elevation. No front is inferred, because nothing in the archetype declares one.

## Statuses

- `ready` — four views with signal and every referenced texture bound.
- `placeholder_texture` — more than half the object's surface wears a Rockstar
  stand-in such as `prop_remove`, whose texture reads "PLEASE REPLACE PROP". The
  render is faithful to the files; the asset is unfinished in this game build, so
  the picture is not evidence of how the object looks. `placeholderTextureShare`
  and `placeholderTextures` give the detail.
- `incomplete_textures` — rendered, but some textures were missing. The untextured
  areas are not material evidence. `missingTextures` names what was not found.
- `low_signal_render` — all four views are nearly uniform. May be effect geometry
  or a thin object. Needs a human look, not automatic rejection.
- `blank_render` — all four views are uniform. No visual evidence at all.
- `failed` — read `error` and `traceback`.

## Geometry

Fragments (`.yft`) bring their physics bounds in as meshes, and for something like
a traffic light those outnumber the visual geometry. Only objects Sollumz marks
`sollumz_drawable_model` are rendered; bounds and the object's own game lights are
deleted, so every preview is framed under the same neutral rig.

## Textures

The extractor decodes both the archetype's YTD and any dictionary embedded in the
drawable itself, the embedded one taking precedence as the game does. Sollumz does
have a `sollumz.import_ytd` operator, but the renderer binds the decoded PNGs
directly, matching each image node against its image name, its label and its own
name — that keeps one recorded texture mapping in the fingerprint. A texture it
cannot identify is reported in `missingTextures` and left unbound, never replaced
with a stand-in that would read as material evidence.

## Caching

A render is keyed by a fingerprint over the recipe, every source file's SHA-256 and
the texture mapping. Changing the renderer, the game files or the texture set
invalidates it. Do not move or delete rendered evidence after importing reviews:
search rechecks the image bytes.
