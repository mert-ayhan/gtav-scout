using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using CodeWalker.GameFiles;
using SharpDX;

namespace GtavScout.Extract
{
    /// Writes a .ymap — and a .ytyp for any custom models — from a JSON placement spec.
    ///
    /// Follows CodeWalker's own editor step for step (ProjectForm.NewYmap, NewEntity,
    /// NewArchetypesFromYdrs, SaveYmap), since that is what map makers already use and
    /// trust. Nothing is reported as written until the bytes have been read back and
    /// every entity found where the spec put it.
    ///
    /// Spec:
    /// {
    ///   "ymap": "name",                       // file name without extension
    ///   "ytyp": "name",                       // needed only if "archetypes" is given
    ///   "archetypes": [                       // custom models, one per exported .ydr
    ///     { "name": "my_model", "drawable": "C:/path/my_model.ydr",
    ///       "texture": "C:/path/my_model.ytd", "lodDist": 150 } ],
    ///   "entities": [
    ///     { "archetype": "prop_bench_01a", "position": [x, y, z],
    ///       "heading": 90,                    // degrees about Z, or
    ///       "rotation": [x, y, z, w],         // a world-space quaternion
    ///       "anchor": "base",                 // put the footprint here, not the origin
    ///       "lodDist": 100, "scale": 1.0 } ]
    /// }
    public static class YmapCommand
    {
        internal sealed class EntitySpec
        {
            public string Archetype;
            public Vector3 Position;
            public Quaternion Rotation = Quaternion.Identity;
            public float LodDist = -1;
            public float Scale = 1;
            // "origin" places the archetype's own origin at Position, as the ymap stores
            // it; "base" places the centre of its footprint, at the bottom of its bounds.
            public string Anchor = "origin";
        }

        internal sealed class ArchetypeSpec
        {
            public string Name;
            public string Drawable;
            public string Texture;
            public float LodDist = -1;
        }

        public static int Run(Dictionary<string, List<string>> options)
        {
            var specPath = Path.GetFullPath(Program.One(options, "spec"));
            var outRoot = Path.GetFullPath(Program.One(options, "out"));
            Directory.CreateDirectory(outRoot);

            using var doc = JsonDocument.Parse(File.ReadAllText(specPath));
            var root = doc.RootElement;
            var ymapName = Required(root, "ymap");
            var entities = ReadEntities(root);
            var customs = ReadArchetypes(root, Path.GetDirectoryName(specPath));
            if (entities.Count == 0) throw new ArgumentException("The spec places no entities");

            // Custom models first: their archetypes are defined here, from their own bounds.
            var archetypes = new Dictionary<uint, Archetype>();
            string ytypPath = null;
            YtypFile ytyp = null;
            if (customs.Count > 0)
            {
                var ytypName = Required(root, "ytyp");
                ytyp = BuildYtyp(ytypName, customs, archetypes, outRoot);
                ytypPath = Path.Combine(outRoot, ytypName + ".ytyp");
                File.WriteAllBytes(ytypPath, ytyp.Save());
            }

            // Game models: their real archetypes supply the bounds CodeWalker uses for
            // the ymap extents. A name found nowhere would stream in as nothing, so it is
            // an error rather than a warning.
            var needed = new HashSet<uint>();
            foreach (var e in entities)
            {
                var hash = JenkHash.GenHash(e.Archetype.ToLowerInvariant());
                if (!archetypes.ContainsKey(hash)) needed.Add(hash);
            }
            if (needed.Count > 0)
            {
                if (!options.ContainsKey("asset-root") && !options.ContainsKey("game-root"))
                    throw new ArgumentException(
                        "Game archetypes are placed; pass --asset-root so their bounds can be read.");
                using var source = AssetSources.Open(options, m => Console.Error.WriteLine(m));
                FindGameArchetypes(source, needed, archetypes);
            }
            var missing = new List<string>();
            foreach (var e in entities)
                if (!archetypes.ContainsKey(JenkHash.GenHash(e.Archetype.ToLowerInvariant())))
                    missing.Add(e.Archetype);
            if (missing.Count > 0)
                throw new ArgumentException(
                    "No archetype found for: " + string.Join(", ", new HashSet<string>(missing)) +
                    ". Placing them would stream in as nothing.");

            ResolveAnchors(entities, archetypes);
            var ymap = BuildYmap(ymapName, entities, archetypes);
            var ymapPath = Path.Combine(outRoot, ymapName + ".ymap");
            var bytes = ymap.Save();
            File.WriteAllBytes(ymapPath, bytes);

            var verification = Verify(bytes, entities, ytypPath, customs);
            var report = new Dictionary<string, object> {
                { "status", verification.Count == 0 ? "ok" : "failed" },
                { "ymap", ymapPath },
                { "ytyp", ytypPath },
                { "entities", entities.Count },
                { "customArchetypes", customs.Count },
                { "entitiesExtentsMin", Vec(ymap._CMapData.entitiesExtentsMin) },
                { "entitiesExtentsMax", Vec(ymap._CMapData.entitiesExtentsMax) },
                { "streamingExtentsMin", Vec(ymap._CMapData.streamingExtentsMin) },
                { "streamingExtentsMax", Vec(ymap._CMapData.streamingExtentsMax) },
                { "flags", ymap._CMapData.flags },
                { "contentFlags", ymap._CMapData.contentFlags },
                { "verificationFailures", verification },
                { "note", "Verified by reading the written bytes back with CodeWalker. " +
                          "Nothing was written to the game installation." }
            };
            File.WriteAllText(Path.Combine(outRoot, ymapName + ".report.json"), Json.Write(report) + "\n");
            Console.WriteLine(Json.Write(report));
            return verification.Count == 0 ? 0 : 1;
        }

