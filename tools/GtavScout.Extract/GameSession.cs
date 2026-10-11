using System;
using System.IO;
using CodeWalker.GameFiles;

namespace GtavScout.Extract
{
    public sealed class GameSession : IDisposable
    {
        public string GameRoot { get; private set; }
        public RpfManager Rpf { get; private set; }

        public static GameSession Open(string gameRoot, Action<string> log)
        {
            if (string.IsNullOrWhiteSpace(gameRoot)) throw new ArgumentException("Game root is required");
            gameRoot = Path.GetFullPath(gameRoot);
            if (!Directory.Exists(gameRoot)) throw new DirectoryNotFoundException("No such game root: " + gameRoot);

            var exe = Path.Combine(gameRoot, "GTA5.exe");
            if (!File.Exists(exe))
                throw new FileNotFoundException(
                    "GTA5.exe not found. This adapter targets the Legacy edition; Enhanced (GTA5_Enhanced.exe) is unsupported.", exe);

            LoadKeys(File.ReadAllBytes(exe), log);

            var manager = new RpfManager();
            manager.Init(gameRoot, false, log, log);
            manager.BuildBaseJenkIndex();

            return new GameSession { GameRoot = gameRoot, Rpf = manager };
        }

        /// True when only the AES key was recovered, so NG-encrypted entries cannot be read.
        public static bool NgKeysMissing { get; private set; }

        /// CodeWalker locates GTA V's key material by hashing candidate byte ranges of
        /// GTA5.exe. A game update moves that material, so a CodeWalker checkout older than
        /// the installed build finds the AES key but none of the NG keys and tables, and
        /// GTA5Keys.Generate then throws on a null table. Fall back to the AES-only path and
        /// record the limitation instead of failing outright: whether NG matters depends on
        /// what the archives actually use, which the caller can then measure.
        static void LoadKeys(byte[] exeData, Action<string> log)
        {
            try
            {
                GTA5Keys.Generate(exeData, log);
                NgKeysMissing = false;
            }
            catch (Exception error)
            {
                log("NG key material not found in this executable (" + error.Message +
                    "); continuing with the AES key only. Update the CodeWalker checkout if " +
                    "NG-encrypted entries fail to read.");
                GTA5Keys.GenerateV2(exeData, log);
                NgKeysMissing = true;
                if (GTA5Keys.PC_AES_KEY == null)
                    throw new InvalidOperationException(
                        "Neither the NG key material nor the AES key was found in GTA5.exe. " +
                        "This CodeWalker checkout cannot read this game build.");
            }
        }

        public void Dispose()
        {
            Rpf = null;
        }
    }
}
