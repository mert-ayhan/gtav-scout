using System;
using System.Collections.Generic;
using CodeWalker.GameFiles;

namespace GtavScout.Extract
{
    public static class PlacementScanner
    {
        /// Stored placements are capped so one ubiquitous prop cannot dominate the
        /// snapshot; the reported count stays the true total.
        const int MaxStoredPerArchetype = 32;

        sealed class Placements
        {
            public List<string> Ymaps = new List<string>();
            public List<object> Locs = new List<object>();
            public int Total;
        }

        public static Dictionary<string, object> Scan(
            IAssetSource source, List<Dictionary<string, object>> failures)
        {
            var byArchetype = new Dictionary<string, Placements>(StringComparer.Ordinal);
            var ymapIndex = new Dictionary<string, int>(StringComparer.Ordinal);

            foreach (var entry in source.Enumerate(new[] { ".ymap" }))
            {
                YmapFile ymap;
                try
                {
                    ymap = new YmapFile();
                    ymap.Load(entry.Read());
                }
                catch (Exception error)
                {
                    failures.Add(new Dictionary<string, object> {
                        { "source", entry.Path }, { "kind", "ymap" }, { "error", error.Message } });
                    continue;
                }
                if (ymap.AllEntities == null) continue;

                if (!ymapIndex.TryGetValue(entry.Name, out var index))
                    ymapIndex[entry.Name] = index = ymapIndex.Count;

                foreach (var ent in ymap.AllEntities)
                {
                    if (ent == null) continue;
                    var name = ent.CEntityDef.archetypeName.ToString();
                    if (string.IsNullOrEmpty(name)) continue;

                    if (!byArchetype.TryGetValue(name, out var target))
                        byArchetype[name] = target = new Placements();
                    target.Total++;
                    if (!target.Ymaps.Contains(entry.Name)) target.Ymaps.Add(entry.Name);
                    if (target.Locs.Count < MaxStoredPerArchetype)
                    {
                        target.Locs.Add(new Dictionary<string, object> {
                            { "x", ent.Position.X }, { "y", ent.Position.Y },
                            { "z", ent.Position.Z }, { "i", index } });
                    }
                }
            }

            var result = new Dictionary<string, object>(StringComparer.Ordinal);
            foreach (var pair in byArchetype)
            {
                result[pair.Key] = new Dictionary<string, object> {
                    // "i" indexes this snapshot's ymap list: the source map file, never an
                    // inferred interior id.
                    { "ipls", pair.Value.Ymaps.ToArray() },
                    { "locs", pair.Value.Locs.ToArray() },
                    { "count", pair.Value.Total }
                };
            }
            return result;
        }
    }
}