        static YtypFile BuildYtyp(string name, List<ArchetypeSpec> customs,
            Dictionary<uint, Archetype> archetypes, string outRoot)
        {
            var ytyp = new YtypFile();
            ytyp._CMapTypes.name = JenkHash.GenHash(name.ToLowerInvariant());
            ytyp.NameHash = ytyp._CMapTypes.name;
            JenkIndex.Ensure(name.ToLowerInvariant());

            foreach (var spec in customs)
            {
                var ydr = new YdrFile();
                ydr.Load(File.ReadAllBytes(spec.Drawable));
                var drawable = ydr.Drawable ?? throw new InvalidDataException("No drawable in " + spec.Drawable);

                var key = spec.Name.ToLowerInvariant();
                var hash = JenkHash.GenHash(key);
                JenkIndex.Ensure(key);

                // As CodeWalker's "New archetypes from YDRs".
                var archetype = ytyp.AddArchetype();
                archetype._BaseArchetypeDef.name = hash;
                archetype._BaseArchetypeDef.assetName = hash;
                archetype._BaseArchetypeDef.assetType = rage__fwArchetypeDef__eAssetType.ASSET_TYPE_DRAWABLE;
                archetype._BaseArchetypeDef.specialAttribute = 0;
                archetype._BaseArchetypeDef.flags = 32;
                archetype._BaseArchetypeDef.bbMin = drawable.BoundingBoxMin;
                archetype._BaseArchetypeDef.bbMax = drawable.BoundingBoxMax;
                archetype._BaseArchetypeDef.bsCentre = drawable.BoundingCenter;
                archetype._BaseArchetypeDef.bsRadius = drawable.BoundingSphereRadius;
                archetype._BaseArchetypeDef.hdTextureDist = 60.0f;
                archetype._BaseArchetypeDef.lodDist = spec.LodDist > 0 ? spec.LodDist : 60.0f;
                // A drawable with its textures embedded needs no dictionary; one that
                // relies on a separate .ytd names it after itself.
                if (drawable.ShaderGroup?.TextureDictionary != null || spec.Texture != null)
                    archetype._BaseArchetypeDef.textureDictionary = hash;
                if (drawable.Bound != null)
                    archetype._BaseArchetypeDef.physicsDictionary = hash;
                archetype.Init(ytyp, ref archetype._BaseArchetypeDef);
                archetypes[hash] = archetype;

                // A resource needs its drawable and dictionary beside the ytyp.
                File.Copy(spec.Drawable, Path.Combine(outRoot, key + ".ydr"), true);
                if (spec.Texture != null)
                    File.Copy(spec.Texture, Path.Combine(outRoot, key + ".ytd"), true);
            }
            return ytyp;
        }

