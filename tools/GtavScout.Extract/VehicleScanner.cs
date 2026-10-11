using System;
using System.Collections.Generic;
using System.IO;
using System.Xml;
using CodeWalker.GameFiles;

namespace GtavScout.Extract
{
    public sealed class VehicleScanResult
    {
        public List<Dictionary<string, object>> Models = new List<Dictionary<string, object>>();
        public Dictionary<string, object> Sizes = new Dictionary<string, object>();
        public int Files;
        public int Scanned;
        public int Overridden;
        public int WithoutDrawable;
    }

    /// Reads vehicle definitions out of vehicles.meta.
    ///
    /// Vehicles are not archetypes: nothing in any YTYP declares them, so a catalogue
    /// built from archetypes alone cannot find "prairie" even though prairie.yft is
    /// right there in the source. Their model, texture dictionary, make and class all
    /// live in vehicles.meta instead, which is plain XML.
    public static class VehicleScanner
    {
        public static VehicleScanResult Scan(IAssetSource source, List<Dictionary<string, object>> failures)
        {
            var result = new VehicleScanResult();
            var byName = new Dictionary<string, Dictionary<string, object>>(StringComparer.Ordinal);

            foreach (var entry in source.Enumerate(new[] { ".meta" }))
            {
                if (!entry.Name.Equals("vehicles.meta", StringComparison.Ordinal)) continue;
                result.Files++;

                XmlDocument document;
                try
                {
                    document = new XmlDocument();
                    document.LoadXml(System.Text.Encoding.UTF8.GetString(entry.Read()));
                }
                catch (Exception error)
                {
                    failures.Add(new Dictionary<string, object> {
                        { "source", entry.Path }, { "kind", "vehicles.meta" }, { "error", error.Message } });
                    continue;
                }

                var items = document.SelectNodes("//InitDatas/Item");
                if (items == null) continue;
                foreach (XmlNode node in items)
                {
                    result.Scanned++;
                    // Only a handful of fields matter here, and reading them directly
                    // keeps the scan working on DLC files that omit whole sections —
                    // CodeWalker's own loader expects a complete record and throws.
                    var name = Text(node, "modelName");
                    if (name.Length == 0) continue;
                    name = name.ToLowerInvariant();

                    var txd = Text(node, "txdName");
                    var record = new Dictionary<string, object> {
                        { "id", name },
                        { "name", name },
                        { "nameResolved", true },
                        { "dff", name },
                        { "txd", txd.Length == 0 ? name : txd.ToLowerInvariant() },
                        { "drawableDict", "0" },
                        { "source", entry.Path },
                        { "section", "CVehicleModelInfo" },
                        { "vehicleMake", Text(node, "vehicleMakeName") },
                        { "vehicleClass", Text(node, "vehicleClass") },
                        { "vehicleType", Text(node, "type") },
                        { "gameName", Text(node, "gameName") },
                        { "handlingId", Text(node, "handlingId") },
                        // The make and in-game name are what a person searches for, and
                        // neither appears in the model name: "prairie" never says Bollokan.
                        { "tags", Tags(node) }
                    };

                    if (byName.ContainsKey(name)) result.Overridden++;
                    byName[name] = record;
                }
            }

            foreach (var pair in byName)
            {
                result.Models.Add(pair.Value);
                var size = MeasureDrawable(source, (string)pair.Value["dff"]);
                if (size != null) result.Sizes[pair.Key] = size;
                else result.WithoutDrawable++;
            }
            result.Models.Sort((a, b) => StringComparer.Ordinal.Compare((string)a["id"], (string)b["id"]));
            return result;
        }

        /// Inner text of a direct child, or "" when the element is absent.
        static string Text(XmlNode node, string child)
        {
            var found = node.SelectSingleNode(child);
            return found == null ? string.Empty : (found.InnerText ?? string.Empty).Trim();
        }

        static object[] Tags(XmlNode node)
        {
            var tags = new List<object>();
            void add(string value)
            {
                if (string.IsNullOrEmpty(value)) return;
                value = value.Trim().ToLowerInvariant();
                if (value.Length == 0 || value == "null" || tags.Contains(value)) return;
                tags.Add(value);
            }
            add(Text(node, "vehicleMakeName"));
            add(Text(node, "gameName"));
            // VC_MUSCLE and VEHICLE_TYPE_CAR carry their meaning in the tail.
            add(Strip(Text(node, "vehicleClass"), "vc_"));
            add(Strip(Text(node, "type"), "vehicle_type_"));
            return tags.ToArray();
        }

        static string Strip(string value, string prefix)
        {
            if (string.IsNullOrEmpty(value)) return value;
            var lower = value.Trim().ToLowerInvariant();
            return lower.StartsWith(prefix, StringComparison.Ordinal) ? lower.Substring(prefix.Length) : lower;
        }

        /// Vehicles carry no bounding box in their metadata, so dimensions come from
        /// the drawable itself when it has been exported.
        static object MeasureDrawable(IAssetSource source, string assetName)
        {
            var entry = source.Find(assetName, AssetSources.Drawables);
            if (entry == null) return null;
            try
            {
                var bytes = entry.Read();
                DrawableBase drawable = null;
                switch (Path.GetExtension(entry.Name))
                {
                    case ".yft":
                        var yft = new YftFile(); yft.Load(bytes);
                        drawable = yft.Fragment?.Drawable;
                        break;
                    case ".ydr":
                        var ydr = new YdrFile(); ydr.Load(bytes);
                        drawable = ydr.Drawable;
                        break;
                }
                if (drawable == null) return null;
                var min = drawable.BoundingBoxMin;
                var max = drawable.BoundingBoxMax;
                var width = max.X - min.X;
                var depth = max.Y - min.Y;
                var height = max.Z - min.Z;
                if (width <= 0 || depth <= 0 || height <= 0) return null;
                return new Dictionary<string, object> {
                    { "width", width }, { "height", height }, { "depth", depth } };
            }
            catch (Exception)
            {
                return null;
            }
        }
    }
}
