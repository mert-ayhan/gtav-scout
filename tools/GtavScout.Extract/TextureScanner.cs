using System;
using System.Collections.Generic;
using System.IO;
using CodeWalker.GameFiles;

namespace GtavScout.Extract
{
    public static class TextureScanner
    {
        public static List<Dictionary<string, object>> Scan(
            IAssetSource source, List<Dictionary<string, object>> failures)
        {
            var textures = new List<Dictionary<string, object>>();

            foreach (var entry in source.Enumerate(new[] { ".ytd" }))
            {
                var dictionaryName = Path.GetFileNameWithoutExtension(entry.Name);

                YtdFile ytd;
                try
                {
                    ytd = new YtdFile();
                    ytd.Load(entry.Read());
                }
                catch (Exception error)
                {
                    failures.Add(new Dictionary<string, object> {
                        { "source", entry.Path }, { "kind", "ytd" }, { "error", error.Message } });
                    continue;
                }
                if (ytd.TextureDict == null) continue;
                var items = ytd.TextureDict.Textures;
                if (items == null || items.data_items == null) continue;

                // Texture identity is [source, txd, name], so the same name in two
                // dictionaries is two legitimate occurrences. Only a repeat inside one
                // dictionary would collide, and that is recorded as a failure.
                var seen = new HashSet<string>(StringComparer.Ordinal);
                foreach (var texture in items.data_items)
                {
                    if (texture == null || string.IsNullOrEmpty(texture.Name)) continue;
                    if (!seen.Add(texture.Name))
                    {
                        failures.Add(new Dictionary<string, object> {
                            { "source", entry.Path }, { "kind", "texture" },
                            { "error", "Repeated texture name in dictionary: " + texture.Name } });
                        continue;
                    }
                    textures.Add(new Dictionary<string, object> {
                        { "name", texture.Name },
                        { "txd", dictionaryName },
                        { "source", entry.Path },
                        { "width", (int)texture.Width },
                        { "height", (int)texture.Height },
                        { "format", texture.Format.ToString() }
                    });
                }
            }
            return textures;
        }
    }
}
