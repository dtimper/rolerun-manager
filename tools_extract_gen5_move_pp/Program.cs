using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using PKHeX.Core;

class Program
{
    static void Main(string[] args)
    {
        var salida = args.Length > 0 ? args[0] : "b2w2_move_pp.json";
        ReadOnlySpan<byte> tabla = MoveInfo.GetPPTable(EntityContext.Gen5);
        var pp = new Dictionary<string, int>();
        for (int id = 1; id < tabla.Length; id++)
            pp[id.ToString()] = tabla[id];

        var documento = new
        {
            version = "b2w2-gen5",
            source = "PKHeX.Core " + typeof(PK5).Assembly.GetName().Version + " · MoveInfo.GetPPTable(EntityContext.Gen5)",
            note = "PP base de quinta generacion. Extraido del mismo PKHeX.Core.dll que usa el motor de guardados de RoleRun.",
            pp,
        };
        var json = JsonSerializer.Serialize(documento, new JsonSerializerOptions { WriteIndented = false });
        File.WriteAllText(salida, json, new UTF8Encoding(false));

        Console.WriteLine("movimientos: " + pp.Count);
        Console.WriteLine("id maximo  : " + (tabla.Length - 1));
        foreach (var id in new[] { 1, 33, 39, 52, 84, 165, 559 })
            Console.WriteLine($"  PP #{id} = {(id < tabla.Length ? tabla[id] : -1)}");
        Console.WriteLine("escrito en " + Path.GetFullPath(salida));
    }
}
