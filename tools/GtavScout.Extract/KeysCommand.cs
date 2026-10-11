using System;
using System.Collections.Generic;
using CodeWalker.GameFiles;

namespace GtavScout.Extract
{
    public static class KeysCommand
    {
        public static int Run(Dictionary<string, List<string>> options)
        {
            var gameRoot = Program.One(options, "game-root");
            if (options.ContainsKey("probe")) return Probe(gameRoot);
            using (var session = GameSession.Open(gameRoot, m => Console.Error.WriteLine(m)))
            {
                Console.WriteLine(Json.Write(new Dictionary<string, object> {
                    { "status", "ok" },
                    { "ngKeysMissing", GameSession.NgKeysMissing },
                    { "gameRoot", session.GameRoot },
                    { "aesKeyBytes", GTA5Keys.PC_AES_KEY == null ? 0 : GTA5Keys.PC_AES_KEY.Length },
                    { "ngKeyCount", GTA5Keys.PC_NG_KEYS == null ? 0 : GTA5Keys.PC_NG_KEYS.Length },
                    { "mountedArchives", session.Rpf.AllRpfs.Count },
                    { "indexedEntries", session.Rpf.EntryDict.Count }
                }));
            }
            return 0;
        }

        /// Reports how much of the exe's key material CodeWalker's hashes still match.
        /// A game update changes these tables, so a partial match is the signal that this
        /// CodeWalker checkout predates the installed game.
        static int Probe(string gameRoot)
        {
            var exe = System.IO.Path.Combine(System.IO.Path.GetFullPath(gameRoot), "GTA5.exe");
            var bytes = System.IO.File.ReadAllBytes(exe);
            var stream = new System.IO.MemoryStream(bytes);

            var aes = HashSearch.SearchHash(stream, GTA5KeyHashes.PC_AES_KEY_HASH, 0x20);
            var ngKeys = HashSearch.SearchHashes(stream, GTA5KeyHashes.PC_NG_KEY_HASHES, 0x110);
            var tables = HashSearch.SearchHashes(stream, GTA5KeyHashes.PC_NG_DECRYPT_TABLE_HASHES, 0x400);
            var lut = HashSearch.SearchHash(stream, GTA5KeyHashes.PC_LUT_HASH, 0x100);

            var foundKeys = 0;
            foreach (var k in ngKeys) if (k != null) foundKeys++;
            var foundTables = 0;
            foreach (var t in tables) if (t != null) foundTables++;

            // CodeWalker's block loop is `Parallel.For(0, stream.Length / BLOCK_LENGTH)`, so
            // integer division leaves the exe's final partial megabyte unscanned. Rescan a
            // padded copy to find out whether the missing NG material simply lives there.
            var padded = new byte[((bytes.Length / 1048576) + 2) * 1048576];
            Buffer.BlockCopy(bytes, 0, padded, 0, bytes.Length);
            var paddedStream = new System.IO.MemoryStream(padded);
            var tailKeys = HashSearch.SearchHashes(paddedStream, GTA5KeyHashes.PC_NG_KEY_HASHES, 0x110);
            var tailTables = HashSearch.SearchHashes(paddedStream, GTA5KeyHashes.PC_NG_DECRYPT_TABLE_HASHES, 0x400);
            var paddedKeys = 0;
            foreach (var k in tailKeys) if (k != null) paddedKeys++;
            var paddedTables = 0;
            foreach (var t in tailTables) if (t != null) paddedTables++;

            Console.WriteLine(Json.Write(new Dictionary<string, object> {
                { "status", "probe" },
                { "exe", exe },
                { "exeBytes", bytes.Length },
                { "scannedBytes", (bytes.Length / 1048576) * 1048576 },
                { "unscannedTailBytes", bytes.Length - (bytes.Length / 1048576) * 1048576 },
                { "aesKeyFound", aes != null },
                { "ngKeysFound", foundKeys },
                { "ngKeysExpected", GTA5KeyHashes.PC_NG_KEY_HASHES.Length },
                { "ngDecryptTablesFound", foundTables },
                { "ngDecryptTablesExpected", GTA5KeyHashes.PC_NG_DECRYPT_TABLE_HASHES.Length },
                { "lutFound", lut != null },
                { "ngKeysFoundWhenPadded", paddedKeys },
                { "ngDecryptTablesFoundWhenPadded", paddedTables }
            }));
            return 0;
        }
    }
}
