using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.Json;
using PKHeX.Core;

class Program
{
    static void Main(string[] args)
    {
        var salida = args.Length > 0 ? args[0] : "b2w2_bag_layout.json";
        var sav = new SAV5B2W2();
        var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
        var bolsillos = new List<object>();
        foreach (var p in sav.Inventory.Pouches)
        {
            var t = p.GetType();
            int offset = Convert.ToInt32(
                t.GetProperty("Offset", flags)?.GetValue(p)
                ?? t.GetField("Offset", flags)?.GetValue(p) ?? 0);
            var legales = new List<int>();
            foreach (var id in sav.Inventory.Info.GetItems(p.Type)) legales.Add(id);
            legales.Sort();
            bolsillos.Add(new
            {
                tipo = p.Type.ToString(),
                desplazamiento = offset,
                huecos = legales.Count,
                items_legales = legales,
            });
            Console.WriteLine($"  {p.Type,-10} +{offset,5}  huecos={legales.Count,4}");
        }
        var doc = new
        {
            version = "b2w2-gen5",
            source = "PKHeX.Core " + typeof(PK5).Assembly.GetName().Version
                   + " - SAV5B2W2.Inventory.Pouches (Offset e items legales)",
            note = "Desplazamientos relativos al inicio del bolsillo Items dentro del bloque de mochila. "
                 + "Cada hueco son dos u16: identificador y cantidad.",
            bolsillos,
        };
        File.WriteAllText(salida, JsonSerializer.Serialize(doc), new UTF8Encoding(false));
        Console.WriteLine("escrito en " + Path.GetFullPath(salida));
    }
}
