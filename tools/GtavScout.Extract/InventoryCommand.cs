using System;
using System.Collections.Generic;
using System.IO;

namespace GtavScout.Extract
{
    public static class InventoryCommand
    {
        public static int Run(Dictionary<string, List<string>> options)
        {
            var outRoot = Path.GetFullPath(Program.One(options, "out"));
            if (Directory.Exists(outRoot))
                throw new ArgumentException(
                    "Output exists; choose a new directory to preserve prior snapshots: " + outRoot);

            foreach (var name in new[] { "asset-root", "game-root" })
            {
                if (!options.ContainsKey(name)) continue;
                var input = Path.GetFullPath(Program.One(options, name));
                if (outRoot.StartsWith(input, StringComparison.OrdinalIgnoreCase))
                    throw new ArgumentException("Output must be outside the source tree: " + input);
            }

            var failures = new List<Dictionary<string, object>>();
            var started = DateTime.UtcNow;

            using (var source = AssetSources.Open(options, m => Console.Error.WriteLine(m)))
            {
                var archetypes = ArchetypeScanner.Scan(source, failures);
                var vehicles = VehicleScanner.Scan(source, failures);

                // Vehicles come from vehicles.meta rather than a YTYP, but they are
                // models like any other once catalogued. A name declared both ways is
                // kept as the archetype, which is what the map actually places.
                var models = new List<Dictionary<string, object>>(archetypes.Models);
                var known = new HashSet<string>(StringComparer.Ordinal);
                foreach (var record in archetypes.Models) known.Add((string)record["id"]);
                var addedVehicles = 0;
                foreach (var record in vehicles.Models)
                {
                    if (!known.Add((string)record["id"])) continue;
                    models.Add(record);
                    addedVehicles++;
                }
                models.Sort((a, b) => StringComparer.Ordinal.Compare((string)a["id"], (string)b["id"]));

                var sizes = new Dictionary<string, object>(archetypes.Sizes, StringComparer.Ordinal);
                foreach (var pair in vehicles.Sizes)
                    if (!sizes.ContainsKey(pair.Key)) sizes[pair.Key] = pair.Value;

                Write(outRoot, "models/data/models.json",
                    new Dictionary<string, object> { { "models", models } });
                Write(outRoot, "models/data/model-sizes.json", sizes);

                var textures = TextureScanner.Scan(source, failures);
                Write(outRoot, "textures/data/textures.json",
                    new Dictionary<string, object> { { "textures", textures } });

                var locations = PlacementScanner.Scan(source, failures);
                Write(outRoot, "models/data/locations.json",
                    new Dictionary<string, object> { { "locations", locations } });

                var report = new Dictionary<string, object> {
                    { "adapter", "gta5-legacy-v1" },
                    { "assetSource", source.Describe() },
                    { "models", models.Count },
                    { "archetypes", archetypes.Models.Count },
                    { "vehicles", addedVehicles },
                    { "vehicleMetaFiles", vehicles.Files },
                    { "vehiclesWithoutDrawable", vehicles.WithoutDrawable },
                    { "textures", textures.Count },
                    { "placedArchetypes", locations.Count },
                    { "ytypFiles", archetypes.Files },
                    { "scannedArchetypes", archetypes.Scanned },
                    { "overriddenArchetypes", archetypes.Overridden },
                    { "conflictingArchetypes", archetypes.Conflicting },
                    { "unresolvedNames", archetypes.UnresolvedNames },
                    { "unresolvedNamesInDrawableDict", archetypes.UnresolvedInDrawableDict },
                    { "conflictExamples", archetypes.ConflictExamples },
                    { "collapsedCopies", (source as DirectoryAssetSource)?.CollapsedCopies },
                    { "failures", failures },
                    { "seconds", Math.Round((DateTime.UtcNow - started).TotalSeconds, 2) },
                    { "scope", "Archetypes, texture dictionaries and map placements from the " +
                               "supplied source, archetype names resolved by enumeration order. " +
                               "No rendered evidence, no semantic labels, no visual review." }
                };
                Write(outRoot, "source-report.json", report);
                Console.WriteLine(Json.Write(report));
            }
            return 0;
        }

        public static void Write(string outRoot, string relative, object value)
        {
            var target = Path.Combine(outRoot, relative.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            File.WriteAllText(target, Json.Write(value) + "\n");
        }
    }
}
