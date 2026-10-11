using System;
using System.Collections.Generic;

namespace GtavScout.Extract
{
    public static class SelfTest
    {
        /// When set, CheckPngWriter also leaves a known image here so another decoder
        /// can read it back. A structural check inside this tool cannot prove the bytes
        /// are a PNG anything else will accept.
        public static string SampleOutputDirectory;

        public static int Run()
        {
            var failures = new List<string>();

            var json = Json.Write(new Dictionary<string, object> {
                { "b", 1 }, { "a", "x\"y" }, { "c", new object[] { 1, 2 } }
            });
            if (json != "{\"a\":\"x\\\"y\",\"b\":1,\"c\":[1,2]}")
                failures.Add("Json.Write produced " + json);

            var options = Program.ParseOptions(new[] { "--id", "a", "--id", "b", "--out", "x" });
            if (!options.ContainsKey("id") || options["id"].Count != 2)
                failures.Add("ParseOptions did not collect repeated --id values");
            if (Program.One(options, "out") != "x")
                failures.Add("Program.One did not return the single --out value");

            CheckDirectorySource(failures);
            CheckPngWriter(failures);
            CheckVehicleScanner(failures);
            CheckYmapWriter(failures);

            Console.WriteLine(Json.Write(new Dictionary<string, object> {
                { "selfTest", failures.Count == 0 ? "passed" : "failed" },
                { "failures", failures.ToArray() }
            }));
            return failures.Count == 0 ? 0 : 1;
        }

        /// Writes a ymap for a synthetic archetype and reads it back. The bounds are
        /// deliberately off-centre so a wrong anchor or rotation cannot pass by luck.
        static void CheckYmapWriter(List<string> failures)
        {
            try
            {
                const string name = "gs_selftest_box";
                var hash = CodeWalker.GameFiles.JenkHash.GenHash(name);
                var def = new CodeWalker.GameFiles.CBaseArchetypeDef();
                def.name = hash; def.assetName = hash; def.lodDist = 80;
                def.bbMin = new SharpDX.Vector3(0, 0, 0);
                def.bbMax = new SharpDX.Vector3(2, 4, 3);
                def.bsCentre = new SharpDX.Vector3(1, 2, 1.5f); def.bsRadius = 2.9f;
                var archetype = new CodeWalker.GameFiles.Archetype();
                archetype.Init(null, ref def);
                var archetypes = new Dictionary<uint, CodeWalker.GameFiles.Archetype> { { hash, archetype } };

                // Footprint centre at (10, 20, 5), turned 90 degrees. The footprint
                // centre is local (1, 2, 0); turned 90 about Z that is (-2, 1, 0), so the
                // stored origin must be (12, 19, 5).
                var heading = SharpDX.Quaternion.RotationAxis(SharpDX.Vector3.UnitZ, (float)(Math.PI / 2));
                var entities = new List<YmapCommand.EntitySpec> {
                    new YmapCommand.EntitySpec { Archetype = name, Position = new SharpDX.Vector3(10, 20, 5),
                                                 Rotation = heading, Anchor = "base" } };
                YmapCommand.ResolveAnchors(entities, archetypes);
                var expected = new SharpDX.Vector3(12, 19, 5);
                if (SharpDX.Vector3.Distance(entities[0].Position, expected) > 0.001f)
                    failures.Add("base anchor resolved to " + entities[0].Position + ", expected " + expected);

                var ymap = YmapCommand.BuildYmap("gs_selftest", entities, archetypes);
                var bytes = ymap.Save();
                var problems = YmapCommand.Verify(bytes, entities, null, new List<YmapCommand.ArchetypeSpec>());
                if (problems.Count != 0) failures.Add("ymap round trip: " + Json.Write(problems));

                var back = new CodeWalker.GameFiles.YmapFile(); back.Load(bytes);
                var ent = back.AllEntities[0];
                // The file stores the inverse rotation; read back it must be the world one.
                var dot = Math.Abs(SharpDX.Quaternion.Dot(ent.Orientation, heading));
                if (dot < 0.9999f) failures.Add("ymap stored rotation does not read back as 90 degrees");
                var raw = ent.CEntityDef.rotation;
                if (Math.Abs(raw.Z + heading.Z) > 0.001f)
                    failures.Add("ymap did not store the inverse quaternion (z " + raw.Z + ")");
                if (back._CMapData.entitiesExtentsMin.Z > 5.001f || back._CMapData.entitiesExtentsMax.Z < 7.999f)
                    failures.Add("ymap extents do not span the archetype bounds");
            }
            catch (Exception error)
            {
                failures.Add("ymap writer check threw " + error);
            }
        }