        /// Turns every "base" anchor into the origin the ymap actually stores.
        internal static void ResolveAnchors(List<EntitySpec> entities, Dictionary<uint, Archetype> archetypes)
        {
            foreach (var e in entities)
            {
                if (e.Anchor != "base") continue;
                var archetype = archetypes[JenkHash.GenHash(e.Archetype.ToLowerInvariant())];
                var local = new Vector3(
                    (archetype.BBMin.X + archetype.BBMax.X) * 0.5f,
                    (archetype.BBMin.Y + archetype.BBMax.Y) * 0.5f,
                    archetype.BBMin.Z) * e.Scale;
                e.Position -= Vector3.Transform(local, e.Rotation);
                e.Anchor = "origin";
            }
        }

        internal static YmapFile BuildYmap(string name, List<EntitySpec> entities, Dictionary<uint, Archetype> archetypes)
        {
            // As CodeWalker's NewYmap.
            var ymap = new YmapFile();
            ymap.Loaded = true;
            ymap._CMapData.contentFlags = 65;

            foreach (var spec in entities)
            {
                var hash = JenkHash.GenHash(spec.Archetype.ToLowerInvariant());
                var archetype = archetypes[hash];

                // As CodeWalker's NewEntity defaults.
                var cent = new CEntityDef();
                cent.archetypeName = new MetaHash(hash);
                cent.rotation = new Vector4(0, 0, 0, 1);
                cent.scaleXY = spec.Scale;
                cent.scaleZ = spec.Scale;
                cent.flags = 32;
                cent.parentIndex = -1;
                cent.lodDist = spec.LodDist > 0 ? spec.LodDist : Math.Max(archetype.LodDist, 100f);
                cent.lodLevel = rage__eLodType.LODTYPES_DEPTH_ORPHANHD;
                cent.priorityLevel = rage__ePriorityLevel.PRI_REQUIRED;
                cent.ambientOcclusionMultiplier = 255;
                cent.artificialAmbientOcclusion = 255;
                cent.position = spec.Position;

                var ent = new YmapEntityDef(ymap, 0, ref cent);
                ent.SetArchetype(archetype);
                ent.SetPosition(spec.Position);
                // The file stores the inverse; SetOrientation takes the world rotation.
                ent.SetOrientation(spec.Rotation);
                ymap.AddEntity(ent);
            }

            // As CodeWalker's SaveYmap.
            ymap.CalcFlags();
            ymap.CalcExtents();
            ymap.SetName(name);
            return ymap;
        }

        internal static List<object> Verify(byte[] bytes, List<EntitySpec> entities, string ytypPath,
            List<ArchetypeSpec> customs)
        {
            var failures = new List<object>();
            var back = new YmapFile();
            back.Load(bytes);
            var got = back.AllEntities ?? new YmapEntityDef[0];
            if (got.Length != entities.Count)
            {
                failures.Add("read back " + got.Length + " entities, wrote " + entities.Count);
                return failures;
            }
            for (var i = 0; i < entities.Count; i++)
            {
                var want = entities[i];
                var have = got[i];
                if (have.CEntityDef.archetypeName.Hash != JenkHash.GenHash(want.Archetype.ToLowerInvariant()))
                    failures.Add("entity " + i + " archetype changed");
                if (Vector3.Distance(have.Position, want.Position) > 0.001f)
                    failures.Add("entity " + i + " moved to " + Vec(have.Position));
                // q and -q are the same rotation.
                var dot = Math.Abs(Quaternion.Dot(Quaternion.Normalize(have.Orientation),
                                                  Quaternion.Normalize(want.Rotation)));
                if (dot < 0.9999f)
                    failures.Add("entity " + i + " rotation changed (dot " + dot + ")");
            }
            if (ytypPath != null)
            {
                var ytyp = new YtypFile();
                ytyp.Load(File.ReadAllBytes(ytypPath));
                var count = ytyp.AllArchetypes?.Length ?? 0;
                if (count != customs.Count)
                    failures.Add("ytyp read back " + count + " archetypes, wrote " + customs.Count);
            }
            return failures;
        }

