using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using CodeWalker.GameFiles;
using CodeWalker.Utils;

namespace GtavScout.Extract
{
    /// Pulls each requested archetype's drawable and texture dictionary out of the
    /// asset source, decodes the textures to PNG, and writes the batch the Blender
    /// renderer consumes.
    public static class ExtractCommand
    {
        public static int Run(Dictionary<string, List<string>> options)
        {
            var outRoot = Path.GetFullPath(Program.One(options, "out"));
            options.TryGetValue("id", out var ids);
            // Vehicles, weapons and peds are declared in .meta files rather than in a
            // YTYP, so they never reach the archetype catalogue even though their
            // drawables are right there in the source. --drawable extracts one by file
            // name, with the texture dictionary looked up under the same name.
            options.TryGetValue("drawable", out var drawables);
            ids = ids ?? new List<string>();
            drawables = drawables ?? new List<string>();
            if (ids.Count == 0 && drawables.Count == 0)
                throw new ArgumentException("At least one --id or --drawable is required");

            var sourcesDir = Path.Combine(outRoot, "sources");
            Directory.CreateDirectory(sourcesDir);
            if (options.ContainsKey("catalog-root")) LoadTextureIndex(catalogRoot(options));

            var models = ids.Count > 0
                ? ReadModels(Path.Combine(catalogRoot(options), "models", "data", "models.json"))
                : new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
            foreach (var name in drawables)
            {
                models[name] = new Dictionary<string, string>(StringComparer.Ordinal) {
                    { "id", name }, { "dff", name }, { "txd", name } };
                ids.Add(name);
            }
            var assets = new List<object>();
            var failures = new List<object>();

            using (var source = AssetSources.Open(options, m => Console.Error.WriteLine(m)))
            {
                foreach (var id in ids)
                {
                    try { assets.Add(ExtractOne(source, models, id, sourcesDir)); }
                    catch (Exception error)
                    {
                        failures.Add(new Dictionary<string, object> {
                            { "id", id }, { "error", error.Message } });
                    }
                }

                var manifest = new Dictionary<string, object> {
                    { "assets", assets },
                    { "failures", failures },
                    { "assetSource", source.Describe() },
                    { "decodeRecipe", new Dictionary<string, object> {
                        { "output", "PNG RGBA native resolution" },
                        { "mip", 0 },
                        { "decoder", "CodeWalker.Core DDSIO.GetPixels" } } }
                };
                File.WriteAllText(Path.Combine(outRoot, "input.json"), Json.Write(manifest) + "\n");
            }

            Console.WriteLine(Json.Write(new Dictionary<string, object> {
                { "assets", assets.Count }, { "failures", failures },
                { "input", Path.Combine(outRoot, "input.json") } }));
            return failures.Count == 0 ? 0 : 1;
        }

        static string catalogRoot(Dictionary<string, List<string>> options)
        {
            return Path.GetFullPath(Program.One(options, "catalog-root"));
        }

        static Dictionary<string, Dictionary<string, string>> ReadModels(string path)
        {
            if (!File.Exists(path))
                throw new FileNotFoundException("No models.json under the catalogue root", path);
            var result = new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
            foreach (var record in MiniJson.ReadObjectArray(File.ReadAllText(path), "models"))
            {
                if (record.TryGetValue("id", out var id) && !string.IsNullOrEmpty(id))
                    result[id] = record;
            }
            return result;
        }

