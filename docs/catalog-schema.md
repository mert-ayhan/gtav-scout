# Catalogue input

`gtav-catalog --db DATABASE build --root CATALOG_ROOT --game gta5` reads the layout
`gtav-scout-extract inventory` writes:

```
CATALOG_ROOT/
  models/data/models.json
  models/data/model-sizes.json
  models/data/locations.json
  textures/data/textures.json
  source-report.json
```

## models.json

One record per archetype:

```json
{"models":[{"id":"prop_bench_01a","name":"prop_bench_01a","dff":"prop_bench_01a",
  "txd":"prop_bench_01a","drawableDict":"0",
  "source":"x64a.rpf/levels/gta5/props.rpf/v_bench.ytyp",
  "section":"CBaseArchetypeDef","lodDist":120.0,"tags":[]}]}
```

`id` and `name` are the archetype name. `dff` keeps upstream's field name and holds
the archetype's `assetName`, which is the drawable to load. `txd` is its
`textureDictionary`.

### Names are hashes

GTA V stores these names as Jenkins hashes and resolves them through a global
index. Reading loose files gives no archive listing to build that index from, so
the tool primes it with every asset file name in the source, CodeWalker's
`strings.txt`, and the string table inside every YTYP — collected in a first pass,
so a name is not resolved by luck of enumeration order.

**A name that stays unresolved appears as a bare decimal number** such as
`1519556632`, and the record carries `"nameResolved": false`. That is a missing
string, not a malformed record: the archetype is real and its dimensions and
placements are correct. Do not invent a plausible name for it, and expect text
search to miss it.

Measured on a full export of build 1.0.3889.0: 83,634 of 159,380 archetype names
resolve (52.5%). The number looks alarming and is not, because the two halves are
different populations:

| | resolved | unresolved |
| --- | --- | --- |
| count | 83,634 | 75,746 |
| drawable packed inside a dictionary | 1.8% | **99.5%** |
| readable `assetName` | 99.9% | 0% |

A standalone drawable is a file, so its name is in the file listing. A drawable
packed inside a `.ydd` is not, and in this game those are overwhelmingly the
`_slod_children` and `_lod_..._children` dictionaries — distance stand-ins rather
than props anyone would build with. `unresolvedNamesInDrawableDict` in the report
measures exactly that overlap.

The named half is not short of real props. Against a 21,631-entry public object
list, 97.1% of its names are present, the 633 absent are all weapons (`w_*`, which
are not archetypes at all), and all 79 of its `bench` entries are here — alongside
119 bench archetypes in total. These names exist nowhere public either: that same
public list resolves none of the 75,746.

**Model identity is `gta5:model:<archetypeName>`.**

The same archetype name can be declared in several YTYPs, and the game resolves
that by load order with later DLC winning. The scanner does the same and emits
exactly one record per name, counting replacements as `overriddenArchetypes`. It
has to: the core rejects two records that share an identity but differ.

Most of those replacements are harmless — the same declaration repeated — so the
report separates them. `conflictingArchetypes` counts only names declared *with
differing content*, and `conflictExamples` shows which fields differed and which
declaration was kept. On a full export of build 1.0.3889.0 that was 24 conflicts
out of 157,595 repeats, all differing only in `textureDictionary`. Which one the
game would load cannot be recovered from a source that has lost each file's
archive, so the tool reports the ambiguity rather than implying it resolved it.

### Vehicles

Vehicles are not archetypes. Nothing in any YTYP declares them, so they enter the
catalogue from `vehicles.meta` instead, as models with `section` set to
`CVehicleModelInfo`:

```json
{"id":"prairie","name":"prairie","nameResolved":true,"dff":"prairie",
 "txd":"prairie","drawableDict":"0","source":"vehicles.meta",
 "section":"CVehicleModelInfo","vehicleMake":"BOLLOKAN","vehicleClass":"VC_COMPACT",
 "vehicleType":"VEHICLE_TYPE_CAR","gameName":"PRAIRIE","handlingId":"PRAIRIE",
 "tags":["bollokan","prairie","compact","car"]}
```

The make, in-game name, class and type are also copied into `tags`, because none of
them appears in the model name: nothing about the string `prairie` says Bollokan or
compact, and those are what a person searches for.

Vehicle metadata carries no bounding box, so dimensions are measured from the
drawable's own bounds when that file was exported. Where an archetype and a vehicle
share a name the archetype wins, since that is what the map actually places.

If a name declared in `vehicles.meta` has no exported drawable it is still
catalogued, without dimensions, and counted as `vehiclesWithoutDrawable`.

## textures.json

One record per texture occurrence:

```json
{"textures":[{"name":"bench_wood","txd":"prop_bench_01a",
  "source":"x64a.rpf/levels/gta5/props.rpf/prop_bench_01a.ytd",
  "width":512,"height":512,"format":"D3DFMT_DXT1"}]}
```

**Texture identity is `gta5:texture:` followed by compact JSON `[source,txd,name]`.**

Unlike archetypes, occurrences are not collapsed: the same texture name in two
dictionaries is two legitimate occurrences with different pixels. Only a repeat
inside one dictionary is a collision, and that is recorded as a failure. A texture
name is not a pixel identity.

## model-sizes.json

```json
{"prop_bench_01a":{"width":1.8,"height":0.9,"depth":0.6}}
```

From each archetype's `bbMin`/`bbMax`. GTA V is Z-up, so `height` is the Z extent
and `depth` the Y extent. Archetypes without bounds are absent, and are excluded
when a dimension filter is requested rather than treated as zero-sized.

## locations.json

```json
{"locations":{"prop_bench_01a":{
  "ipls":["hw1_08.ymap"],
  "locs":[{"x":1.5,"y":-2.0,"z":30.25,"i":0}],
  "count":1}}}
```

From YMAP entity placements. `ipls` keeps upstream's field name and holds ymap file
names; `i` indexes that list — the source map file, never an inferred interior id.
Stored `locs` are capped at 32 per archetype so one ubiquitous prop cannot dominate
the snapshot, while `count` stays the true total.

## Provenance and rebuilds

`source` records where a record came from: an RPF-internal path when read through
the archives, or a path relative to the asset root when read from exported files.
Records and source roots enter the metadata hash.

A metadata-only build does not detect edited drawable or texture bytes. Render
provenance separately includes source bytes and recipe hashes. A game update
changes archetypes, so it needs a fresh `inventory` and an explicit reimport.

Keep generated metadata, evidence and databases out of Git.

## Local preview overrides

`gtav-catalog-visual prepare --keys KEYS --overrides OVERRIDES --out DIR` expects a
key list:

```json
["gta5:model:prop_bench_01a"]
```

and a mapping to local images:

```json
{"gta5:model:prop_bench_01a":["/path/to/azimuth-045.png","/path/to/azimuth-135.png"]}
```

One to eight images per key. Every image is validated and hashed. `prepare` writes
each packet into its own content-addressed directory and names the paths in
`latest.json`; read that rather than assuming a filename. The response schema is in
each `packet.json` — use that exact version rather than guessing fields.
