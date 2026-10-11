using System;
using System.Collections.Generic;
using System.IO;
using CodeWalker.GameFiles;

namespace GtavScout.Extract
{
    /// One asset file, wherever it came from.
    public sealed class AssetEntry
    {
        /// Stable, source-relative identifier recorded as a record's provenance:
        /// an RPF-internal path, or a path relative to the extracted asset root.
        public string Path;
        /// Lowercased file name including its extension, e.g. "prop_bench_01a.ytd".
        public string Name;
        public Func<byte[]> Read;
    }

    /// Where asset bytes come from. The scanners are written against this and never
    /// learn whether they are reading archives or a directory of extracted files.
    public interface IAssetSource : IDisposable
    {
        string Describe();
        /// Every asset file whose name ends with one of `extensions` (lowercase, dotted).
        IEnumerable<AssetEntry> Enumerate(string[] extensions);
        /// The single entry named `baseName` + one of `extensions`, or null.
        AssetEntry Find(string baseName, string[] extensions);
    }

    /// Reads assets already exported from the game, typically with OpenIV.
    ///
    /// This is the working path: CodeWalker cannot derive the NG keys for recent game
    /// builds, and every CodeWalker format parser accepts raw bytes through Load(byte[]),
    /// so the archive layer is the only part that needs replacing.
    public sealed class DirectoryAssetSource : IAssetSource
    {
        readonly string _root;
        readonly Dictionary<string, List<string>> _byName =
            new Dictionary<string, List<string>>(StringComparer.Ordinal);
        // Files whose names differ only by an exporter-added "(N)" suffix, grouped by
        // the name they collided on.
        readonly Dictionary<string, List<string>> _byBaseName =
            new Dictionary<string, List<string>>(StringComparer.Ordinal);

        /// How many redundant copies the last Enumerate call skipped.
        public int CollapsedCopies { get; private set; }

        public DirectoryAssetSource(string assetRoot)
        {
            _root = Path.GetFullPath(assetRoot);
            if (!Directory.Exists(_root))
                throw new DirectoryNotFoundException("No such asset root: " + _root);

            foreach (var file in Directory.EnumerateFiles(_root, "*", SearchOption.AllDirectories))
            {
                var name = Path.GetFileName(file).ToLowerInvariant();
                if (!_byName.TryGetValue(name, out var paths)) _byName[name] = paths = new List<string>();
                paths.Add(file);

                var baseName = StripCopySuffix(Path.GetFileNameWithoutExtension(name))
                               + Path.GetExtension(name);
                if (!_byBaseName.TryGetValue(baseName, out var group))
                    _byBaseName[baseName] = group = new List<string>();
                group.Add(file);
            }
            if (_byName.Count == 0)
                throw new InvalidOperationException("Asset root contains no files: " + _root);

            PrimeNameIndex();
        }

        /// Archetypes, texture dictionaries and map entities refer to each other by
        /// Jenkins hash, and CodeWalker resolves those through a global index it normally
        /// fills from RPF entry names. Reading loose files skips that, and every name in
        /// the catalogue then comes out as a bare number.
        ///
        /// Asset file names are the same strings the hashes were made from, so the file
        /// listing rebuilds most of the index. CodeWalker's own strings.txt adds the
        /// names that belong to no file.
        void PrimeNameIndex()
        {
            foreach (var name in _byBaseName.Keys)
                JenkIndex.Ensure(Path.GetFileNameWithoutExtension(name));

            for (var i = 0; i < 100; i++) JenkIndex.Ensure(i.ToString("00"));

            var assembly = System.Reflection.Assembly.GetExecutingAssembly().Location;
            var strings = Path.Combine(Path.GetDirectoryName(assembly) ?? ".", "strings.txt");
            if (!File.Exists(strings)) return;
            foreach (var line in File.ReadAllLines(strings))
            {
                var value = line == null ? null : line.Trim();
                if (string.IsNullOrEmpty(value) || value.StartsWith("//")) continue;
                JenkIndex.Ensure(value);
            }
        }

        /// Exporters that flatten archives into one directory rename collisions to
        /// "name(1).ext". The suffix says nothing about which archive a file came from,
        /// so it is only ever used to recognise that two files collided.
        public static string StripCopySuffix(string stem)
        {
            if (stem.Length < 4 || stem[stem.Length - 1] != ')') return stem;
            var open = stem.LastIndexOf('(');
            if (open <= 0 || open == stem.Length - 2) return stem;
            for (var i = open + 1; i < stem.Length - 1; i++)
                if (!char.IsDigit(stem[i])) return stem;
            return stem.Substring(0, open);
        }

        public string Describe() { return "directory:" + _root; }