        static object ExtractOne(IAssetSource source,
            Dictionary<string, Dictionary<string, string>> models, string id, string sourcesDir)
        {
            var key = id.StartsWith("gta5:model:", StringComparison.Ordinal)
                ? id.Substring("gta5:model:".Length) : id;
            if (!models.TryGetValue(key, out var record))
                throw new ArgumentException("Unknown model " + id);

            var assetName = record.TryGetValue("dff", out var a) && !string.IsNullOrEmpty(a) ? a : key;
            var drawable = source.Find(assetName, AssetSources.Drawables);
            if (drawable == null)
                throw new FileNotFoundException(
                    "No .ydr, .ydd or .yft found for " + assetName + "; it may not be exported yet.");

            var drawableBytes = drawable.Read();
            var drawablePath = StoreBytes(sourcesDir, drawable.Name, drawableBytes);

            var textures = new Dictionary<string, object>(StringComparer.Ordinal);
            var undecodedEarly = new List<object>();
            // A drawable can carry its own texture dictionary, and the game looks there
            // before the archetype's. Decoding only the external YTD leaves those
            // materials untextured, which reads as missing evidence rather than as the
            // tool having looked in the wrong place.
            var embeddedDir = Path.Combine(Path.GetDirectoryName(drawablePath), "textures");
            foreach (var texture in EmbeddedTextures(drawableBytes, Path.GetExtension(drawable.Name)))
                Decode(texture, embeddedDir, textures, undecodedEarly);

            var sourceFiles = new List<object> { drawablePath };
            var sources = new List<object> {
                new Dictionary<string, object> {
                    { "path", drawable.Path }, { "entry", drawable.Name },
                    { "bytes", drawableBytes.Length }, { "sha256", Sha256(drawableBytes) } } };
            var undecoded = undecodedEarly;
            var embeddedCount = textures.Count;

            // A hash-only textureDictionary name means the archetype's dictionary could not
            // be resolved to a readable name; there is nothing to look up, so say so rather
            // than guessing at a file.
            var txdName = record.TryGetValue("txd", out var t) ? t : null;
            if (!string.IsNullOrEmpty(txdName) && txdName != "0"
                && !txdName.StartsWith("hash_", StringComparison.Ordinal))
            {
                var ytdEntry = source.Find(txdName, new[] { ".ytd" });
                if (ytdEntry == null)
                {
                    undecoded.Add(new Dictionary<string, object> {
                        { "txd", txdName }, { "reason", "dictionary not found in this asset source" } });
                }
                else
                {
                    var ytdBytes = ytdEntry.Read();
                    var ytdPath = StoreBytes(sourcesDir, ytdEntry.Name, ytdBytes);
                    sourceFiles.Add(ytdPath);
                    sources.Add(new Dictionary<string, object> {
                        { "path", ytdEntry.Path }, { "entry", ytdEntry.Name },
                        { "bytes", ytdBytes.Length }, { "sha256", Sha256(ytdBytes) } });

                    var ytd = new YtdFile();
                    ytd.Load(ytdBytes);
                    var textureDir = Path.Combine(Path.GetDirectoryName(ytdPath), "textures");
                    Directory.CreateDirectory(textureDir);
                    if (ytd.TextureDict != null && ytd.TextureDict.Textures != null
                        && ytd.TextureDict.Textures.data_items != null)
                    {
                        foreach (var texture in ytd.TextureDict.Textures.data_items)
                            Decode(texture, textureDir, textures, undecoded);
                    }
                }
            }

            // Map pieces and many props take textures from a parent dictionary the game
            // links in through gtxd relationships, which an export does not carry. What
            // the shaders ask for and neither dictionary above supplied is looked up by
            // name across the catalogue, and every such guess is reported as one.
            var resolvedByName = new List<object>();
            var unresolved = new List<object>();
            foreach (var wanted in ReferencedTextures(drawableBytes, Path.GetExtension(drawable.Name)))
            {
                if (textures.ContainsKey(wanted)) continue;
                var found = ResolveByName(source, wanted, assetName, txdName, sourcesDir,
                                          textures, undecoded, sourceFiles, sources);
                if (found != null) resolvedByName.Add(found);
                else unresolved.Add(wanted);
            }

            return new Dictionary<string, object> {
                { "id", "gta5:model:" + key },
                { "model", key },
                { "drawable", drawablePath },
                { "textures", textures },
                { "sourceFiles", sourceFiles },
                { "sources", sources },
                { "embeddedTextures", embeddedCount },
                { "resolvedByName", resolvedByName },
                { "unresolvedTextures", unresolved },
                { "undecodedTextures", undecoded }
            };
        }

