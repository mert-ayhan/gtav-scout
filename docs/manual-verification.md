# Manual verification

The automated suite is synthetic and game-free. These checks need the real game and
are run by hand. Record the observed numbers each time; they are how a regression in
extraction or decoding gets noticed.

Set `CODEWALKER_PATH` to a built CodeWalker checkout first.

## 1. Keys and archive mount

    dotnet run -c Release --project tools/GtavScout.Extract -- \
      keys --game-root "<GAME ROOT>"

On a build CodeWalker still understands this reports `status: ok`,
`aesKeyBytes: 32`, and non-zero `mountedArchives` and `indexedEntries`, and the RPF
asset source can be used directly.

If it reports `ngKeysMissing: true` and zero mounted archives, this game build no
longer exposes the NG key material CodeWalker looks for. Measure it:

    dotnet run -c Release --project tools/GtavScout.Extract -- \
      keys --game-root "<GAME ROOT>" --probe 1

`ngKeysFound` and `ngDecryptTablesFound` say how many of the 101 keys and 272
tables were recognised. Zero of both, with `aesKeyFound: true`, means the material
changed rather than moved — use the extracted-file source instead.

**Observed 2026-09-10, game build 1.0.3889.0, CodeWalker master @ 2025-04-11:**
`aesKeyFound: true`, `lutFound: true`, `ngKeysFound: 0/101`,
`ngDecryptTablesFound: 0/272`, `mountedArchives: 0`.

## 2. Export assets

Only needed while the RPF source is unusable. In OpenIV, with GTA V selected:
search for a file mask, select the results, and use **Export selected**. The
directory layout underneath does not matter; the scanner recurses.

| Stage | Mask | Gives |
| --- | --- | --- |
| A | `*.ytyp`, `*.ymap` | model catalogue and map placements — search works |
| B | `*.ytd` | texture catalogue and decoded pixels |
| C | `*.ydr`, `*.ydd`, `*.yft` | drawables for Blender previews |
| D | `*.meta` | vehicles become searchable (see below) |

Stage D is small and worth doing early. Vehicles, unlike props, are declared in
`vehicles.meta` rather than in any YTYP, so without those files a catalogue has no
vehicles at all and searching for `prairie` returns nothing.

A game update invalidates an export. Re-export and rebuild the snapshot.

### Flattened exports

Exporting into one directory makes names collide, and OpenIV renames the losers to
`name(1).ext`. On a full export of build 1.0.3889.0 that affected 93,978 of 282,233
files. The suffix carries no information about which archive a file came from, so
the tool treats it only as a sign that two files collided: it strips the suffix
when reporting a name, and yields one entry per distinct content within a colliding
group. Identical copies are collapsed — without that, placements are counted once
per copy, which inflated the totals by 22.4% before it was fixed.

`collapsedCopies` in `source-report.json` says how many copies the last scan
skipped. Exporting with the archive folder structure preserved, if your exporter
offers it, avoids the collisions and gives real provenance, but is not required.

## 3. Inventory

    dotnet run -c Release --project tools/GtavScout.Extract -- \
      inventory --asset-root "<EXPORT DIR>" --out output/gta5-source

Point `--asset-root` at the whole export, not one subdirectory. The hash-to-name
index is rebuilt from the file names in the source, so scanning only the metadata
leaves nearly every archetype named by a bare number.

Inspect `output/gta5-source/source-report.json`, especially `failures`. Some
failures are legitimate, but a failure count near the model count means the scan is
broken rather than the data. Then check how many names resolved:

    .venv/Scripts/python.exe -c "
    import json
    m=json.load(open('output/gta5-source/models/data/models.json'))['models']
    n=[r for r in m if r['name'].isdigit()]
    print(f'models {len(m):,}  unresolved {len(n):,} ({len(n)/len(m)*100:.1f}%)')"

Unresolved names are expected — see `docs/catalog-schema.md`. What is *not*
expected is nearly 100% unresolved: that means the index was never primed, and the
usual cause is passing a subdirectory as the asset root.

A successful metadata pass is not a visual review.

## 4. Catalogue build and search

    .venv/Scripts/gtav-catalog.exe --db output/gta5.sqlite build \
      --root output/gta5-source --game gta5
    .venv/Scripts/gtav-catalog.exe --db output/gta5.sqlite stats
    .venv/Scripts/gtav-catalog.exe --db output/gta5.sqlite search 'office desk' \
      --kind model --limit 20

`stats` must agree with `source-report.json`.

## 5. Texture decoding

    dotnet run -c Release --project tools/GtavScout.Extract -- extract \
      --asset-root "<EXPORT DIR>" --catalog-root output/gta5-source \
      --out output/gta5-extract --id prop_bench_01a

Then **open one of the decoded PNGs and look at it.** Wood should look brown, not
blue. Swapped red and blue channels mean `ExtractCommand.ToRgba` needs to stop
swapping. This cannot be checked by assertion; the automated suite only proves the
encoder writes readable PNGs, not that the channel order matches the source format.

## 6. Writing a ymap

    dotnet run -c Release --project tools/GtavScout.Extract -- ymap \
      --spec SPEC.json --out output/DIR --asset-root "<EXPORT DIR>"

`status: ok` means the written bytes were read back with every entity where the
spec put it. Then read the file with Sollumz and compare archetype hashes, and
render it in context with `scripts/render-map-context.py`.

**Observed 2026-09-11, Pillbox Hill:** a 14-entity ymap — 13 game props plus one
custom `gs_stand_frame` drawable declared in its own ytyp — written, read back by
CodeWalker and by Sollumz (13/13 then 14/14 archetype hashes matching, headings
matching under the world-rotation convention), and rendered on the paved plaza off
the hospital's south-west facade at z 42.45 among 484 real map entities. The
custom drawable's nine embedded DDS textures decoded to their intended colours.

## 7. Previews

See `docs/blender-cli.md`. Look at the rendered images; a status of `ready` means
four views had signal, not that the object is what its name suggests.

## 8. Custom buildings with embedded collision

Use a separate simplified collision mesh for walls, floors, columns, canopy,
stairs, kerbs and ramps. Export with `--collision-prefix` and inspect the resulting
Legacy drawable. Confirm a non-empty Composite/GeometryBVH tree, distinct surface
material indices, complete embedded textures and the intended emissive shaders.
Read the written YMAP independently with Sollumz and compare its archetype hashes.

In-game verification remains necessary: approach from several streaming distances;
walk into each wall and closed door; drive slowly against a column; drive both
access ramps; walk the stairs; test concrete, glass and metal impacts; inspect
night-time signs and canopy lighting. Check existing map collision, traffic gates,
vehicle generators and pedestrian navigation separately from new drawable bounds.

An archetype with `physicsDictionary` equal to its own name follows CodeWalker's
embedded-bound convention. File inspection and Blender ray casts do not prove the
game loads it. Record this as unverified until tested in Legacy. A shared ground
drawable can contain lamp bases even after the lamp entities have been removed;
inspect the cleared site visually before designing circulation.