        /// Vehicles live in vehicles.meta, not in any YTYP. This checks the scanner on a
        /// synthetic file shaped like the real one, so it needs no game.
        static void CheckVehicleScanner(List<string> failures)
        {
            var root = System.IO.Path.Combine(System.IO.Path.GetTempPath(),
                "gtav-scout-vehicles-" + Guid.NewGuid().ToString("N"));
            try
            {
                System.IO.Directory.CreateDirectory(root);
                System.IO.File.WriteAllText(System.IO.Path.Combine(root, "vehicles.meta"),
                    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" +
                    "<CVehicleModelInfo__InitDataList>\n" +
                    "  <InitDatas>\n" +
                    "    <Item>\n" +
                    "      <modelName>Prairie</modelName>\n" +
                    "      <txdName>prairie</txdName>\n" +
                    "      <handlingId>PRAIRIE</handlingId>\n" +
                    "      <gameName>PRAIRIE</gameName>\n" +
                    "      <vehicleMakeName>BOLLOKAN</vehicleMakeName>\n" +
                    "      <type>VEHICLE_TYPE_CAR</type>\n" +
                    "      <vehicleClass>VC_COMPACT</vehicleClass>\n" +
                    "    </Item>\n" +
                    "    <Item>\n" +
                    "      <modelName>police</modelName>\n" +
                    "      <txdName>police</txdName>\n" +
                    "      <vehicleMakeName>VAPID</vehicleMakeName>\n" +
                    "      <type>VEHICLE_TYPE_CAR</type>\n" +
                    "      <vehicleClass>VC_EMERGENCY</vehicleClass>\n" +
                    "    </Item>\n" +
                    "  </InitDatas>\n" +
                    "</CVehicleModelInfo__InitDataList>\n");
                // A stray .meta of another kind must be ignored rather than reported.
                System.IO.File.WriteAllText(System.IO.Path.Combine(root, "handling.meta"),
                    "<CHandlingDataMgr><HandlingData /></CHandlingDataMgr>");

                var problems = new List<Dictionary<string, object>>();
                using (var source = new DirectoryAssetSource(root))
                {
                    var result = VehicleScanner.Scan(source, problems);
                    if (result.Files != 1)
                        failures.Add("vehicle scanner read " + result.Files + " vehicles.meta files, expected 1");
                    if (result.Models.Count != 2)
                        failures.Add("vehicle scanner found " + result.Models.Count + " vehicles, expected 2");
                    if (problems.Count != 0)
                        failures.Add("vehicle scanner reported failures on clean input: " + Json.Write(problems));

                    var prairie = result.Models.Find(m => (string)m["id"] == "prairie");
                    if (prairie == null)
                        failures.Add("vehicle scanner did not lowercase the model name");
                    else
                    {
                        if ((string)prairie["txd"] != "prairie")
                            failures.Add("vehicle txd was " + prairie["txd"]);
                        if ((string)prairie["section"] != "CVehicleModelInfo")
                            failures.Add("vehicle section was " + prairie["section"]);
                        if (!Equals(prairie["nameResolved"], true))
                            failures.Add("vehicle name should always be resolved");
                        var tags = string.Join(",", Array.ConvertAll((object[])prairie["tags"], t => t.ToString()));
                        // The make and class are what someone searches for; neither is in
                        // the model name, so both must reach the catalogue as tags.
                        if (!tags.Contains("bollokan") || !tags.Contains("compact") || !tags.Contains("car"))
                            failures.Add("vehicle tags were " + tags);
                    }
                    if (result.Sizes.Count != 0)
                        failures.Add("vehicle sizes should be empty when no drawable was exported");
                    if (result.WithoutDrawable != 2)
                        failures.Add("expected both vehicles to report a missing drawable");
                }
            }
            catch (Exception error)
            {
                failures.Add("vehicle scanner check threw " + error);
            }
            finally
            {
                if (System.IO.Directory.Exists(root)) System.IO.Directory.Delete(root, true);
            }
        }

