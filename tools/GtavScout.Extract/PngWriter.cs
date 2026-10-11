using System;
using System.IO;
using System.IO.Compression;

namespace GtavScout.Extract
{
    /// Minimal 8-bit RGBA PNG encoder. Keeping this in-tree is what lets the whole
    /// extraction side be one .NET tool with no Node runtime and no image library.
    public static class PngWriter
    {
        public static void WriteRgba(string path, int width, int height, byte[] rgba)
        {
            if (width <= 0 || height <= 0)
                throw new ArgumentException("Bad image size " + width + "x" + height);
            if (rgba == null || rgba.Length < width * height * 4)
                throw new ArgumentException("RGBA buffer too small for " + width + "x" + height);

            var stride = width * 4;
            var raw = new byte[height * (stride + 1)];
            for (var y = 0; y < height; y++)
            {
                raw[y * (stride + 1)] = 0; // filter type: None
                Buffer.BlockCopy(rgba, y * stride, raw, y * (stride + 1) + 1, stride);
            }

            using (var file = File.Create(path))
            {
                file.Write(new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A }, 0, 8);

                var ihdr = new byte[13];
                WriteBigEndian(ihdr, 0, (uint)width);
                WriteBigEndian(ihdr, 4, (uint)height);
                ihdr[8] = 8;  // bit depth
                ihdr[9] = 6;  // colour type: RGBA
                WriteChunk(file, "IHDR", ihdr);
                WriteChunk(file, "IDAT", Zlib(raw));
                WriteChunk(file, "IEND", new byte[0]);
            }
        }

        static byte[] Zlib(byte[] data)
        {
            using (var buffer = new MemoryStream())
            {
                buffer.WriteByte(0x78);
                buffer.WriteByte(0x01);
                using (var deflate = new DeflateStream(buffer, CompressionLevel.Optimal, true))
                    deflate.Write(data, 0, data.Length);
                var adler = Adler32(data);
                buffer.WriteByte((byte)(adler >> 24));
                buffer.WriteByte((byte)(adler >> 16));
                buffer.WriteByte((byte)(adler >> 8));
                buffer.WriteByte((byte)adler);
                return buffer.ToArray();
            }
        }

        static uint Adler32(byte[] data)
        {
            uint a = 1, b = 0;
            foreach (var value in data)
            {
                a = (a + value) % 65521;
                b = (b + a) % 65521;
            }
            return (b << 16) | a;
        }

        static void WriteChunk(Stream stream, string type, byte[] data)
        {
            var length = new byte[4];
            WriteBigEndian(length, 0, (uint)data.Length);
            stream.Write(length, 0, 4);

            var body = new byte[4 + data.Length];
            for (var i = 0; i < 4; i++) body[i] = (byte)type[i];
            Buffer.BlockCopy(data, 0, body, 4, data.Length);
            stream.Write(body, 0, body.Length);

            var crc = new byte[4];
            WriteBigEndian(crc, 0, Crc32(body));
            stream.Write(crc, 0, 4);
        }

        static void WriteBigEndian(byte[] target, int offset, uint value)
        {
            target[offset] = (byte)(value >> 24);
            target[offset + 1] = (byte)(value >> 16);
            target[offset + 2] = (byte)(value >> 8);
            target[offset + 3] = (byte)value;
        }

        static readonly uint[] CrcTable = BuildCrcTable();

        static uint[] BuildCrcTable()
        {
            var table = new uint[256];
            for (uint n = 0; n < 256; n++)
            {
                var c = n;
                for (var k = 0; k < 8; k++) c = (c & 1) != 0 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
                table[n] = c;
            }
            return table;
        }

        static uint Crc32(byte[] data)
        {
            var c = 0xFFFFFFFFu;
            foreach (var value in data) c = CrcTable[(c ^ value) & 0xFF] ^ (c >> 8);
            return c ^ 0xFFFFFFFFu;
        }
    }
}