        public IEnumerable<AssetEntry> Enumerate(string[] extensions)
        {
            CollapsedCopies = 0;

            foreach (var pair in _byBaseName)
            {
                var matches = false;
                foreach (var extension in extensions)
                    if (pair.Key.EndsWith(extension, StringComparison.Ordinal)) { matches = true; break; }
                if (!matches) continue;

                var group = pair.Value;
                if (group.Count == 1)
                {
                    yield return Entry(group[0]);
                    continue;
                }

                // A flattened export repeats identical files under different names. Yield
                // one entry per distinct content so placements are not counted twice and
                // archetypes are not re-declared, while genuine variants all survive.
                var seen = new HashSet<string>(StringComparer.Ordinal);
                var ordered = new List<string>(group);
                ordered.Sort(StringComparer.Ordinal);
                foreach (var file in ordered)
                {
                    string identity;
                    try { identity = new FileInfo(file).Length + ":" + Sha256(file); }
                    catch (IOException) { identity = Guid.NewGuid().ToString(); }
                    if (!seen.Add(identity)) { CollapsedCopies++; continue; }
                    yield return Entry(file);
                }
            }
        }

        AssetEntry Entry(string file)
        {
            // Name is the game's own file name, with any exporter "(N)" suffix removed:
            // it becomes the texture dictionary name and the map name in the catalogue,
            // where "prop_bench_01a(1)" would be wrong. Path keeps the real file.
            var actual = Path.GetFileName(file).ToLowerInvariant();
            return new AssetEntry {
                Path = GetRelativePath(file),
                Name = StripCopySuffix(Path.GetFileNameWithoutExtension(actual))
                       + Path.GetExtension(actual),
                Read = () => File.ReadAllBytes(file)
            };
        }

        static string Sha256(string file)
        {
            using (var hash = System.Security.Cryptography.SHA256.Create())
            using (var stream = File.OpenRead(file))
                return Convert.ToHexString(hash.ComputeHash(stream));
        }

        public AssetEntry Find(string baseName, string[] extensions)
        {
            foreach (var extension in extensions)
            {
                if (!_byName.TryGetValue(baseName.ToLowerInvariant() + extension, out var paths)) continue;
                // Several archives can export the same name; the first in sorted order is
                // chosen so a rerun picks the same file, and the count is reported by callers.
                paths.Sort(StringComparer.Ordinal);
                return Entry(paths[0]);
            }
            return null;
        }

        string GetRelativePath(string file)
        {
            return Path.GetRelativePath(_root, file).Replace('\\', '/');
        }

        public void Dispose() { }
    }

    /// Reads assets straight out of the game's RPF archives. Requires the NG key
    /// material, which recent game builds no longer expose to CodeWalker; kept so a
    /// future CodeWalker update restores fully automatic operation unchanged.
    public sealed class RpfAssetSource : IAssetSource
    {
        readonly GameSession _session;

        public RpfAssetSource(GameSession session) { _session = session; }

        public string Describe() { return "rpf:" + _session.GameRoot; }

        public IEnumerable<AssetEntry> Enumerate(string[] extensions)
        {
            foreach (var rpf in _session.Rpf.AllRpfs)
            {
                if (rpf.AllEntries == null) continue;
                foreach (var entry in rpf.AllEntries)
                {
                    var file = entry as RpfFileEntry;
                    if (file == null || file.NameLower == null) continue;
                    var matches = false;
                    foreach (var extension in extensions)
                        if (file.NameLower.EndsWith(extension, StringComparison.Ordinal)) { matches = true; break; }
                    if (!matches) continue;

                    var captured = file;
                    yield return new AssetEntry {
                        Path = rpf.Path + "/" + captured.Path,
                        Name = captured.NameLower,
                        Read = () => captured.File.ExtractFile(captured)
                    };
                }
            }
        }

        public AssetEntry Find(string baseName, string[] extensions)
        {
            var lower = baseName.ToLowerInvariant();
            foreach (var extension in extensions)
            {
                if (!_session.Rpf.EntryDict.TryGetValue(lower + extension, out var entry)) continue;
                var file = entry as RpfFileEntry;
                if (file == null) continue;
                return new AssetEntry {
                    Path = file.File.Path + "/" + file.Path,
                    Name = file.NameLower,
                    Read = () => file.File.ExtractFile(file)
                };
            }
            return null;
        }

        public void Dispose() { _session.Dispose(); }
    }

    public static class AssetSources
    {
        public static readonly string[] Drawables = { ".ydr", ".ydd", ".yft" };

        /// Opens whichever source the options ask for. --asset-root selects the
        /// directory source; --game-root selects the RPF source and fails loudly when
        /// the key material this build needs is unavailable.
        public static IAssetSource Open(Dictionary<string, List<string>> options, Action<string> log)
        {
            var hasAssetRoot = options.ContainsKey("asset-root");
            var hasGameRoot = options.ContainsKey("game-root");
            if (hasAssetRoot == hasGameRoot)
                throw new ArgumentException("Pass exactly one of --asset-root (extracted files) or --game-root (RPF archives)");

            if (hasAssetRoot) return new DirectoryAssetSource(Program.One(options, "asset-root"));

            var session = GameSession.Open(Program.One(options, "game-root"), log);
            if (GameSession.NgKeysMissing)
            {
                session.Dispose();
                throw new InvalidOperationException(
                    "This game build does not expose the NG key material CodeWalker needs, so its " +
                    "archives cannot be opened. Export the assets with OpenIV and pass --asset-root " +
                    "instead. Run `keys --game-root DIR --probe 1` for the measured detail.");
            }
            return new RpfAssetSource(session);
        }
    }
}
