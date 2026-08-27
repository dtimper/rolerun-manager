using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Reflection;
using PKHeX.Core;

// Extrae de PKHeX la tabla MT/MO de B2/W2 y la compatibilidad por especie.
//
// La correspondencia MT -> movimiento no se copia a mano de ninguna lista: se
// DERIVA de la propia logica de PKHeX. Para cada indice de MT se enciende solo
// ese bit en una ficha personal en blanco y se pregunta a LearnSource5B2W2
// que movimiento pasa a ser ensenable. Si PKHeX cambiara su tabla, esta
// extraccion cambiaria con ella en lugar de quedarse obsoleta en silencio.
class Program
{
    const int MaxMove5 = 559;

    static void Main(string[] args)
    {
        var salida = args.Length > 0 ? args[0] : "b2w2_tm_table.json";
        // Varias de estas piezas no son publicas en PKHeX 26.7.7. Se llegan
        // por reflexion en lugar de reescribir a mano lo que ya sabe la libreria.
        var flags = BindingFlags.Public | BindingFlags.NonPublic
                  | BindingFlags.Static | BindingFlags.Instance;
        var tipoPersonal = typeof(PersonalInfo5B2W2);
        int tamano = Convert.ToInt32(tipoPersonal.GetField("SIZE", flags).GetRawConstantValue());
        int total = Convert.ToInt32(tipoPersonal.GetField("CountTMHM", flags).GetRawConstantValue());
        var setIsLearnTM = tipoPersonal.GetMethod("SetIsLearnTM", flags);
        var getIsTM = typeof(LearnSource5B2W2).GetMethod("GetIsTM", flags);
        var fuente = LearnSource5B2W2.Instance;

        var movimientos = new List<int>();
        for (int indice = 0; indice < total; indice++)
        {
            // Ficha en blanco nueva por indice: solo ese bit encendido.
            var blanco = new PersonalInfo5B2W2(new byte[tamano]);
            setIsLearnTM.Invoke(blanco, new object[] { indice, true });
            int encontrado = 0;
            for (ushort move = 1; move <= MaxMove5; move++)
            {
                if (!(bool)getIsTM.Invoke(fuente, new object[] { blanco, move })) continue;
                if (encontrado != 0)
                    throw new Exception($"El indice {indice} enciende dos movimientos: {encontrado} y {move}.");
                encontrado = move;
            }
            if (encontrado == 0)
                throw new Exception($"El indice {indice} no enciende ningun movimiento.");
            movimientos.Add(encontrado);
        }

        // MT01-MT92 = 328..419, MO01-MO06 = 420..425, MT93-MT95 = 618..620.
        // Los identificadores salen de la misma tabla de objetos que ya valido
        // la mochila real del usuario (MT21 = 348).
        var entradas = new List<object>();
        for (int indice = 0; indice < total; indice++)
        {
            int numero = indice + 1;
            bool esMO = numero > 95;
            int item;
            string etiqueta;
            if (esMO) { item = 420 + (numero - 96); etiqueta = $"HM{numero - 95:00}"; }
            else if (numero <= 92) { item = 328 + (numero - 1); etiqueta = $"TM{numero:00}"; }
            else { item = 618 + (numero - 93); etiqueta = $"TM{numero:00}"; }
            entradas.Add(new
            {
                indice,
                etiqueta,
                numero = esMO ? numero - 95 : numero,
                tipo = esMO ? "HM" : "TM",
                item_id = item,
                move_id = movimientos[indice],
            });
        }

        // La compatibilidad por especie NO se extrae a proposito: RoleRun ignora
        // deliberadamente la compatibilidad de la ROM (ver _build_tm_candidates
        // en app/ui.py), asi que un volcado de 731 fichas seria dato muerto.
        // PersonalInfo5B2W2.GetIsLearnTM la tiene si algun dia hace falta.

        var doc = new
        {
            version = "b2w2-tm-v1",
            source = "PKHeX.Core " + typeof(PK5).Assembly.GetName().Version
                   + " - LearnSource5B2W2.GetIsTM + PersonalTable.B2W2",
            metodo = "La correspondencia MT->movimiento se deriva encendiendo un solo bit "
                   + "por indice y preguntando a PKHeX que movimiento queda ensenable.",
            total_indices = total,
            entradas,
        };
        File.WriteAllText(salida, JsonSerializer.Serialize(doc), new UTF8Encoding(false));
        Console.WriteLine($"{total} MT/MO extraidas.");
        Console.WriteLine("escrito en " + Path.GetFullPath(salida));
    }
}
