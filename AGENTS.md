# Using GTAV Scout with an AI agent

This is an early-alpha discovery tool. Read `README.md`, `docs/catalog-schema.md`,
`docs/blender-cli.md` and `docs/manual-verification.md` before operating it. Use
this tool to find and inspect reusable assets; keep your own Blender construction
workflow for building with them.

## Start

1. Ask for or discover the user's game path, asset export path and Blender
   executable. Write output to a local ignored directory outside both. Do not
   assume any hosted catalogue, preview service or CDN exists, because none does.
2. Set `CODEWALKER_PATH` to a built CodeWalker checkout before any extraction.
   CodeWalker is not bundled. Run `--help` and the `--self-test` before relying on
   commands. For `gtav-catalog`, `--db` comes before the subcommand.
3. Establish which asset source works. Run `keys --game-root DIR`. If it reports
   `ngKeysMissing`, this game build does not expose the key material CodeWalker
   needs and the RPF source is unusable; the user must export assets with OpenIV
   and you pass `--asset-root`. Do not present this as a failure to work around —
   it is measured, and `--probe 1` reports the detail.
4. Build a snapshot with `gtav-catalog-sources`, then read `source-report.json`,
   especially `failures`. Import it with `gtav-catalog build --game gta5`. **A
   successful metadata import is not a visual review.**
5. Search several formulations and related functional categories, and inspect
   coverage. Opaque names and incomplete annotations mean absence from a shortlist
   is not proof that a suitable asset does not exist. Five queries is not
   "several": for a food stand, search the dish (`taco`, `burger`, `steak`), the
   equipment (`bbq`, `grill`, `cooler`, `sink`), the packaging (`food bag`,
   `coffee`, `cup`), the furniture and the containers separately. A build that
   searched narrowly misses props that were there all along.
6. Render small, varied batches. Review the images yourself with your
   image-viewing capability. **Never infer an object's shape, material or role
   from its filename**, or from a surface you have not seen.
7. Import honest reviews, preserving evidence paths and hashes. Describe visible
   shape, material, condition, likely use, orientation uncertainty and missing
   views. Do not mark an AI review as human. **Never fabricate a visual review to
   make a test or a coverage counter pass.** Ambiguous and failed assets stay
   unresolved.
8. Build semantic vectors from actual descriptions, search with `--hybrid`, and
   inspect the proposed objects. Test the user's explicit constraints visually and
   check dimensions, collisions and orientation in the construction scene.
9. Record which candidates were used, rejected, or found manually outside the
   results.

## Designing a build

Finding assets is half the job; the other half is making something a person wants
to look at. Two agents were given the same two briefs with the same catalogue and
the same pipeline. One produced competent objects in a grey void; the other
produced places. Every difference was a design decision, not a tooling one, and
these rules are what separated them.

**Build a place, not an object.** A stand needs a street: a facade behind it,
paving under it, a kerb, a drain, a scrap of litter. A patrol car needs a precinct
lot with painted bays and a wheel stop. Context is what makes scale legible and
what makes a render read as Los Santos rather than as a model on a turntable.
Where the build is meant to sit in the real map, import the surrounding YMAP
entities and render it there.

**Commit to an art direction before placing anything.** Pick a palette of three
or four colours, a neighbourhood and a character, and say them out loud: "teal
enamel, coral-and-cream awning, warm timber; a taco cart in Strawberry." Default
red-on-grey is not a choice. Every later material and prop decision gets checked
against that line.

**Give it an identity, not a label.** "LOS SANTOS STREET EATS" describes a
category. "LA ESQUINA — TACOS DE LA CALLE" on the fascia, "STRAWBERRY – LOS
SANTOS" on the skirt and a chalkboard with priced dishes is a business. Local
specifics — district names, Spanish shop signage, a vendor permit number — are
what make it belong to this city.

**Imply the person who uses it.** Meat on the griddle, tacos plated, three sauce
bottles, a cutting board, a paper bag, a permit card clipped to the awning post, a
stool for the one regular. Each detail is small and together they say someone
works here. A clean, empty build reads as a showroom.