        static void FindGameArchetypes(IAssetSource source, HashSet<uint> needed,
            Dictionary<uint, Archetype> found)
        {
            foreach (var entry in source.Enumerate(new[] { ".ytyp" }))
            {
                if (needed.Count == 0) return;
                YtypFile ytyp;
                try { ytyp = new YtypFile(); ytyp.Load(entry.Read()); }
                catch (Exception) { continue; }
                if (ytyp.AllArchetypes == null) continue;
                foreach (var archetype in ytyp.AllArchetypes)
                {
                    var hash = archetype._BaseArchetypeDef.name.Hash;
                    if (!needed.Remove(hash)) continue;
                    found[hash] = archetype;
                }
            }
        }

        static List<EntitySpec> ReadEntities(JsonElement root)
        {
            var list = new List<EntitySpec>();
            if (!root.TryGetProperty("entities", out var items)) return list;
            foreach (var item in items.EnumerateArray())
            {
                var spec = new EntitySpec {
                    Archetype = Required(item, "archetype"),
                    Position = ReadVector(item.GetProperty("position"))
                };
                if (item.TryGetProperty("rotation", out var rot))
                {
                    var r = new float[4]; var k = 0;
                    foreach (var v in rot.EnumerateArray()) r[k++] = v.GetSingle();
                    spec.Rotation = Quaternion.Normalize(new Quaternion(r[0], r[1], r[2], r[3]));
                }
                else if (item.TryGetProperty("heading", out var heading))
                {
                    spec.Rotation = Quaternion.RotationAxis(Vector3.UnitZ,
                        (float)(heading.GetDouble() * Math.PI / 180.0));
                }
                if (item.TryGetProperty("lodDist", out var lod)) spec.LodDist = lod.GetSingle();
                if (item.TryGetProperty("scale", out var scale)) spec.Scale = scale.GetSingle();
                if (item.TryGetProperty("anchor", out var anchor)) spec.Anchor = anchor.GetString();
                if (spec.Anchor != "origin" && spec.Anchor != "base")
                    throw new ArgumentException("anchor must be \"origin\" or \"base\"");
                list.Add(spec);
            }
            return list;
        }

        static List<ArchetypeSpec> ReadArchetypes(JsonElement root, string baseDir)
        {
            var list = new List<ArchetypeSpec>();
            if (!root.TryGetProperty("archetypes", out var items)) return list;
            foreach (var item in items.EnumerateArray())
            {
                var spec = new ArchetypeSpec {
                    Name = Required(item, "name"),
                    Drawable = Path.GetFullPath(Path.Combine(baseDir, Required(item, "drawable")))
                };
                if (item.TryGetProperty("texture", out var tex))
                    spec.Texture = Path.GetFullPath(Path.Combine(baseDir, tex.GetString()));
                if (item.TryGetProperty("lodDist", out var lod)) spec.LodDist = lod.GetSingle();
                if (!File.Exists(spec.Drawable)) throw new FileNotFoundException("No drawable", spec.Drawable);
                if (spec.Texture != null && !File.Exists(spec.Texture))
                    throw new FileNotFoundException("No texture dictionary", spec.Texture);
                list.Add(spec);
            }
            return list;
        }

        static Vector3 ReadVector(JsonElement element)
        {
            var v = new float[3]; var k = 0;
            foreach (var item in element.EnumerateArray()) v[k++] = item.GetSingle();
            return new Vector3(v[0], v[1], v[2]);
        }

        static string Required(JsonElement element, string name)
        {
            if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.String
                || string.IsNullOrWhiteSpace(value.GetString()))
                throw new ArgumentException("Spec is missing \"" + name + "\"");
            return value.GetString();
        }

        static object Vec(Vector3 v) => new object[] { v.X, v.Y, v.Z };
    }
}