        /// Texture names this drawable's shaders sample, lowercased.
        static IEnumerable<string> ReferencedTextures(byte[] bytes, string extension)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var drawable in LoadDrawables(bytes, extension))
            {
                var shaders = drawable?.ShaderGroup?.Shaders?.data_items;
                if (shaders == null) continue;
                foreach (var shader in shaders)
                {
                    var parameters = shader?.ParametersList?.Parameters;
                    if (parameters == null) continue;
                    foreach (var parameter in parameters)
                    {
                        if (parameter == null || parameter.DataType != 0) continue;
                        var name = (parameter.Data as TextureBase)?.Name;
                        if (!string.IsNullOrEmpty(name)) names.Add(name.ToLowerInvariant());
                    }
                }
            }
            return names;
        }

        static Dictionary<string, List<string>> textureIndex;

        /// Every dictionary that holds a texture of this name, from the catalogue.
        public static void LoadTextureIndex(string catalogRoot)
        {
            textureIndex = new Dictionary<string, List<string>>(StringComparer.Ordinal);
            var path = Path.Combine(catalogRoot, "textures", "data", "textures.json");
            if (!File.Exists(path)) return;
            foreach (var record in MiniJson.ReadObjectArray(File.ReadAllText(path), "textures"))
            {
                if (!record.TryGetValue("name", out var name) || !record.TryGetValue("txd", out var txd)) continue;
                name = name.ToLowerInvariant();
                if (!textureIndex.TryGetValue(name, out var list)) textureIndex[name] = list = new List<string>();
                if (!list.Contains(txd)) list.Add(txd);
            }
        }

        static object ResolveByName(IAssetSource source, string wanted, string assetName, string txdName,
            string sourcesDir, Dictionary<string, object> textures, List<object> undecoded,
            List<object> sourceFiles, List<object> sources)
        {
            if (textureIndex == null || !textureIndex.TryGetValue(wanted, out var candidates) || candidates.Count == 0)
                return null;
            // Prefer the dictionary that shares the most leading characters with the
            // drawable or its own dictionary: a dt1_06 building takes dt1_06 textures.
            string best = null; var bestScore = -1;
            foreach (var candidate in candidates)
            {
                var score = Math.Max(CommonPrefix(candidate, assetName), CommonPrefix(candidate, txdName ?? ""));
                if (score > bestScore || (score == bestScore && string.CompareOrdinal(candidate, best) < 0))
                { best = candidate; bestScore = score; }
            }
            var entry = source.Find(best, new[] { ".ytd" });
            if (entry == null) return null;
            var bytes = entry.Read();
            var ytd = new YtdFile();
            ytd.Load(bytes);
            var items = ytd.TextureDict?.Textures?.data_items;
            if (items == null) return null;
            foreach (var texture in items)
            {
                if (texture == null || !string.Equals(texture.Name, wanted, StringComparison.OrdinalIgnoreCase)) continue;
                var stored = StoreBytes(sourcesDir, entry.Name, bytes);
                if (!sourceFiles.Contains(stored)) sourceFiles.Add(stored);
                sources.Add(new Dictionary<string, object> {
                    { "path", entry.Path }, { "entry", entry.Name },
                    { "bytes", bytes.Length }, { "sha256", Sha256(bytes) } });
                Decode(texture, Path.Combine(Path.GetDirectoryName(stored), "textures"), textures, undecoded);
                return new Dictionary<string, object> {
                    { "texture", wanted }, { "txd", best }, { "candidates", candidates.Count } };
            }
            return null;
        }

        static int CommonPrefix(string a, string b)
        {
            var n = 0;
            while (n < a.Length && n < b.Length && char.ToLowerInvariant(a[n]) == char.ToLowerInvariant(b[n])) n++;
            return n;
        }

        /// Decodes one texture to PNG, keeping the first definition of a name: a
        /// drawable's own dictionary is consulted before the archetype's, as the game
        /// does. Failures are recorded, never silently skipped.
        static void Decode(Texture texture, string directory,
            Dictionary<string, object> textures, List<object> undecoded)
        {
            if (texture == null || string.IsNullOrEmpty(texture.Name)) return;
            if (Path.GetFileName(texture.Name) != texture.Name)
                throw new ArgumentException("Unsafe texture name: " + texture.Name);
            var key = texture.Name.ToLowerInvariant();
            if (textures.ContainsKey(key)) return;

            byte[] pixels;
            try { pixels = DDSIO.GetPixels(texture, 0); }
            catch (Exception error)
            {
                undecoded.Add(new Dictionary<string, object> {
                    { "texture", texture.Name },
                    { "format", texture.Format.ToString() },
                    { "reason", error.Message } });
                return;
            }
            if (pixels == null) return;

            Directory.CreateDirectory(directory);
            var png = Path.Combine(directory, texture.Name + ".png");
            PngWriter.WriteRgba(png, texture.Width, texture.Height, ToRgba(pixels));
            textures[key] = png;
        }

        /// Textures stored inside the drawable itself rather than in a YTD.
        static IEnumerable<Texture> EmbeddedTextures(byte[] bytes, string extension)
        {
            foreach (var drawable in LoadDrawables(bytes, extension))
            {
                var dict = drawable?.ShaderGroup?.TextureDictionary;
                var items = dict?.Textures?.data_items;
                if (items == null) continue;
                foreach (var texture in items) yield return texture;
            }
        }

        static List<DrawableBase> LoadDrawables(byte[] bytes, string extension)
        {
            var drawables = new List<DrawableBase>();
            switch (extension)
            {
                case ".ydr":
                    var ydr = new YdrFile(); ydr.Load(bytes);
                    if (ydr.Drawable != null) drawables.Add(ydr.Drawable);
                    break;
                case ".yft":
                    var yft = new YftFile(); yft.Load(bytes);
                    if (yft.Fragment != null && yft.Fragment.Drawable != null)
                        drawables.Add(yft.Fragment.Drawable);
                    break;
                case ".ydd":
                    var ydd = new YddFile(); ydd.Load(bytes);
                    if (ydd.Dict != null) drawables.AddRange(ydd.Dict.Values);
                    break;
            }
            return drawables;
        }

        /// DDSIO returns pixels in the source format's channel order, which for the
        /// B8G8R8A8 family GTA V uses means blue first. Verified against a decoded game
        /// texture rather than assumed; see docs/manual-verification.md.
        static byte[] ToRgba(byte[] bgra)
        {
            var rgba = new byte[bgra.Length];
            for (var i = 0; i + 3 < bgra.Length; i += 4)
            {
                rgba[i] = bgra[i + 2];
                rgba[i + 1] = bgra[i + 1];
                rgba[i + 2] = bgra[i];
                rgba[i + 3] = bgra[i + 3];
            }
            return rgba;
        }

        static string StoreBytes(string sourcesDir, string name, byte[] bytes)
        {
            var folder = Path.Combine(sourcesDir, Sha256(bytes));
            Directory.CreateDirectory(folder);
            var target = Path.Combine(folder, name);
            if (!File.Exists(target)) File.WriteAllBytes(target, bytes);
            return target;
        }

        static string Sha256(byte[] bytes)
        {
            using (var hash = SHA256.Create())
                return Convert.ToHexString(hash.ComputeHash(bytes)).ToLowerInvariant();
        }
    }
}