**Keep real scale, and measure it.** A counter works at about 1.05 m; a walkway
needs about 0.9 m. Leave game props at their true size and fit the new geometry to
them, not the reverse. A prop scaled up to fill a gap — an awning stretched into a
roof — is a sign the layout is wrong, and it shows.

**Light for daylight first.** Neutral, soft daylight exposes weak geometry, which is
the point: fix the geometry. A night scene with glowing emissive signs hides a weak
build and should come after, not instead.

**Compose, don't centre.** An elevated three-quarter view, the subject off-centre,
paving and kerb lines leading in, the background adding depth. Frame at least one
close-up that someone will actually inspect.

**For a vehicle conversion,** follow the bodywork. A livery panel cut to the door
and wing lines reads as paint; a rectangle pasted on reads as a sticker. Kit it out
the way the real thing is: a lightbar with a mount and segmented lenses, a push bar
with grille lights, a whip antenna, an A-pillar spotlight, a roof number for the
helicopter, a plate. Use the game's own badge and decal art where it fits, and make
new lettering where it does not.

**Choose from a contact sheet, and write down the rejects.** Render every candidate
— twelve is a reasonable pool — look at all four views, and record why each one
was taken or turned down ("a bright beach parasol, off-palette"; "a complete
hot-dog cart, wrong dish"). The rejects are evidence that you looked.

**Iterate against what you see, at least twice.** Keep the first render. Then list
what is wrong in it — a sign floating off the ground, a post piercing the awning, a
grill facing its back to the customer, overexposure — fix those, render again, and
then go in close: a close-up pass finds two tacos intersecting and a permit card
with nothing holding it up. Record each round.

**Hand over a delivery note** beside the `.blend` and the renders: the brief as you
understood it, the selections table with visual reasons, the rejects, the iteration
log with before-and-after renders, measurements, and the limits — what is invented
rather than taken from the map, what the low-poly game props give away at close
range, and how much of the catalogue your search actually covered.

## Placing a build in the map

A build that is meant to exist in the game ends as a `.ymap` that places entities,
a `.ytyp` that declares any custom models, and the custom `.ydr` files themselves.
The tool writes the first two with CodeWalker, following its map editor step for
step; Sollumz exports the drawables.

**Survey the site before choosing it.** `gtav-scout-extract nearby --at X,Y`
lists every map entity around a point with its archetype, map file, position,
rotation and LOD level, and estimates the ground height from what stands on it.
Then render the area from above with `render-map-context.py --plan-only` and a
coordinate grid, and choose by looking. Bounding boxes hint; a plan shows the
facade, the paving and what already stands there.

**Interior entities are occupied space.** Hospital lobbies, shop interiors and
MLO rooms live in their own ymaps. Leaving them out of an occupancy check makes a
building's inside look like open ground; a first test here put a food stand in
Pillbox's lobby exactly that way. Wall-mounted props — lights, signs — mark where
a facade runs.

**A new ymap adds; it cannot remove.** If the chosen site holds something, either
choose clear ground or ship an edited copy of the map file that owns it, and say
which. When a block has a DLC override (`hei_dt1_06_strm_0` over
`dt1_06_strm_0`), the game loads the override, so that is the file to edit.

**Place by footprint.** A ymap stores each entity's archetype origin, which is
rarely the object's base. `"anchor": "base"` in a spec puts the centre of the
footprint at the given point; custom models exported with their origin at their
ground centre go at the site with the default `"anchor": "origin"`.

**Prove the file, not the spec.** `ymap` reads its own output back and fails if
any entity moved. Read it again with Sollumz — an independent implementation —
and check that the archetype hashes equal the Jenkins hash of the intended names;
Sollumz shows unknown names as `hash_xxxxxxxx`. Then render before and after with
`render-map-context.py`, which builds the after-scene from Sollumz's reading of
the written file, so a correct render is evidence about the file itself.

**Custom models** come from `examples/export_custom_drawable.py`: every object
with a given name prefix, text turned to mesh, each flat colour baked to a DDS
texture, joined, converted and exported with embedded textures. Game props in
the same build are placed by name in the ymap, not re-exported.

- `--emissive emissivenight.sps` puts every material that glowed in the build on
  an emissive shader — `emissivenight` lights at night, as GTA's own signs do;
  `emissive` is always on. Without it a lit sign exports as flat paint.
- `--collision --collision-material CONCRETE` embeds a collision bound. By
  default it is built from the visual mesh, which is right for a stand and wrong
  for a building: give a building a simplified collision mesh — walls, floors,
  stairs, kerbs — so players and cars collide with the shape they see and not
  with every sign bracket.
- **Check the file, not the export log.** `gtav-scout-extract inspect --file
  X.ydr` lists shader files, embedded textures, the bound tree with vertex and
  polygon counts and collision materials, and light count, read with CodeWalker.
  An export that reported success once had no collision and no emissive at all.
- **Open question:** CodeWalker's editor sets an archetype's `physicsDictionary`
  to its own name when the drawable carries an embedded bound, and the ymap
  command follows it. Whether the game then loads that collision has not been
  confirmed in game here; say so until someone has walked into one.

## GTA V specifics

- The adapter targets the **Legacy** edition. Enhanced (`GTA5_Enhanced.exe`) is
  unsupported and the tool says so rather than guessing.
- **Archetype names are the identity, and about half are hashes.** An archetype
  named by a bare decimal number, such as `1519556632`, carries
  `"nameResolved": false`. It is a real archetype with correct dimensions and
  placements — **report it as unresolved rather than inventing a plausible name**.
  Nearly all of them are distance-LOD stand-ins packed inside drawable
  dictionaries, so they are rarely what a build needs; text search cannot reach
  them either way. Do not read the unresolved count as missing props: measured
  against a public object list, the named half contains 97.1% of it.
- **Vehicles come from `vehicles.meta`**, not from any YTYP, and carry
  `section: CVehicleModelInfo` plus make, class and in-game name as tags. If the
  export has no `.meta` files the catalogue has no vehicles at all — say so rather
  than concluding the game has none. `extract --drawable NAME` still pulls a
  drawable by file name when a model is outside the catalogue.
- **Placements are YMAP entities only.** A named archetype with no placements is
  usually one placed through an interior or spawned by script, not an error.
- Archetype bounding boxes give real dimensions, so dimension filters are
  meaningful. Height is the Z extent: GTA V is Z-up.
- A texture name is not a pixel identity. The same name in two dictionaries is two
  occurrences with different pixels.
- **A game update invalidates everything upstream of the catalogue.** New
  archetypes, changed drawables and a stale asset export all need a fresh
  `inventory` and an explicit reimport. Renders keyed to changed bytes are
  invalidated by their fingerprint, but metadata is not rechecked for you.
- **Fragments (`.yft`) import with baggage.** They bring their physics bounds in
  as meshes — for a traffic light, 19 collision objects against 11 visual ones —
  so keep only objects Sollumz marks `sollumz_drawable_model`. A vehicle drawable
  ships one visual wheel, because the game instances the rest onto bones; the four
  `hub_*` meshes give the positions for the other three.
- **A texture can be a Rockstar stand-in.** `prop_remove` reads "PLEASE REPLACE
  PROP". A render wearing it is faithful to the files and still says nothing about
  how the object looks; the renderer reports `placeholder_texture`.

## Reviews and revisions

**`--out` is a directory, not a file**, for `gtav-catalog-visual prepare`,
`gtav-catalog-shortlist prepare` and `plan-asset-catalog-batch.py` alike. Each
fills it and names what it wrote in a `latest.json` or an equivalent report; read
that rather than assuming a filename. Assuming otherwise silently produces nothing
where you expect a file.

`gtav-catalog-visual prepare` writes each packet into its own content-addressed
directory and records the paths in `latest.json`. `manifest.json` holds the private
identities and evidence; `packet.json` holds the review instructions, image ids and
the exact response schema. Read the packet's schema rather than guessing fields.
`sheets --manifest MANIFEST --out DIR` builds contact sheets.

    gtav-catalog-visual --db output/gta5.sqlite import \
      --manifest PATH_TO_MANIFEST --responses PATH_TO_RESPONSES
    gtav-catalog-semantic --db output/gta5.sqlite build

Do not move or delete evidence after importing: search rechecks the image bytes.
Moving a database alone does not move its evidence or make its paths portable.

`gtav-catalog-shortlist prepare --help` provides query-specific constrained
verification. General descriptions and query verdicts stay separate.
`scripts/plan-asset-catalog-batch.py` selects deterministic category-balanced
batches into an output directory; `scripts/asset_catalog_campaign.py` splits review
packets; `scripts/asset_catalog_run_chunks.py` resumes bounded render chunks with a
journal. These prepare work — they do not call a vision service for you.

## Setup and commands

Placeholders: `<GAME ROOT>` is the GTA V install, `<EXPORT DIR>` the user's OpenIV
export (all of it — `meta/`, `models/`, `textures/` or however it is laid out),
`<CODEWALKER>` a built CodeWalker checkout (`references/CodeWalker` is ignored by
git and a good place for it), `<BLENDER>` the Blender executable with Sollumz and
its dependencies installed. Blender is often not on `PATH`; ask for it.

- **Prefer `--asset-root`.** Run `keys --game-root` once; if it reports
  `ngKeysMissing` (measured on Legacy 1.0.3889.0: 0 of 101 NG keys found) the
  archives cannot be opened and every command takes `--asset-root <EXPORT DIR>`.
- Python lives in `.venv` (3.12, created by `uv`; it has no `pip`, use
  `uv pip install --python .venv/Scripts/python.exe ...`). On Linux/macOS the
  path is `.venv/bin/`.

Commands:

    # tests — set both variables or the Blender and PNG checks skip
    export CODEWALKER_PATH=<CODEWALKER>
    export BLENDER_PATH=<BLENDER>
    .venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'
    dotnet run -c Release --project tools/GtavScout.Extract -- --self-test

    # catalogue and search
    dotnet run -c Release --project tools/GtavScout.Extract -- \
      inventory --asset-root <EXPORT DIR> --out output/NEW_DIR
    .venv/Scripts/gtav-catalog.exe --db output/gta5.sqlite search 'bench' --kind model

    # extract and preview
    dotnet run -c Release --project tools/GtavScout.Extract -- extract \
      --asset-root <EXPORT DIR> --catalog-root output/gta5-source \
      --out output/DIR --id NAME            # catalogued models
    #   --drawable NAME instead of --id for anything outside the catalogue
    <BLENDER> -b --python scripts/render-asset-catalog-views.py -- \
      --input output/DIR/input.json --output output/DIR-previews

    # what stands around a point, straight from the YMAPs (~20 s over a full export)
    dotnet run -c Release --project tools/GtavScout.Extract -- nearby \
      --asset-root <EXPORT DIR> --at X,Y[,Z] --radius 60 --limit 5000

    # write a .ymap (+ .ytyp for custom .ydr models) from a JSON spec, verified
    dotnet run -c Release --project tools/GtavScout.Extract -- ymap \
      --spec SPEC.json --out output/DIR --asset-root <EXPORT DIR>

    # custom geometry from a build .blend -> .ydr with embedded textures
    <BLENDER> -b --python examples/export_custom_drawable.py -- \
      --blend BUILD.blend --prefix PREFIX_ --name my_model --out output/DIR

    # the site from above, and a written ymap in its real surroundings
    <BLENDER> -b --python scripts/render-map-context.py -- --plan-only ...
    <BLENDER> -b --python scripts/render-map-context.py -- --ymap FILE.ymap ...

Set `CODEWALKER_PATH` for every `dotnet` command. Measured on one machine: the full
`inventory` takes about five minutes, `build` about ninety seconds, a context
render of ~500 map entities about two minutes. Run long ones in the background.

## Traps

Each of these cost a debugging round before it was written down.

- **`--asset-root` must be the whole export.** Names are Jenkins hashes resolved
  from the file listing; scanning `meta/` alone leaves nearly every name numeric.
- **`--out` is a directory** for visual `prepare`, shortlist `prepare` and the batch
  planner. Each names what it wrote in `latest.json`. `inventory --out` refuses an
  existing directory on purpose.
- **Flattened exports rename collisions `name(1).ext`.** The directory source
  collapses identical copies and strips the suffix from reported names. Never let a
  `(N)` reach catalogue data.
- **`JenkIndex.TryGetString` returns `""`, not `null`,** for an unknown hash.
- **Sollumz: check `hasattr(bpy.types, 'SOLLUMZ_OT_import_assets')`.**
  `bpy.ops.<anything>` is a lazy proxy and `hasattr` on it is always true. Without
  its Python dependencies Sollumz registers only `install_dependencies`; run it,
  save preferences, and verify in a fresh Blender.
- **Blender deletions invalidate references.** Decide what to keep by name before
  removing anything, or you get "StructRNA of type Object has been removed".
- **Sollumz materials:** body paint goes in slots whose name contains `[PRIMARY]`;
  collision meshes are anything not `sollumz_drawable_model`.
- **Vehicles** live in `vehicles.meta`; the catalogue only has them once `.meta`
  files are exported. CodeWalker's `VehicleInitData.Load` throws on incomplete
  records — the scanner reads fields directly for that reason.
- **Look at the image, not the status.** A `ready` render has twice been a
  collision skeleton or Rockstar's "PLEASE REPLACE PROP" texture. Every render you
  report on, you have opened.
- **Interior ymaps are occupied space.** `rc12b_*`, `*_interior*` and MLO entities
  fill building interiors. Filter them out of an occupancy check and a hospital
  lobby reads as a free plaza. Pick sites from a `--plan-only` render, not from
  bounding boxes.
- **A base ymap and its DLC override** (`dt1_06_strm_0` / `hei_dt1_06_strm_0`)
  list the same entities twice; the game loads the override.
- **Sollumz export in a background session:** "limit to selected" does not hold,
  so reduce the scene to the one drawable first; embedded textures must be DDS
  (Blender cannot write DDS — the export script writes uncompressed A8R8G8B8
  itself); meshes need a UV map named `UVMap 0` and a vertex colour layer
  `Color 1`, filled white, or the model can render black in game. It writes
  `gen8/` (Legacy) and `gen9/` (Enhanced).
- **Emissive is lost** when auto-converted materials become `default.sps`; pass
  `--emissive emissivenight.sps` to the export script.
- **Sollumz's auto collision keeps the visual materials** on the bound copy and
  then refuses them; the export script replaces them with one collision material.
- **Verify exports with `inspect`**, which reads the file with CodeWalker:
  `dotnet run -c Release --project tools/GtavScout.Extract -- inspect --file X.ydr`.
  Shader names come from `tools/GtavScout.Extract/shader-names.txt`.
- **Windows paths:** Python under Git Bash does not understand `/tmp/...` or
  `/c/...` in every call; pass Windows paths to Python and Blender.
- **Heredocs rewrite escapes.** `\n` and `\0` inside a Bash heredoc reach the file
  as a real newline and a real NUL byte, and apostrophes break quoting. Write code
  with a file-editing tool, never through a heredoc.
- **Symlink test skips** without Windows Developer Mode; that is environmental.

## Contributions

Keep tests synthetic and game-free. A behaviour that needs the game gets a manual
step in `docs/manual-verification.md`, not a test that silently skips. Never commit
`output/`, `references/`, local paths, credentials, game assets, databases, decoded
pixels or private annotation payloads — `.gitignore` covers them; keep it that way.
When a measured number changes, update the docs that quote it. Commit messages
explain why and record the measurements that justify the change. Benchmark reports
should disclose sample construction, missed candidates, unsupported assets and
costs, without redistributing game data. Do not claim coverage from render counts
alone.
