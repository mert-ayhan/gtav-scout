using System;
using System.Collections.Generic;
using CodeWalker.GameFiles;

namespace GtavScout.Extract
{
    public sealed class ScanResult
    {
        public List<Dictionary<string, object>> Models = new List<Dictionary<string, object>>();
        public Dictionary<string, object> Sizes = new Dictionary<string, object>();
        public int Overridden;
        public int Conflicting;
        public int UnresolvedNames;
        public int UnresolvedInDrawableDict;
        public int Scanned;
        public int Files;
        public List<Dictionary<string, object>> ConflictExamples = new List<Dictionary<string, object>>();
    }

    public static class ArchetypeScanner
    {
        public static ScanResult Scan(IAssetSource source, List<Dictionary<string, object>> failures)
        {
            var result = new ScanResult();
            // Enumeration order is the source's own order, and a later declaration of the
            // same archetype name replaces an earlier one, matching how the game resolves
            // DLC overrides. The core rejects conflicting duplicate identities, so exactly
            // one record per name must be emitted.
            var byName = new Dictionary<string, Dictionary<string, object>>(StringComparer.Ordinal);
            var sizes = new Dictionary<string, object>(StringComparer.Ordinal);

            // A YTYP carries the string table for the hashes inside it, and an archetype
            // in one file can be named by a string that only appears in another. Collect
            // every table before reading any archetype, or the names resolve by luck of
            // enumeration order.
            var ytyps = new List<AssetEntry>(source.Enumerate(new[] { ".ytyp" }));
            foreach (var entry in ytyps)
            {
                try
                {
                    var probe = new YtypFile();
                    probe.Load(entry.Read());
                    if (probe.Strings == null) continue;
                    foreach (var value in probe.Strings)
                        if (!string.IsNullOrEmpty(value)) JenkIndex.Ensure(value);
                }
                catch (Exception) { /* reported when the file is read again below */ }
            }

            foreach (var entry in ytyps)
            {
                result.Files++;
                YtypFile ytyp;
                try
                {
                    ytyp = new YtypFile();
                    ytyp.Load(entry.Read());
                }
                catch (Exception error)
                {
                    failures.Add(new Dictionary<string, object> {
                        { "source", entry.Path }, { "kind", "ytyp" }, { "error", error.Message } });
                    continue;
                }
                if (ytyp.AllArchetypes == null) continue;

                foreach (var archetype in ytyp.AllArchetypes)
                {
                    result.Scanned++;
                    string name;
                    try { name = archetype.Name; }
                    catch (Exception error)
                    {
                        failures.Add(new Dictionary<string, object> {
                            { "source", entry.Path }, { "kind", "archetype" }, { "error", error.Message } });
                        continue;
                    }
                    if (string.IsNullOrEmpty(name)) continue;

                    var assetName = string.IsNullOrEmpty(archetype.AssetName) ? name : archetype.AssetName;
                    // GTA V refers to archetypes by hash. A name that survives as a bare
                    // number is one no source in this scan could spell out; saying so on
                    // the record stops it reading as a real name later.
                    var resolved = !IsBareHash(name);
                    var drawableDict = archetype.DrawableDict.ToString();

                    var record = new Dictionary<string, object> {
                        { "nameResolved", resolved },
                        { "id", name },
                        { "name", name },
                        { "dff", assetName },
                        { "txd", archetype.TextureDict.ToString() },
                        { "drawableDict", archetype.DrawableDict.ToString() },
                        { "source", entry.Path },
                        { "section", archetype.Type.ToString() },
                        { "lodDist", archetype.LodDist },
                        { "tags", new object[0] }
                    };

                    if (byName.TryGetValue(name, out var previous))
                    {
                        result.Overridden++;
                        // A repeat of an identical declaration is harmless; the same name
                        // declared differently is a real ambiguity, and which one the game
                        // would load cannot be recovered from a source that has lost the
                        // archive each file came from.
                        if (!SameDeclaration(previous, record))
                        {
                            result.Conflicting++;
                            if (result.ConflictExamples.Count < 20)
                            {
                                result.ConflictExamples.Add(new Dictionary<string, object> {
                                    { "name", name },
                                    { "kept", record["source"] },
                                    { "discarded", previous["source"] },
                                    { "differingFields", DifferingFields(previous, record) } });
                            }
                        }
                    }
                    byName[name] = record;

                    // GTA V is Z-up: height is the Z extent, depth the Y extent.
                    sizes[name] = new Dictionary<string, object> {
                        { "width", archetype.BBMax.X - archetype.BBMin.X },
                        { "height", archetype.BBMax.Z - archetype.BBMin.Z },
                        { "depth", archetype.BBMax.Y - archetype.BBMin.Y }
                    };
                }
            }

            // Count over the surviving records, not over declarations: the same archetype
            // is declared many times, so counting inside the scan would report a number
            // that matches nothing in the catalogue.
            foreach (var pair in byName)
            {
                result.Models.Add(pair.Value);
                if (Equals(pair.Value["nameResolved"], true)) continue;
                result.UnresolvedNames++;
                // A drawable packed inside a dictionary has no file of its own, so no file
                // listing can supply its name. In practice these are almost all distance-LOD
                // proxies rather than props anyone would build with.
                var dict = Convert.ToString(pair.Value["drawableDict"]);
                if (!string.IsNullOrEmpty(dict) && dict != "0") result.UnresolvedInDrawableDict++;
            }
            result.Sizes = sizes;
            result.Models.Sort((a, b) => StringComparer.Ordinal.Compare((string)a["id"], (string)b["id"]));
            return result;
        }

        /// CodeWalker renders an unknown name as its decimal hash. A real archetype name
        /// never looks like that, so an all-digit name means the index did not know it.
        static bool IsBareHash(string name)
        {
            if (string.IsNullOrEmpty(name)) return false;
            foreach (var c in name) if (!char.IsDigit(c)) return false;
            return true;
        }

        /// Compares two declarations of one archetype, ignoring where each was read
        /// from: two copies of the same file describe the same thing.
        static bool SameDeclaration(Dictionary<string, object> a, Dictionary<string, object> b)
        {
            return DifferingFields(a, b).Count == 0;
        }

        static List<object> DifferingFields(Dictionary<string, object> a, Dictionary<string, object> b)
        {
            var differing = new List<object>();
            foreach (var key in a.Keys)
            {
                if (key == "source" || key == "tags") continue;
                var left = a[key];
                var right = b.TryGetValue(key, out var value) ? value : null;
                if (!Equals(Convert.ToString(left), Convert.ToString(right))) differing.Add(key);
            }
            return differing;
        }
    }
}