        /// Writes a small image and checks the container structure. Pillow reads the
        /// result back in the Python suite; here we only prove the bytes are a PNG.
        static void CheckPngWriter(List<string> failures)
        {
            var path = System.IO.Path.Combine(System.IO.Path.GetTempPath(),
                "gtav-scout-selftest-" + Guid.NewGuid().ToString("N") + ".png");
            try
            {
                var pixels = new byte[4 * 3 * 4];
                for (var i = 0; i < pixels.Length; i++) pixels[i] = (byte)(i * 7);
                PngWriter.WriteRgba(path, 4, 3, pixels);

                var written = System.IO.File.ReadAllBytes(path);
                if (written.Length < 45 || written[0] != 0x89 || written[1] != 0x50)
                    failures.Add("PngWriter produced no PNG signature");
                else if (System.Text.Encoding.ASCII.GetString(written, 12, 4) != "IHDR")
                    failures.Add("PngWriter produced no IHDR chunk");
                else if (written[16] != 0 || written[17] != 0 || written[18] != 0 || written[19] != 4)
                    failures.Add("PngWriter wrote the wrong width");
                else if (written[24] != 8 || written[25] != 6)
                    failures.Add("PngWriter did not declare 8-bit RGBA");

                try
                {
                    PngWriter.WriteRgba(path, 4, 3, new byte[8]);
                    failures.Add("PngWriter accepted a buffer too small for its dimensions");
                }
                catch (ArgumentException) { }

                if (!string.IsNullOrEmpty(SampleOutputDirectory))
                {
                    System.IO.Directory.CreateDirectory(SampleOutputDirectory);
                    // A deliberately asymmetric image: a decoder that transposes the axes or
                    // mixes up the channel order cannot read these values back correctly.
                    var sample = new byte[3 * 2 * 4];
                    for (var y = 0; y < 2; y++)
                        for (var x = 0; x < 3; x++)
                        {
                            var o = (y * 3 + x) * 4;
                            sample[o] = (byte)(10 + x);
                            sample[o + 1] = (byte)(100 + y);
                            sample[o + 2] = (byte)(200 + x + y);
                            sample[o + 3] = 255;
                        }
                    PngWriter.WriteRgba(
                        System.IO.Path.Combine(SampleOutputDirectory, "sample.png"), 3, 2, sample);
                }
            }
            catch (Exception error)
            {
                failures.Add("PngWriter check threw " + error);
            }
            finally
            {
                if (System.IO.File.Exists(path)) System.IO.File.Delete(path);
            }
        }

        /// Opening a directory source must rebuild CodeWalker's hash-to-name index from
        /// the file listing. Without it every archetype, dictionary and map name in the
        /// catalogue comes out as a bare number and text search finds nothing.
        static void CheckNameIndexPriming(string root, List<string> failures)
        {
            var dir = System.IO.Path.Combine(root, "priming");
            System.IO.Directory.CreateDirectory(dir);
            const string name = "prop_selftest_bench_01a";
            System.IO.File.WriteAllText(System.IO.Path.Combine(dir, name + ".ydr"), "geometry");
            System.IO.File.WriteAllText(System.IO.Path.Combine(dir, "prop_selftest_copy(1).ytd"), "pixels");

            var hash = CodeWalker.GameFiles.JenkHash.GenHash(name);
            using (new DirectoryAssetSource(dir))
            {
                var resolved = CodeWalker.GameFiles.JenkIndex.TryGetString(hash);
                if (resolved != name)
                    failures.Add("name index did not learn " + name + " (got '" + resolved + "')");

                // The exporter suffix must not enter the index as if it were a game name.
                // TryGetString reports "not indexed" as the empty string, not null.
                var suffixed = CodeWalker.GameFiles.JenkHash.GenHash("prop_selftest_copy(1)");
                var stored = CodeWalker.GameFiles.JenkIndex.TryGetString(suffixed);
                if (!string.IsNullOrEmpty(stored))
                    failures.Add("name index learned an exporter suffix: '" + stored + "'");
                var stripped = CodeWalker.GameFiles.JenkHash.GenHash("prop_selftest_copy");
                if (CodeWalker.GameFiles.JenkIndex.TryGetString(stripped) != "prop_selftest_copy")
                    failures.Add("name index did not learn the suffix-stripped name");
            }
        }

