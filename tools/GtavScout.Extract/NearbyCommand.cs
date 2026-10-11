using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using CodeWalker.GameFiles;
using SharpDX;

namespace GtavScout.Extract
{
    /// Lists every map entity within a radius of a point, straight from the YMAPs.
    ///
    /// The catalogue keeps only a few example placements per archetype, which is
    /// enough to say where something tends to appear and useless for "what stands
    /// on this corner". Placing a build needs the second: the ground height, the
    /// kerb, what would have to be cleared, and which map file owns it.
    public static class NearbyCommand
    {
        public static int Run(Dictionary<string, List<string>> options)
        {
            var at = ParsePoint(Program.One(options, "at"));
            var radius = options.ContainsKey("radius")
                ? float.Parse(Program.One(options, "radius"), CultureInfo.InvariantCulture) : 50f;
            var limit = options.ContainsKey("limit")
                ? int.Parse(Program.One(options, "limit"), CultureInfo.InvariantCulture) : 200;

            var hits = new List<Dictionary<string, object>>();
            var perYmap = new Dictionary<string, int>(StringComparer.Ordinal);
            var scanned = 0;
            var failures = 0;

            using (var source = AssetSources.Open(options, m => Console.Error.WriteLine(m)))
            {
                foreach (var entry in source.Enumerate(new[] { ".ymap" }))
                {
                    scanned++;
                    YmapFile ymap;
                    try { ymap = new YmapFile(); ymap.Load(entry.Read()); }
                    catch (Exception) { failures++; continue; }
                    if (ymap.AllEntities == null) continue;

                    // Cheap reject on the file's own extents before touching entities.
                    var min = ymap._CMapData.streamingExtentsMin;
                    var max = ymap._CMapData.streamingExtentsMax;
                    if (max.X > min.X && (at.X < min.X - radius || at.X > max.X + radius ||
                                          at.Y < min.Y - radius || at.Y > max.Y + radius))
                        continue;

                    foreach (var ent in ymap.AllEntities)
                    {
                        if (ent == null) continue;
                        var dx = ent.Position.X - at.X;
                        var dy = ent.Position.Y - at.Y;
                        var distance = (float)Math.Sqrt(dx * dx + dy * dy);
                        if (distance > radius) continue;

                        var name = ent.CEntityDef.archetypeName.ToString();
                        perYmap[entry.Name] = perYmap.TryGetValue(entry.Name, out var n) ? n + 1 : 1;
                        hits.Add(new Dictionary<string, object> {
                            { "archetype", name },
                            { "ymap", entry.Name },
                            { "path", entry.Path },
                            { "position", new object[] { Round(ent.Position.X), Round(ent.Position.Y), Round(ent.Position.Z) } },
                            { "heading", Round(Heading(ent.Orientation)) },
                            // World orientation (x, y, z, w); some map pieces are not
                            // upright, and a heading alone would stand them up.
                            { "rotation", new object[] { ent.Orientation.X, ent.Orientation.Y,
                                                         ent.Orientation.Z, ent.Orientation.W } },
                            { "scale", new object[] { ent.Scale.X, ent.Scale.Y, ent.Scale.Z } },
                            { "distance", Round(distance) },
                            { "lodLevel", ent.CEntityDef.lodLevel.ToString() },
                            { "lodDist", Round(ent.CEntityDef.lodDist) }
                        });
                    }
                }
            }

            hits.Sort((a, b) => ((float)a["distance"]).CompareTo((float)b["distance"]));

            // Ground height: the lowest-lying full-detail placements near the point are
            // almost always things standing on it — kerbs, lamps, benches, bins.
            var groundSamples = hits
                .Where(h => (string)h["lodLevel"] == "LODTYPES_DEPTH_HD" ||
                            (string)h["lodLevel"] == "LODTYPES_DEPTH_ORPHANHD")
                .Take(40)
                .Select(h => (float)((object[])h["position"])[2])
                .OrderBy(z => z)
                .ToList();
            object ground = groundSamples.Count == 0
                ? null : (object)groundSamples[groundSamples.Count / 4];

            var report = new Dictionary<string, object> {
                { "at", new object[] { at.X, at.Y, at.Z } },
                { "radius", radius },
                { "ymapsScanned", scanned },
                { "ymapFailures", failures },
                { "entities", hits.Count },
                { "groundEstimate", ground },
                { "groundNote", "Lower quartile of nearby full-detail placements; check it against a render." },
                { "perYmap", perYmap.OrderByDescending(p => p.Value)
                                    .ToDictionary(p => p.Key, p => (object)p.Value) },
                { "nearest", hits.Take(limit).ToArray() }
            };
            Console.WriteLine(Json.Write(report));
            return 0;
        }

        static Vector3 ParsePoint(string text)
        {
            var parts = text.Split(',');
            if (parts.Length < 2) throw new ArgumentException("--at needs x,y or x,y,z");
            float p(int i) => float.Parse(parts[i].Trim(), CultureInfo.InvariantCulture);
            return new Vector3(p(0), p(1), parts.Length > 2 ? p(2) : 0);
        }

        static float Heading(Quaternion q)
        {
            // Yaw about Z, in degrees, from the entity's world orientation.
            var siny = 2 * (q.W * q.Z + q.X * q.Y);
            var cosy = 1 - 2 * (q.Y * q.Y + q.Z * q.Z);
            return (float)(Math.Atan2(siny, cosy) * 180.0 / Math.PI);
        }

        static float Round(float v) => (float)Math.Round(v, 2);
    }
}
