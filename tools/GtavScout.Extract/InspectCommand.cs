using System;
using System.Collections.Generic;
using System.IO;
using CodeWalker.GameFiles;

namespace GtavScout.Extract
{
    /// Reports what is actually inside an exported game file.
    ///
    /// An export that "succeeded" can still have dropped the collision, flattened an
    /// emissive shader to default.sps, or embedded no textures. Those only show up
    /// by reading the file back, so this reads it with CodeWalker — not with the
    /// Blender add-on that wrote it — and lists shaders, textures, bounds and lights.
    public static class InspectCommand
    {
        public static int Run(Dictionary<string, List<string>> options)
        {
            var path = Path.GetFullPath(Program.One(options, "file"));
            // Shader file names are stored as hashes; seed the index so a report says
            // "emissive.sps" instead of a number nobody can check.
            var names = Path.Combine(AppContext.BaseDirectory, "shader-names.txt");
            if (File.Exists(names))
                foreach (var line in File.ReadAllLines(names))
                    if (line.Length > 0 && !line.StartsWith("//"))
                    {
                        JenkIndex.Ensure(line.Trim());
                        JenkIndex.Ensure(Path.GetFileNameWithoutExtension(line.Trim()));
                    }
            var bytes = File.ReadAllBytes(path);
            object report;
            switch (Path.GetExtension(path).ToLowerInvariant())
            {
                case ".ydr":
                    var ydr = new YdrFile(); ydr.Load(bytes);
                    report = Drawable(ydr.Drawable);
                    break;
                case ".yft":
                    var yft = new YftFile(); yft.Load(bytes);
                    report = Drawable(yft.Fragment?.Drawable);
                    break;
                case ".ydd":
                    var ydd = new YddFile(); ydd.Load(bytes);
                    var list = new List<object>();
                    if (ydd.Dict != null) foreach (var d in ydd.Dict.Values) list.Add(Drawable(d));
                    report = new Dictionary<string, object> { { "drawables", list } };
                    break;
                case ".ybn":
                    var ybn = new YbnFile(); ybn.Load(bytes);
                    report = new Dictionary<string, object> { { "bound", Bound(ybn.Bounds) } };
                    break;
                case ".ytyp":
                    var ytyp = new YtypFile(); ytyp.Load(bytes);
                    var arch = new List<object>();
                    foreach (var a in ytyp.AllArchetypes ?? new Archetype[0])
                    {
                        var def = a._BaseArchetypeDef;
                        arch.Add(new Dictionary<string, object> {
                            { "name", Hash(def.name) }, { "assetName", Hash(def.assetName) },
                            { "textureDictionary", Hash(def.textureDictionary) },
                            { "physicsDictionary", Hash(def.physicsDictionary) },
                            { "lodDist", def.lodDist }, { "flags", def.flags },
                            { "bbMin", Vec(def.bbMin) }, { "bbMax", Vec(def.bbMax) } });
                    }
                    report = new Dictionary<string, object> { { "archetypes", arch } };
                    break;
                case ".ymap":
                    var ymap = new YmapFile(); ymap.Load(bytes);
                    var ents = new List<object>();
                    foreach (var e in ymap.AllEntities ?? new YmapEntityDef[0])
                        ents.Add(new Dictionary<string, object> {
                            { "archetype", Hash(e.CEntityDef.archetypeName) },
                            { "position", Vec(e.Position) }, { "lodDist", e.CEntityDef.lodDist },
                            { "lodLevel", e.CEntityDef.lodLevel.ToString() }, { "flags", e.CEntityDef.flags } });
                    report = new Dictionary<string, object> {
                        { "entities", ents }, { "flags", ymap._CMapData.flags },
                        { "contentFlags", ymap._CMapData.contentFlags },
                        { "entitiesExtentsMin", Vec(ymap._CMapData.entitiesExtentsMin) },
                        { "entitiesExtentsMax", Vec(ymap._CMapData.entitiesExtentsMax) } };
                    break;
                default:
                    throw new ArgumentException("inspect reads .ydr .yft .ydd .ybn .ytyp .ymap");
            }
            Console.WriteLine(Json.Write(new Dictionary<string, object> {
                { "file", path }, { "bytes", bytes.Length }, { "content", report } }));
            return 0;
        }

        static object Drawable(DrawableBase drawable)
        {
            if (drawable == null) return null;
            var triangles = 0L; var geometries = 0;
            foreach (var model in drawable.AllModels ?? new DrawableModel[0])
                foreach (var geometry in model?.Geometries ?? new DrawableGeometry[0])
                {
                    geometries++;
                    triangles += geometry.IndicesCount / 3;
                }

            var shaders = new List<object>();
            foreach (var shader in drawable.ShaderGroup?.Shaders?.data_items ?? new ShaderFX[0])
            {
                if (shader == null) continue;
                var textures = new List<object>();
                foreach (var p in shader.ParametersList?.Parameters ?? new ShaderParameter[0])
                    if (p != null && p.DataType == 0 && p.Data is TextureBase t) textures.Add(t.Name);
                shaders.Add(new Dictionary<string, object> {
                    { "file", shader.FileName.ToString() }, { "name", shader.Name.ToString() },
                    { "textures", textures } });
            }

            var embedded = new List<object>();
            foreach (var t in drawable.ShaderGroup?.TextureDictionary?.Textures?.data_items ?? new Texture[0])
                if (t != null) embedded.Add(t.Name + " " + t.Width + "x" + t.Height + " " + t.Format);

            var lights = (drawable as Drawable)?.LightAttributes?.data_items;
            return new Dictionary<string, object> {
                { "models", drawable.AllModels?.Length ?? 0 },
                { "geometries", geometries }, { "triangles", triangles },
                { "bbMin", Vec(drawable.BoundingBoxMin) }, { "bbMax", Vec(drawable.BoundingBoxMax) },
                { "shaders", shaders }, { "embeddedTextures", embedded },
                { "bound", Bound((drawable as Drawable)?.Bound) },
                { "lights", lights?.Length ?? 0 } };
        }

        static object Bound(Bounds bound)
        {
            if (bound == null) return null;
            var node = new Dictionary<string, object> { { "type", bound.Type.ToString() } };
            if (bound is BoundGeometry geometry)
            {
                node["vertices"] = geometry.Vertices?.Length ?? 0;
                node["polygons"] = geometry.Polygons?.Length ?? 0;
                var materials = new List<object>();
                foreach (var m in geometry.Materials ?? new BoundMaterial_s[0])
                    materials.Add((int)m.Type);
                node["materials"] = materials;
            }
            if (bound is BoundComposite composite)
            {
                var children = new List<object>();
                foreach (var child in composite.Children?.data_items ?? new Bounds[0])
                    children.Add(Bound(child));
                node["children"] = children;
            }
            return node;
        }

        static string Hash(MetaHash h) => h.Hash == 0 ? "" : h.ToString();
        static object Vec(SharpDX.Vector3 v) => new object[] { v.X, v.Y, v.Z };
    }
}