        /// A flattened export renames collisions to "name(1).ext". Identical copies must
        /// collapse so nothing is counted twice, genuine variants must all survive, and
        /// the catalogue must see the game's name rather than the exporter's.
        static void CheckCopySuffixHandling(string root, List<string> failures)
        {
            foreach (var pair in new[] {
                new[] { "airfield", "airfield" }, new[] { "airfield(1)", "airfield" },
                new[] { "airfield(12)", "airfield" }, new[] { "prop_x(1)y", "prop_x(1)y" },
                new[] { "prop(a)", "prop(a)" }, new[] { "prop()", "prop()" },
                new[] { "(1)", "(1)" } })
            {
                var got = DirectoryAssetSource.StripCopySuffix(pair[0]);
                if (got != pair[1])
                    failures.Add("StripCopySuffix(" + pair[0] + ") = " + got + ", expected " + pair[1]);
            }

            var dir = System.IO.Path.Combine(root, "flattened");
            System.IO.Directory.CreateDirectory(dir);
            System.IO.File.WriteAllText(System.IO.Path.Combine(dir, "airfield.ymap"), "same");
            System.IO.File.WriteAllText(System.IO.Path.Combine(dir, "airfield(1).ymap"), "same");
            System.IO.File.WriteAllText(System.IO.Path.Combine(dir, "airfield(2).ymap"), "different");
            System.IO.File.WriteAllText(System.IO.Path.Combine(dir, "solo.ymap"), "only one");

            using (var source = new DirectoryAssetSource(dir))
            {
                var maps = new List<AssetEntry>(source.Enumerate(new[] { ".ymap" }));
                if (maps.Count != 3)
                    failures.Add("expected 3 ymap entries after collapsing copies, got " + maps.Count);
                if (source.CollapsedCopies != 1)
                    failures.Add("expected 1 collapsed copy, got " + source.CollapsedCopies);
                foreach (var entry in maps)
                {
                    if (entry.Name.Contains("("))
                        failures.Add("entry name kept an exporter suffix: " + entry.Name);
                }
                var airfield = maps.FindAll(e => e.Name == "airfield.ymap");
                if (airfield.Count != 2)
                    failures.Add("expected both airfield variants, got " + airfield.Count);
                var bodies = new HashSet<string>(StringComparer.Ordinal);
                foreach (var entry in airfield)
                    bodies.Add(System.Text.Encoding.UTF8.GetString(entry.Read()));
                if (!bodies.Contains("same") || !bodies.Contains("different"))
                    failures.Add("collapsing lost a genuine variant: " + string.Join(",", bodies));
            }
        }

        /// Exercises the directory asset source on a synthetic tree. No game needed:
        /// the bytes are never parsed, only located, read back and named.
        static void CheckDirectorySource(List<string> failures)
        {
            var root = System.IO.Path.Combine(System.IO.Path.GetTempPath(),
                "gtav-scout-selftest-" + Guid.NewGuid().ToString("N"));
            try
            {
                var nested = System.IO.Path.Combine(root, "levels", "gta5");
                System.IO.Directory.CreateDirectory(nested);
                System.IO.File.WriteAllText(System.IO.Path.Combine(root, "v_bench.ytyp"), "one");
                System.IO.File.WriteAllText(System.IO.Path.Combine(nested, "props.ytyp"), "two");
                System.IO.File.WriteAllText(System.IO.Path.Combine(nested, "PROP_Bench_01a.ytd"), "pixels");
                System.IO.File.WriteAllText(System.IO.Path.Combine(nested, "hw1_08.ymap"), "map");

                using (var source = new DirectoryAssetSource(root))
                {
                    var ytyps = new List<AssetEntry>(source.Enumerate(new[] { ".ytyp" }));
                    if (ytyps.Count != 2)
                        failures.Add("DirectoryAssetSource found " + ytyps.Count + " ytyp files, expected 2");

                    var nestedEntry = ytyps.Find(e => e.Name == "props.ytyp");
                    if (nestedEntry == null)
                        failures.Add("DirectoryAssetSource did not recurse into subdirectories");
                    else
                    {
                        if (nestedEntry.Path != "levels/gta5/props.ytyp")
                            failures.Add("DirectoryAssetSource path was " + nestedEntry.Path);
                        if (System.Text.Encoding.UTF8.GetString(nestedEntry.Read()) != "two")
                            failures.Add("DirectoryAssetSource read back the wrong bytes");
                    }

                    // Exported names keep the game's mixed case; lookups must not care.
                    var found = source.Find("prop_bench_01a", new[] { ".ytd" });
                    if (found == null) failures.Add("DirectoryAssetSource.Find is case sensitive");
                    else if (found.Name != "prop_bench_01a.ytd")
                        failures.Add("DirectoryAssetSource.Find returned " + found.Name);

                    if (source.Find("prop_bench_01a", AssetSources.Drawables) != null)
                        failures.Add("DirectoryAssetSource.Find matched a missing extension");

                    var maps = new List<AssetEntry>(source.Enumerate(new[] { ".ymap" }));
                    if (maps.Count != 1)
                        failures.Add("DirectoryAssetSource found " + maps.Count + " ymap files, expected 1");
                }

                CheckCopySuffixHandling(root, failures);
                CheckNameIndexPriming(root, failures);

                try
                {
                    using (new DirectoryAssetSource(System.IO.Path.Combine(root, "does-not-exist"))) { }
                    failures.Add("DirectoryAssetSource accepted a missing asset root");
                }
                catch (System.IO.DirectoryNotFoundException) { }
            }
            catch (Exception error)
            {
                failures.Add("DirectoryAssetSource check threw " + error);
            }
            finally
            {
                if (System.IO.Directory.Exists(root)) System.IO.Directory.Delete(root, true);
            }
        }
    }
}
