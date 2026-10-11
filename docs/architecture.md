# Architecture and resource expectations

Three layers. The Python core stores identity, metadata, evidence and FTS5 records
in local SQLite, and is game-independent — it came from upstream unchanged. A .NET
tool reads GTA V's own formats through CodeWalker.Core and writes the catalogue
JSON the core ingests. A Blender script renders previews through Sollumz.

## Asset sources

Only the archive layer needs GTA V's encryption keys. Every CodeWalker format
parser accepts raw bytes through `Load(byte[])`, so the tool reads through an
`IAssetSource` with two implementations: a directory of files exported from the
game, and the game's RPF archives. The scanners are written once against the
interface. See `README.md` for which source applies and why.

The consequence of the directory source is that extraction is a manual, staged
step, and a game update invalidates it. That is the cost of the key failure, not a
design preference.

Names are the other consequence. GTA V refers to everything by Jenkins hash and
resolves those through an index CodeWalker normally fills from RPF entry names.
The directory source rebuilds it from the export's file names, `strings.txt` and
every YTYP string table, which is why the asset root must be the whole export
rather than one subdirectory.

## Retrieval

Semantic vectors are an optional table keyed by asset, corpus, encoder revision and
description fingerprint. Normalized exact dot products avoid an ANN service but
scale linearly with eligible vectors. Hybrid retrieval combines lexical and
semantic ranks. Images still need review.

Visual descriptions come from a user-selected vision-capable agent or a human. This
project includes no API service and no hosted vision inference. That agent's
subscriptions, tokens, review time and render compute are separate costs. Batches
prepare image packets and preserve hashes; they do not produce semantic truth.

Every semantic response reports its coverage, and on a fresh catalogue that number
is brutal: ten reviewed assets against 159,380 in scope means 159,370 with no
semantic coverage at all. Read it before trusting a ranking.

## Measured costs

Observations from one machine — a Ryzen 7900X with the export on NVMe — against
game build 1.0.3889.0. They are not a guarantee, and GTA V's asset set is much
larger than San Andreas's, so upstream's figures do not transfer either.

| Stage | Input | Time | Output |
| --- | --- | --- | --- |
| OpenIV export | whole game | manual, hours | 282,233 files, 69 GB |
| `inventory` | the 69 GB export | 5 min | 124 MB of JSON |
| `build` | that snapshot | 94 s | 475,945 rows, 449 MB SQLite |
| `extract` | 10 archetypes | seconds | drawables plus decoded PNGs |
| render | 10 assets, 384 px, 12 samples | 16 s | 40 preview images |
| `semantic build` | 10 reviewed assets | 1 s after model load | 10 vectors |

The export splits as 33 GB of drawables, 36 GB of texture dictionaries and 685 MB
of metadata. The inventory pass reads and parses every YTYP, YTD and YMAP in the
source, so it scales with the export rather than with the catalogue.

What dominates elsewhere: four-view renders and decoded PNG caches consume
gigabytes; per-query evidence and freshness validation and CLI model loading can
dominate search latency. Scope work by kind, resume in bounded batches, inspect
failures, and measure cold and warm runs before starting a full visual campaign.

Metadata snapshots and evidence paths are local. Exporting or moving a database
alone does not move its evidence or make its paths portable.
