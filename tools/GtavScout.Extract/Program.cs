using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;

namespace GtavScout.Extract
{
    public static class Json
    {
        public static string Write(object value)
        {
            var sb = new StringBuilder();
            Write(sb, value);
            return sb.ToString();
        }

        static void Write(StringBuilder sb, object value)
        {
            switch (value)
            {
                case null: sb.Append("null"); return;
                case string s: WriteString(sb, s); return;
                case bool b: sb.Append(b ? "true" : "false"); return;
                case float f: sb.Append(f.ToString("R", CultureInfo.InvariantCulture)); return;
                case double d: sb.Append(d.ToString("R", CultureInfo.InvariantCulture)); return;
                case IDictionary<string, object> map:
                    sb.Append('{');
                    var first = true;
                    foreach (var key in map.Keys.OrderBy(k => k, StringComparer.Ordinal))
                    {
                        if (!first) sb.Append(',');
                        first = false;
                        WriteString(sb, key);
                        sb.Append(':');
                        Write(sb, map[key]);
                    }
                    sb.Append('}');
                    return;
                case IEnumerable list:
                    sb.Append('[');
                    var firstItem = true;
                    foreach (var item in list)
                    {
                        if (!firstItem) sb.Append(',');
                        firstItem = false;
                        Write(sb, item);
                    }
                    sb.Append(']');
                    return;
                default:
                    sb.Append(Convert.ToString(value, CultureInfo.InvariantCulture));
                    return;
            }
        }

        static void WriteString(StringBuilder sb, string s)
        {
            sb.Append('"');
            foreach (var c in s)
            {
                if (c == '"') sb.Append("\\\"");
                else if (c == '\\') sb.Append("\\\\");
                else if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                else sb.Append(c);
            }
            sb.Append('"');
        }
    }

    public static class MiniJson
    {
        /// Reads a top-level {"KEY":[{...flat object of scalars...}]} document.
        public static List<Dictionary<string, string>> ReadObjectArray(string text, string key)
        {
            var doc = System.Text.Json.JsonDocument.Parse(text);
            var result = new List<Dictionary<string, string>>();
            foreach (var element in doc.RootElement.GetProperty(key).EnumerateArray())
            {
                var record = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (var property in element.EnumerateObject())
                {
                    if (property.Value.ValueKind == System.Text.Json.JsonValueKind.String)
                        record[property.Name] = property.Value.GetString();
                    else if (property.Value.ValueKind == System.Text.Json.JsonValueKind.Number)
                        record[property.Name] = property.Value.GetRawText();
                }
                result.Add(record);
            }
            return result;
        }
    }

    public static class Program
    {
        const string Usage =
            "Assets come from one of two sources:\n" +
            "  --asset-root DIR   a tree of files exported from the game (OpenIV)\n" +
            "  --game-root DIR    the game's RPF archives, when the NG keys can be derived\n" +
            "\n" +
            "gtav-scout-extract keys      --game-root DIR [--probe 1]\n" +
            "gtav-scout-extract inventory (--asset-root DIR | --game-root DIR) --out DIR\n" +
            "gtav-scout-extract extract   (--asset-root DIR | --game-root DIR) --out DIR\n" +
            "                             --catalog-root DIR --id ID [--id ID ...]\n" +
            "gtav-scout-extract ymap      --spec FILE.json --out DIR [--asset-root DIR]\n" +
            "gtav-scout-extract nearby    --asset-root DIR --at X,Y[,Z] [--radius 50] [--limit 200]\n" +
            "gtav-scout-extract inspect   --file FILE.(ydr|yft|ydd|ybn|ytyp|ymap)\n" +
            "gtav-scout-extract --self-test";

        public static int Main(string[] args)
        {
            try
            {
                if (args.Length == 0) { Console.Error.WriteLine(Usage); return 1; }
                if (args[0] == "--self-test")
                {
                    if (args.Length == 3 && args[1] == "--sample-out") SelfTest.SampleOutputDirectory = args[2];
                    return SelfTest.Run();
                }

                var options = ParseOptions(args.Skip(1).ToArray());
                switch (args[0])
                {
                    case "keys": return KeysCommand.Run(options);
                    case "inventory": return InventoryCommand.Run(options);
                    case "extract": return ExtractCommand.Run(options);
                    case "ymap": return YmapCommand.Run(options);
                    case "nearby": return NearbyCommand.Run(options);
                    case "inspect": return InspectCommand.Run(options);
                    default: Console.Error.WriteLine(Usage); return 1;
                }
            }
            catch (Exception error)
            {
                Console.Error.WriteLine(error.ToString());
                Console.WriteLine(Json.Write(new Dictionary<string, object> {
                    { "status", "failed" }, { "error", error.Message }
                }));
                return 1;
            }
        }

        public static Dictionary<string, List<string>> ParseOptions(string[] args)
        {
            var options = new Dictionary<string, List<string>>(StringComparer.Ordinal);
            for (var i = 0; i < args.Length; i++)
            {
                if (!args[i].StartsWith("--")) throw new ArgumentException("Unexpected argument: " + args[i]);
                if (i + 1 >= args.Length || args[i + 1].StartsWith("--"))
                    throw new ArgumentException("Option needs a value: " + args[i]);
                var name = args[i].Substring(2);
                if (!options.TryGetValue(name, out var values)) options[name] = values = new List<string>();
                values.Add(args[++i]);
            }
            return options;
        }

        public static string One(Dictionary<string, List<string>> options, string name)
        {
            if (!options.TryGetValue(name, out var values) || values.Count != 1)
                throw new ArgumentException("Exactly one --" + name + " is required");
            return values[0];
        }
    }
}
