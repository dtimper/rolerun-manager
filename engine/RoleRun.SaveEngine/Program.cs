using System.Text;
using System.Text.Json;
using PKHeX.Core;

namespace RoleRun.SaveEngine;

internal static class Program
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = false,
    };

    public static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        try
        {
            if (args.Length == 0)
                return Fail("Uso: RoleRun.SaveEngine <read|read-boxes|read-inventory|replace-move|teach-tm|set-role|set-box-role|set-item|set-money|party-to-box|box-to-party|swap-party-box|valid-moves|export-moves> [argumentos]");

            return args[0].ToLowerInvariant() switch
            {
                "read" => Read(args),
                "read-boxes" => ReadBoxes(args),
                "read-inventory" => ReadInventory(args),
                "replace-move" => ReplaceMove(args),
                "teach-tm" => TeachTM(args),
                "set-role" => SetRole(args),
                "set-box-role" => SetBoxRole(args),
                "set-item" => SetItem(args),
                "set-money" => SetMoney(args),
                "party-to-box" => PartyToBox(args),
                "box-to-party" => BoxToParty(args),
                "swap-party-box" => SwapPartyBox(args),
                "valid-moves" => ValidMoves(args),
                "export-moves" => ExportMoves(args),
                _ => Fail("Comando desconocido. Usa read, read-boxes, read-inventory, replace-move, teach-tm, set-role, set-box-role, set-item, set-money, party-to-box, box-to-party, swap-party-box, valid-moves o export-moves."),
            };
        }
        catch (Exception ex)
        {
            return Fail($"{ex.GetType().Name}: {ex.Message}");
        }
    }

    private static int Read(string[] args)
    {
        string path = RequirePath(args, "--input");
        SaveFile sav = LoadSave(path);
        Console.WriteLine(JsonSerializer.Serialize(BuildPayload(sav), JsonOptions));
        return 0;
    }

    private static int ReadBoxes(string[] args)
    {
        string path = RequirePath(args, "--input");
        SaveFile sav = LoadSave(path);
        if (!sav.HasBox || sav.BoxCount <= 0)
            return Fail("Este guardado no expone un PC compatible.");

        var boxes = new List<object>(sav.BoxCount);
        for (int box = 0; box < sav.BoxCount; box++)
        {
            var pokemon = new List<object>();
            for (int slot = 0; slot < sav.BoxSlotCount; slot++)
            {
                PKM pk = sav.GetBoxSlotAtIndex(box, slot);
                if (pk.Species == 0)
                    continue;
                pokemon.Add(BuildPokemon(pk, slot + 1, box + 1, slot + 1));
            }
            boxes.Add(new
            {
                index = box + 1,
                name = $"Caja {box + 1}",
                pokemon,
            });
        }

        int nextOpen = sav.NextOpenBoxSlot();
        int? nextOpenBox = null;
        int? nextOpenBoxSlot = null;
        if (nextOpen >= 0)
        {
            sav.GetBoxSlotFromIndex(nextOpen, out int openBox, out int openSlot);
            nextOpenBox = openBox + 1;
            nextOpenBoxSlot = openSlot + 1;
        }

        // Exponemos todos los huecos realmente escribibles. Esto permite que la
        // interfaz prepare varias entradas/salidas del PC antes de guardar sin
        // inventar posiciones que el juego pueda tener protegidas.
        var openSlots = new List<object>();
        for (int box = 0; box < sav.BoxCount; box++)
        {
            for (int slot = 0; slot < sav.BoxSlotCount; slot++)
            {
                if (sav.IsBoxSlotOverwriteProtected(box, slot))
                    continue;
                if (sav.GetBoxSlotAtIndex(box, slot).Species != 0)
                    continue;
                openSlots.Add(new { box = box + 1, boxSlot = slot + 1 });
            }
        }

        Console.WriteLine(JsonSerializer.Serialize(new
        {
            success = true,
            game = sav.Version.ToString(),
            boxCount = sav.BoxCount,
            boxSlotCount = sav.BoxSlotCount,
            currentBox = sav.CurrentBox + 1,
            nextOpenBox,
            nextOpenBoxSlot,
            openSlots,
            boxes,
        }, JsonOptions));
        return 0;
    }

    private static int PartyToBox(string[] args)
    {
        string input = RequirePath(args, "--input");
        string output = RequireValue(args, "--output");
        int partySlot = RequireInt(args, "--party-slot", 1, 6);
        int requestedBox = OptionalInt(args, "--box", 1, int.MaxValue);
        int requestedBoxSlot = OptionalInt(args, "--box-slot", 1, int.MaxValue);

        EnsureDifferentPaths(input, output);
        SaveFile sav = LoadSave(input);
        if (!sav.HasBox || sav.BoxCount <= 0)
            return Fail("Este guardado no expone un PC compatible.");
        if (partySlot > sav.PartyCount)
            return Fail($"El equipo solo tiene {sav.PartyCount} Pokémon; no existe el slot {partySlot}.");

        int destinationIndex;
        if (requestedBox > 0 || requestedBoxSlot > 0)
        {
            if (requestedBox <= 0 || requestedBoxSlot <= 0)
                return Fail("Para elegir un destino debes indicar --box y --box-slot.");
            if (requestedBox > sav.BoxCount || requestedBoxSlot > sav.BoxSlotCount)
                return Fail("El slot de PC indicado está fuera del rango de este juego.");
            int box = requestedBox - 1;
            int slot = requestedBoxSlot - 1;
            if (sav.IsBoxSlotOverwriteProtected(box, slot))
                return Fail("Ese hueco del PC está protegido por el juego y no se puede sobrescribir.");
            if (sav.GetBoxSlotAtIndex(box, slot).Species != 0)
                return Fail("Ese hueco del PC ya está ocupado.");
            destinationIndex = box * sav.BoxSlotCount + slot;
        }
        else
        {
            destinationIndex = sav.NextOpenBoxSlot();
            if (destinationIndex < 0)
                return Fail("El PC está lleno. Libera un hueco antes de enviar un Pokémon del equipo.");
        }

        PKM outgoing = sav.GetPartySlotAtIndex(partySlot - 1);
        sav.SetBoxSlotAtIndex(outgoing, destinationIndex, EntityImportSettings.None);
        sav.DeletePartySlot(partySlot - 1);
        ExportAndWrite(sav, input, output);

        SaveFile verify = LoadSave(output);
        verify.GetBoxSlotFromIndex(destinationIndex, out int verifiedBox, out int verifiedSlot);
        PKM stored = verify.GetBoxSlotAtIndex(destinationIndex);
        if (!SamePokemonIdentity(stored, outgoing) || !SameMoves(stored, outgoing) || verify.PartyCount != sav.PartyCount)
        {
            File.Delete(Path.GetFullPath(output));
            return Fail("La validación posterior del traslado al PC no coincidió con el resultado esperado.");
        }

        Console.WriteLine(JsonSerializer.Serialize(new
        {
            success = true,
            output = Path.GetFullPath(output),
            game = verify.Version.ToString(),
            operation = "party-to-box",
            pokemon = string.IsNullOrWhiteSpace(stored.Nickname) ? GetSpeciesName(stored.Species) : stored.Nickname,
            partySlot,
            box = verifiedBox + 1,
            boxSlot = verifiedSlot + 1,
            party = BuildParty(verify),
            validated = true,
        }, JsonOptions));
        return 0;
    }

    private static int BoxToParty(string[] args)
    {
        string input = RequirePath(args, "--input");
        string output = RequireValue(args, "--output");
        int box = RequireInt(args, "--box", 1, int.MaxValue) - 1;
        int boxSlot = RequireInt(args, "--box-slot", 1, int.MaxValue) - 1;
        string role = OptionalValue(args, "--role");
        int[] removeMoveSlots = OptionalMoveSlots(args, "--remove-move-slots");

        EnsureDifferentPaths(input, output);
        SaveFile sav = LoadSave(input);
        if (!sav.HasBox || sav.BoxCount <= 0)
            return Fail("Este guardado no expone un PC compatible.");
        if (sav.PartyCount >= 6)
            return Fail("El equipo ya tiene seis Pokémon.");
        ValidateBoxPosition(sav, box, boxSlot);
        if (sav.IsBoxSlotOverwriteProtected(box, boxSlot))
            return Fail("Ese slot del PC está protegido por el juego.");

        PKM incoming = sav.GetBoxSlotAtIndex(box, boxSlot);
        if (incoming.Species == 0)
            return Fail("El slot seleccionado del PC está vacío.");
        if (!string.IsNullOrWhiteSpace(role))
            SetRoleMarkings(incoming, ResolveRoleIndex(role));
        foreach (int moveSlot in removeMoveSlots.OrderByDescending(v => v))
            RemoveMoveAndCompact(incoming, moveSlot - 1);
        incoming.RefreshChecksum();

        int partySlot = sav.PartyCount;
        sav.SetPartySlotAtIndex(incoming, partySlot, EntityImportSettings.None);
        sav.SetBoxSlotAtIndex(sav.BlankPKM, box, boxSlot, EntityImportSettings.None);
        ExportAndWrite(sav, input, output);

        SaveFile verify = LoadSave(output);
        PKM added = verify.GetPartySlotAtIndex(partySlot);
        if (!SamePokemonIdentity(added, incoming) || !SameMoves(added, incoming) || verify.GetBoxSlotAtIndex(box, boxSlot).Species != 0)
        {
            File.Delete(Path.GetFullPath(output));
            return Fail("La validación posterior de la incorporación desde el PC no coincidió con el resultado esperado.");
        }
        if (!string.IsNullOrWhiteSpace(role) && ResolveRole(GetMarkings(added)).Role != RoleNameFromIndex(ResolveRoleIndex(role)))
        {
            File.Delete(Path.GetFullPath(output));
            return Fail("La validación posterior detectó que el rol del Pokémon incorporado no coincide con el solicitado.");
        }

        Console.WriteLine(JsonSerializer.Serialize(new
        {
            success = true,
            output = Path.GetFullPath(output),
            game = verify.Version.ToString(),
            operation = "box-to-party",
            pokemon = string.IsNullOrWhiteSpace(added.Nickname) ? GetSpeciesName(added.Species) : added.Nickname,
            partySlot = partySlot + 1,
            box = box + 1,
            boxSlot = boxSlot + 1,
            party = BuildParty(verify),
            validated = true,
        }, JsonOptions));
        return 0;
    }

    private static int SwapPartyBox(string[] args)
    {
        string input = RequirePath(args, "--input");
        string output = RequireValue(args, "--output");
        int partySlot = RequireInt(args, "--party-slot", 1, 6);
        int box = RequireInt(args, "--box", 1, int.MaxValue) - 1;
        int boxSlot = RequireInt(args, "--box-slot", 1, int.MaxValue) - 1;
        string role = OptionalValue(args, "--role");
        int[] removeMoveSlots = OptionalMoveSlots(args, "--remove-move-slots");

        EnsureDifferentPaths(input, output);
        SaveFile sav = LoadSave(input);
        if (!sav.HasBox || sav.BoxCount <= 0)
            return Fail("Este guardado no expone un PC compatible.");
        if (partySlot > sav.PartyCount)
            return Fail($"El equipo solo tiene {sav.PartyCount} Pokémon; no existe el slot {partySlot}.");
        ValidateBoxPosition(sav, box, boxSlot);
        if (sav.IsBoxSlotOverwriteProtected(box, boxSlot))
            return Fail("Ese slot del PC está protegido por el juego.");

        PKM incoming = sav.GetBoxSlotAtIndex(box, boxSlot);
        if (incoming.Species == 0)
            return Fail("El slot seleccionado del PC está vacío.");
        PKM outgoing = sav.GetPartySlotAtIndex(partySlot - 1);
        if (!string.IsNullOrWhiteSpace(role))
            SetRoleMarkings(incoming, ResolveRoleIndex(role));
        foreach (int moveSlot in removeMoveSlots.OrderByDescending(v => v))
            RemoveMoveAndCompact(incoming, moveSlot - 1);
        incoming.RefreshChecksum();

        sav.SetBoxSlotAtIndex(outgoing, box, boxSlot, EntityImportSettings.None);
        sav.SetPartySlotAtIndex(incoming, partySlot - 1, EntityImportSettings.None);
        ExportAndWrite(sav, input, output);

        SaveFile verify = LoadSave(output);
        PKM verifiedIncoming = verify.GetPartySlotAtIndex(partySlot - 1);
        PKM verifiedOutgoing = verify.GetBoxSlotAtIndex(box, boxSlot);
        if (!SamePokemonIdentity(verifiedIncoming, incoming) || !SameMoves(verifiedIncoming, incoming) ||
            !SamePokemonIdentity(verifiedOutgoing, outgoing) || !SameMoves(verifiedOutgoing, outgoing))
        {
            File.Delete(Path.GetFullPath(output));
            return Fail("La validación posterior del intercambio Equipo ↔ PC no coincidió con el resultado esperado.");
        }
        if (!string.IsNullOrWhiteSpace(role) && ResolveRole(GetMarkings(verifiedIncoming)).Role != RoleNameFromIndex(ResolveRoleIndex(role)))
        {
            File.Delete(Path.GetFullPath(output));
            return Fail("La validación posterior detectó que el rol del Pokémon incorporado no coincide con el solicitado.");
        }

        Console.WriteLine(JsonSerializer.Serialize(new
        {
            success = true,
            output = Path.GetFullPath(output),
            game = verify.Version.ToString(),
            operation = "swap-party-box",
            incoming = string.IsNullOrWhiteSpace(verifiedIncoming.Nickname) ? GetSpeciesName(verifiedIncoming.Species) : verifiedIncoming.Nickname,
            outgoing = string.IsNullOrWhiteSpace(verifiedOutgoing.Nickname) ? GetSpeciesName(verifiedOutgoing.Species) : verifiedOutgoing.Nickname,
            partySlot,
            box = box + 1,
            boxSlot = boxSlot + 1,
            party = BuildParty(verify),
            validated = true,
        }, JsonOptions));
        return 0;
    }

    private static int ReadInventory(string[] args)
    {
        string input = RequirePath(args, "--input");
        SaveFile sav = LoadSave(input);
        var items = new List<object>();
        foreach (var pouch in sav.Inventory.Pouches)
        {
            int slot = 0;
            foreach (var item in pouch.Items)
            {
                if (item.Index <= 0 || item.Count <= 0)
                {
                    slot++;
                    continue;
                }
                items.Add(new
                {
                    itemId = item.Index,
                    item = GetItemName(item.Index),
                    count = item.Count,
                    pocket = pouch.Type.ToString(),
                    slot,
                });
                slot++;
            }
        }
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            success = true,
            game = sav.Version.ToString(),
            items,
        }, JsonOptions));
        return 0;
    }

    private static int TeachTM(string[] args)
    {
        string input = RequirePath(args, "--input");
        string output = RequireValue(args, "--output");
        int partySlot = RequireInt(args, "--party-slot", 1, 6);
        int moveSlot = RequireInt(args, "--move-slot", 1, 4);
        int requestedMoveId = RequireInt(args, "--move-id", 1, ushort.MaxValue);
        int itemId = RequireInt(args, "--item-id", 1, ushort.MaxValue);

        if (Path.GetFullPath(input).Equals(Path.GetFullPath(output), StringComparison.OrdinalIgnoreCase))
            return Fail("No se permite sobrescribir directamente el guardado de entrada.");

        SaveFile sav = LoadSave(input);
        if (partySlot > sav.PartyCount)
            return Fail($"El equipo solo tiene {sav.PartyCount} Pokémon; no existe el slot {partySlot}.");
        if (requestedMoveId > sav.MaxMoveID)
            return Fail($"El movimiento #{requestedMoveId} no existe en este guardado (máximo: {sav.MaxMoveID}).");

        int oldQuantity = GetInventoryQuantity(sav, itemId);
        if (oldQuantity <= 0)
            return Fail($"No queda ninguna unidad de {GetItemName(itemId)} en la mochila.");

        var bag = sav.Inventory;
        InventoryPouch? pouch = bag.Pouches.FirstOrDefault(p => Array.Exists(p.Items, z => z.Index == itemId));
        if (pouch is null)
            return Fail($"No se encontró {GetItemName(itemId)} dentro de una bolsa editable.");
        int itemSlot = Array.FindIndex(pouch.Items, z => z.Index == itemId);
        if (itemSlot < 0)
            return Fail($"No se pudo localizar {GetItemName(itemId)} en la mochila.");

        PKM pk = sav.GetPartySlotAtIndex(partySlot - 1);
        int targetIndex = moveSlot - 1;
        ushort oldMoveId = GetMove(pk, targetIndex);
        ushort moveId = (ushort)requestedMoveId;
        SetMove(pk, targetIndex, moveId);
        if (MoveInfo.IsDummiedMove(pk, targetIndex))
            return Fail($"El movimiento #{requestedMoveId} está desactivado y no se puede usar en este juego.");
        pk.HealPPIndex(targetIndex);
        pk.RefreshChecksum();
        sav.SetPartySlotAtIndex(pk, partySlot - 1, EntityImportSettings.None);

        int newQuantity = oldQuantity - 1;
        pouch.Items[itemSlot] = pouch.GetEmpty(newQuantity > 0 ? itemId : 0, newQuantity);
        bag.CopyTo(sav);

        Memory<byte> exported = sav.Write();
        string fullOutput = Path.GetFullPath(output);
        Directory.CreateDirectory(Path.GetDirectoryName(fullOutput)!);
        WriteSaveContainer(input, fullOutput, exported.ToArray());

        SaveFile verify = LoadSave(fullOutput);
        PKM verifiedPk = verify.GetPartySlotAtIndex(partySlot - 1);
        ushort verifiedMove = GetMove(verifiedPk, targetIndex);
        int verifiedQuantity = GetInventoryQuantity(verify, itemId);
        if (verifiedMove != moveId || verifiedQuantity != newQuantity)
        {
            File.Delete(fullOutput);
            return Fail(
                $"La validación posterior de la MT falló: movimiento {verifiedMove}/{moveId}, cantidad {verifiedQuantity}/{newQuantity}. " +
                "El archivo generado se ha descartado por seguridad."
            );
        }

        Console.WriteLine(JsonSerializer.Serialize(new
        {
            success = true,
            output = fullOutput,
            game = verify.Version.ToString(),
            partySlot,
            moveSlot,
            pokemon = string.IsNullOrWhiteSpace(verifiedPk.Nickname) ? GetSpeciesName(verifiedPk.Species) : verifiedPk.Nickname,
            species = GetSpeciesName(verifiedPk.Species),
            oldMove = GetMoveName(oldMoveId),
            newMove = GetMoveName(moveId),
            itemId,
            item = GetItemName(itemId),
            oldQuantity,
            quantity = verifiedQuantity,
            validated = true,
            party = BuildParty(verify),
        }, JsonOptions));
        return 0;
    }

    private static int ReplaceMove(string[] args)
    {
        string input = RequirePath(args, "--input");
        string output = RequireValue(args, "--output");
        int partySlot = RequireInt(args, "--party-slot", 1, 6);
        int moveSlot = RequireInt(args, "--move-slot", 1, 4);
        int requestedMoveId = RequireInt(args, "--move-id", 0, ushort.MaxValue);

        if (Path.GetFullPath(input).Equals(Path.GetFullPath(output), StringComparison.OrdinalIgnoreCase))
            return Fail("La v0.3 no permite sobrescribir el guardado original. Selecciona otra ruta de salida.");

        SaveFile sav = LoadSave(input);
        if (partySlot > sav.PartyCount)
            return Fail($"El equipo solo tiene {sav.PartyCount} Pokémon; no existe el slot {partySlot}.");

        if (requestedMoveId > sav.MaxMoveID)
            return Fail($"El movimiento #{requestedMoveId} no existe en este guardado (máximo: {sav.MaxMoveID}).");
        ushort moveId = (ushort)requestedMoveId;
        PKM pk = sav.GetPartySlotAtIndex(partySlot - 1);
        int targetIndex = moveSlot - 1;
        ushort oldMoveId = GetMove(pk, targetIndex);
        string oldMove = GetMoveName(oldMoveId);
        ushort[] movesBefore = Enumerable.Range(0, 4).Select(i => GetMove(pk, i)).ToArray();

        if (moveId == 0)
        {
            // Un Pokémon no debe quedar con huecos intermedios. Al borrar un
            // movimiento desplazamos los siguientes hacia la izquierda y
            // limpiamos también PP/PP-Ups del último hueco. Esto evita estados
            // inconsistentes que algunos juegos pueden normalizar eliminando
            // movimientos adicionales.
            RemoveMoveAndCompact(pk, targetIndex);
        }
        else
        {
            SetMove(pk, targetIndex, moveId);
            if (MoveInfo.IsDummiedMove(pk, targetIndex))
                return Fail($"El movimiento #{requestedMoveId} existe en la base de datos, pero está desactivado y no se puede usar en este juego.");
            pk.HealPPIndex(targetIndex);
        }
        pk.RefreshChecksum();
        sav.SetPartySlotAtIndex(pk, partySlot - 1, EntityImportSettings.None);

        Memory<byte> exported = sav.Write();
        string fullOutput = Path.GetFullPath(output);
        Directory.CreateDirectory(Path.GetDirectoryName(fullOutput)!);
        WriteSaveContainer(input, fullOutput, exported.ToArray());

        // Validación independiente: recargar el archivo recién generado y verificar el cambio.
        SaveFile verify = LoadSave(fullOutput);
        PKM verifiedPk = verify.GetPartySlotAtIndex(partySlot - 1);
        ushort[] verifiedMoves = Enumerable.Range(0, 4).Select(i => GetMove(verifiedPk, i)).ToArray();
        ushort[] expectedMoves = movesBefore.ToArray();
        if (moveId == 0)
        {
            for (int i = targetIndex; i < 3; i++)
                expectedMoves[i] = expectedMoves[i + 1];
            expectedMoves[3] = 0;
        }
        else
        {
            expectedMoves[targetIndex] = moveId;
        }

        if (!verifiedMoves.SequenceEqual(expectedMoves))
        {
            File.Delete(fullOutput);
            return Fail(
                "La validación posterior detectó que se modificó más de un movimiento o que el equipo quedó en un estado inesperado. " +
                "Por seguridad, el guardado generado se ha descartado y el original no se ha tocado."
            );
        }
        ushort verifiedMove = moveId == 0 ? (ushort)0 : GetMove(verifiedPk, targetIndex);

        var payload = new
        {
            success = true,
            output = fullOutput,
            game = verify.Version.ToString(),
            partySlot,
            moveSlot,
            pokemon = string.IsNullOrWhiteSpace(verifiedPk.Nickname) ? GetSpeciesName(verifiedPk.Species) : verifiedPk.Nickname,
            species = GetSpeciesName(verifiedPk.Species),
            oldMove,
            newMove = GetMoveName(moveId),
            validated = true,
            party = BuildParty(verify),
        };
        Console.WriteLine(JsonSerializer.Serialize(payload, JsonOptions));
        return 0;
    }

    private static int ValidMoves(string[] args)
    {
        string input = RequirePath(args, "--input");
        SaveFile sav = LoadSave(input);
        PKM? probe = sav.PartyData.FirstOrDefault(pk => pk.Species != 0);
        if (probe is null)
            return Fail("El guardado no tiene ningún Pokémon en el equipo para determinar los movimientos utilizables.");

        ushort original = probe.Move1;
        var valid = new List<int>(sav.MaxMoveID);
        for (int id = 1; id <= sav.MaxMoveID; id++)
        {
            probe.Move1 = (ushort)id;
            if (!MoveInfo.IsDummiedMove(probe, 0))
                valid.Add(id);
        }
        probe.Move1 = original;

        var payload = new
        {
            success = true,
            game = sav.Version.ToString(),
            maxMoveId = sav.MaxMoveID,
            moveIds = valid,
            count = valid.Count,
        };
        Console.WriteLine(JsonSerializer.Serialize(payload, JsonOptions));
        return 0;
    }

    private static int SetRole(string[] args)
    {
        string input = RequirePath(args, "--input");
        string output = RequireValue(args, "--output");
        int partySlot = RequireInt(args, "--party-slot", 1, 6);
        string requestedRole = RequireValue(args, "--role");

        if (Path.GetFullPath(input).Equals(Path.GetFullPath(output), StringComparison.OrdinalIgnoreCase))
            return Fail("No se permite sobrescribir directamente el guardado de entrada.");

        int markingIndex = ResolveRoleIndex(requestedRole);
        SaveFile sav = LoadSave(input);
        if (partySlot > sav.PartyCount)
            return Fail($"El equipo solo tiene {sav.PartyCount} Pokémon; no existe el slot {partySlot}.");

        PKM pk = sav.GetPartySlotAtIndex(partySlot - 1);
        SetRoleMarkings(pk, markingIndex);
        pk.RefreshChecksum();
        sav.SetPartySlotAtIndex(pk, partySlot - 1, EntityImportSettings.None);

        Memory<byte> exported = sav.Write();
        string fullOutput = Path.GetFullPath(output);
        Directory.CreateDirectory(Path.GetDirectoryName(fullOutput)!);
        WriteSaveContainer(input, fullOutput, exported.ToArray());

        SaveFile verify = LoadSave(fullOutput);
        PKM verifiedPk = verify.GetPartySlotAtIndex(partySlot - 1);
        bool[] markings = GetMarkings(verifiedPk);
        (string verifiedRole, string roleSymbol) = ResolveRole(markings);
        string expectedRole = markingIndex < 0 ? "SIN ROL" : RoleNameFromIndex(markingIndex);
        if (!string.Equals(verifiedRole, expectedRole, StringComparison.OrdinalIgnoreCase))
        {
            File.Delete(fullOutput);
            return Fail($"La validación posterior falló: se esperaba '{expectedRole}' y se leyó '{verifiedRole}'.");
        }

        var payload = new
        {
            success = true,
            output = fullOutput,
            game = verify.Version.ToString(),
            partySlot,
            pokemon = string.IsNullOrWhiteSpace(verifiedPk.Nickname) ? GetSpeciesName(verifiedPk.Species) : verifiedPk.Nickname,
            species = GetSpeciesName(verifiedPk.Species),
            role = verifiedRole,
            roleSymbol,
            validated = true,
            party = BuildParty(verify),
        };
        Console.WriteLine(JsonSerializer.Serialize(payload, JsonOptions));
        return 0;
    }

    private static int SetBoxRole(string[] args)
    {
        string input = RequirePath(args, "--input");
        string output = RequireValue(args, "--output");
        int box = RequireInt(args, "--box", 1, int.MaxValue) - 1;
        int boxSlot = RequireInt(args, "--box-slot", 1, int.MaxValue) - 1;
        string requestedRole = RequireValue(args, "--role");

        EnsureDifferentPaths(input, output);
        SaveFile sav = LoadSave(input);
        if (!sav.HasBox || sav.BoxCount <= 0)
            return Fail("Este guardado no expone un PC compatible.");
        ValidateBoxPosition(sav, box, boxSlot);
        if (sav.IsBoxSlotOverwriteProtected(box, boxSlot))
            return Fail("Ese slot del PC está protegido por el juego.");

        PKM pk = sav.GetBoxSlotAtIndex(box, boxSlot);
        if (pk.Species == 0)
            return Fail("El slot seleccionado del PC está vacío.");
        int markingIndex = ResolveRoleIndex(requestedRole);
        SetRoleMarkings(pk, markingIndex);
        pk.RefreshChecksum();
        sav.SetBoxSlotAtIndex(pk, box, boxSlot, EntityImportSettings.None);
        ExportAndWrite(sav, input, output);

        SaveFile verify = LoadSave(output);
        PKM verifiedPk = verify.GetBoxSlotAtIndex(box, boxSlot);
        (string verifiedRole, string roleSymbol) = ResolveRole(GetMarkings(verifiedPk));
        string expectedRole = markingIndex < 0 ? "SIN ROL" : RoleNameFromIndex(markingIndex);
        if (!SamePokemonIdentity(verifiedPk, pk) || !SameMoves(verifiedPk, pk) ||
            !string.Equals(verifiedRole, expectedRole, StringComparison.OrdinalIgnoreCase))
        {
            File.Delete(Path.GetFullPath(output));
            return Fail("La validación posterior del cambio de rol en el PC no coincidió con el resultado esperado.");
        }

        Console.WriteLine(JsonSerializer.Serialize(new
        {
            success = true,
            output = Path.GetFullPath(output),
            game = verify.Version.ToString(),
            box = box + 1,
            boxSlot = boxSlot + 1,
            pokemon = string.IsNullOrWhiteSpace(verifiedPk.Nickname) ? GetSpeciesName(verifiedPk.Species) : verifiedPk.Nickname,
            species = GetSpeciesName(verifiedPk.Species),
            role = verifiedRole,
            roleSymbol,
            validated = true,
        }, JsonOptions));
        return 0;
    }

    private static int SetItem(string[] args)
    {
        string input = RequirePath(args, "--input");
        string output = RequireValue(args, "--output");
        string itemKey = RequireValue(args, "--item");
        int requestedQuantity = RequireInt(args, "--quantity", 1, ushort.MaxValue);

        if (Path.GetFullPath(input).Equals(Path.GetFullPath(output), StringComparison.OrdinalIgnoreCase))
            return Fail("No se permite sobrescribir directamente el guardado de entrada.");

        SaveFile sav = LoadSave(input);
        int itemId = ResolveUtilityItemId(itemKey);
        var bag = sav.Inventory;
        InventoryPouch? pouch = bag.Pouches.FirstOrDefault(p => p.CanContain((ushort)itemId));
        if (pouch is null)
            return Fail($"El objeto #{itemId} no pertenece a ninguna bolsa editable de este juego.");

        int quantity = requestedQuantity;
        bool hasNew = pouch.Items.Length != 0 && pouch.Items[0] is IItemNewFlag;
        if (!bag.IsQuantitySane(pouch.Type, itemId, ref quantity, hasNew, false) || quantity != requestedQuantity)
            return Fail($"Este juego no admite una cantidad de {requestedQuantity} para {GetItemName(itemId)} (máximo aceptado: {quantity}).");

        int slot = Array.FindIndex(pouch.Items, z => z.Index == itemId);
        int oldQuantity = slot >= 0 ? pouch.Items[slot].Count : 0;
        if (slot < 0)
            slot = Array.FindIndex(pouch.Items, z => z.Index == 0);
        if (slot < 0)
            return Fail($"La bolsa '{pouch.Type}' está llena y no dispone de un hueco para {GetItemName(itemId)}.");

        pouch.Items[slot] = pouch.GetEmpty(itemId, quantity);
        bag.CopyTo(sav);

        Memory<byte> exported = sav.Write();
        string fullOutput = Path.GetFullPath(output);
        Directory.CreateDirectory(Path.GetDirectoryName(fullOutput)!);
        WriteSaveContainer(input, fullOutput, exported.ToArray());

        SaveFile verify = LoadSave(fullOutput);
        int verifiedQuantity = GetInventoryQuantity(verify, itemId);
        if (verifiedQuantity != quantity)
        {
            File.Delete(fullOutput);
            return Fail($"La validación posterior falló: se esperaban {quantity} unidades y se leyeron {verifiedQuantity}.");
        }

        var payload = new
        {
            success = true,
            output = fullOutput,
            game = verify.Version.ToString(),
            itemId,
            item = GetItemName(itemId),
            oldQuantity,
            quantity = verifiedQuantity,
            validated = true,
        };
        Console.WriteLine(JsonSerializer.Serialize(payload, JsonOptions));
        return 0;
    }

    private static int SetMoney(string[] args)
    {
        string input = RequirePath(args, "--input");
        string output = RequireValue(args, "--output");
        if (Path.GetFullPath(input).Equals(Path.GetFullPath(output), StringComparison.OrdinalIgnoreCase))
            return Fail("No se permite sobrescribir directamente el guardado de entrada.");

        SaveFile sav = LoadSave(input);
        var property = sav.GetType().GetProperty("Money");
        if (property is null || !property.CanRead || !property.CanWrite)
            return Fail("Este formato de guardado no expone un campo de dinero editable.");

        long oldMoney = Convert.ToInt64(property.GetValue(sav) ?? 0);
        long target = 9_999_999;
        object converted = Convert.ChangeType(target, property.PropertyType);
        property.SetValue(sav, converted);

        Memory<byte> exported = sav.Write();
        string fullOutput = Path.GetFullPath(output);
        Directory.CreateDirectory(Path.GetDirectoryName(fullOutput)!);
        WriteSaveContainer(input, fullOutput, exported.ToArray());

        SaveFile verify = LoadSave(fullOutput);
        var verifyProperty = verify.GetType().GetProperty("Money");
        if (verifyProperty is null)
            return Fail("No se pudo validar el dinero del guardado generado.");
        long verifiedMoney = Convert.ToInt64(verifyProperty.GetValue(verify) ?? 0);
        if (verifiedMoney != target)
        {
            File.Delete(fullOutput);
            return Fail($"La validación posterior falló: se esperaban {target} y se leyeron {verifiedMoney}.");
        }

        Console.WriteLine(JsonSerializer.Serialize(new
        {
            success = true, output = fullOutput, game = verify.Version.ToString(),
            oldMoney, money = verifiedMoney, validated = true,
        }, JsonOptions));
        return 0;
    }

    private static int ResolveUtilityItemId(string key)
    {
        string normalized = key.Trim().ToLowerInvariant().Replace("_", "-").Replace(" ", "-");
        string englishName = normalized switch
        {
            "rare-candy" or "caramelo-raro" => "Rare Candy",
            "max-repel" or "repelente-maximo" or "repelente-máximo" => "Max Repel",
            _ => throw new ArgumentException($"Utilidad de mochila desconocida: '{key}'."),
        };

        var names = GameInfo.GetStrings("en").Item;
        for (int id = 1; id < names.Count; id++)
        {
            if (string.Equals(names[id], englishName, StringComparison.OrdinalIgnoreCase))
                return id;
        }
        throw new InvalidOperationException($"PKHeX.Core no pudo localizar el objeto '{englishName}'.");
    }

    private static int GetInventoryQuantity(SaveFile sav, int itemId)
    {
        foreach (var pouch in sav.Inventory.Pouches)
        {
            var item = Array.Find(pouch.Items, z => z.Index == itemId);
            if (item is not null)
                return item.Count;
        }
        return 0;
    }

    private static string GetItemName(int id)
    {
        var strings = GameInfo.GetStrings("es");
        return NameSafe(strings.Item, id, $"Objeto #{id}");
    }

    // Alpha.43: el índice de la marca ES el orden oficial de roles.
    private static int ResolveRoleIndex(string role) => role.Trim().ToLowerInvariant() switch
    {
        "líbero" or "libero" => 0,
        "asesino" => 1,
        "mago" => 2,
        "tanque" => 3,
        "prisma" => 4,
        "paladín" or "paladin" => 4, // alias histórico únicamente
        "support" or "soporte" => 5,
        "sin rol" or "sin-rol" or "none" => -1,
        _ => throw new ArgumentException($"Rol desconocido: '{role}'."),
    };

    private static string RoleNameFromIndex(int index) => index switch
    {
        0 => "Líbero",
        1 => "Asesino",
        2 => "Mago",
        3 => "Tanque",
        4 => "Prisma",
        5 => "Support",
        _ => "SIN ROL",
    };

    private static void SetRoleMarkings(PKM pk, int selectedIndex)
    {
        if (pk is IAppliedMarkings<bool> simple)
        {
            int count = Math.Min(6, simple.MarkingCount);
            for (int i = 0; i < count; i++)
                simple.SetMarking(i, i == selectedIndex);
            return;
        }

        if (pk is IAppliedMarkings<MarkingColor> colored)
        {
            int count = Math.Min(6, colored.MarkingCount);
            for (int i = 0; i < count; i++)
                colored.SetMarking(i, i == selectedIndex ? (MarkingColor)1 : MarkingColor.None);
            return;
        }

        throw new InvalidOperationException("Este formato de Pokémon no admite los seis marcadores necesarios para los roles.");
    }

    private static int ExportMoves(string[] args)
    {
        string output = RequireValue(args, "--output");
        var en = GameInfo.GetStrings("en");
        var es = GameInfo.GetStrings("es");
        int count = Math.Min(en.Move.Count, es.Move.Count);
        var moves = new List<object>();
        for (int id = 1; id < count; id++)
        {
            string nameEn = NameSafe(en.Move, id, "");
            string nameEs = NameSafe(es.Move, id, "");
            if (string.IsNullOrWhiteSpace(nameEn))
                continue;
            moves.Add(new { id, nameEn, nameEs = string.IsNullOrWhiteSpace(nameEs) ? nameEn : nameEs });
        }

        string full = Path.GetFullPath(output);
        Directory.CreateDirectory(Path.GetDirectoryName(full)!);
        File.WriteAllText(full, JsonSerializer.Serialize(new { version = 1, moves }, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            WriteIndented = true,
        }), Encoding.UTF8);
        Console.WriteLine(JsonSerializer.Serialize(new { success = true, output = full, count = moves.Count }, JsonOptions));
        return 0;
    }

    private static object BuildPayload(SaveFile sav) => new
    {
        success = true,
        game = sav.Version.ToString(),
        saveType = sav.GetType().Name,
        generation = sav.Generation,
        trainer = sav.OT,
        maxMoveId = sav.MaxMoveID,
        party = BuildParty(sav),
    };

    private static List<object> BuildParty(SaveFile sav)
    {
        var party = new List<object>();
        int slot = 1;
        foreach (PKM pk in sav.PartyData)
        {
            if (pk.Species == 0)
                continue;
            party.Add(BuildPokemon(pk, slot));
            slot++;
        }
        return party;
    }

    private static object BuildPokemon(PKM pk, int slot, int? box = null, int? boxSlot = null)
    {
        var strings = GameInfo.GetStrings("es");
        string species = NameSafe(strings.Species, pk.Species, $"Especie #{pk.Species}");
        string nickname = string.IsNullOrWhiteSpace(pk.Nickname) ? species : pk.Nickname;
        string heldItem = pk.HeldItem == 0 ? "Ninguno" : NameSafe(strings.Item, pk.HeldItem, $"Objeto #{pk.HeldItem}");
        string ability = NameSafe(strings.Ability, pk.Ability, $"Habilidad #{pk.Ability}");
        ushort[] moveIds = [pk.Move1, pk.Move2, pk.Move3, pk.Move4];
        string[] moves = moveIds.Select(id => id == 0 ? "—" : NameSafe(strings.Move, id, $"Movimiento #{id}")).ToArray();
        bool[] markings = GetMarkings(pk);
        (string role, string roleSymbol) = ResolveRole(markings);
        return new
        {
            slot,
            box,
            boxSlot,
            speciesId = pk.Species,
            species,
            nickname,
            level = pk.CurrentLevel,
            heldItem,
            ability,
            moves,
            moveIds,
            isEgg = pk.IsEgg,
            markings,
            role,
            roleSymbol,
            format = pk.Format,
            form = pk.Form,
            pid = pk.PID,
            tid = pk.TID16,
            sid = pk.SID16,
        };
    }


    private static bool[] GetMarkings(PKM pk)
    {
        var result = new bool[6];
        if (pk is IAppliedMarkings<bool> simple)
        {
            int count = Math.Min(result.Length, simple.MarkingCount);
            for (int i = 0; i < count; i++)
                result[i] = simple.GetMarking(i);
        }
        else if (pk is IAppliedMarkings<MarkingColor> colored)
        {
            int count = Math.Min(result.Length, colored.MarkingCount);
            for (int i = 0; i < count; i++)
                result[i] = colored.GetMarking(i) != MarkingColor.None;
        }
        return result;
    }

    private static (string Role, string Symbol) ResolveRole(IReadOnlyList<bool> markings)
    {
        int selected = -1;
        for (int i = 0; i < markings.Count; i++)
        {
            if (!markings[i])
                continue;
            if (selected != -1)
                return ("SIN ROL", "");
            selected = i;
        }

        return selected switch
        {
            0 => ("Líbero", "●"),
            1 => ("Asesino", "▲"),
            2 => ("Mago", "■"),
            3 => ("Tanque", "♥"),
            4 => ("Prisma", "★"),
            5 => ("Support", "◆"),
            _ => ("SIN ROL", ""),
        };
    }

    private static bool SamePokemonIdentity(PKM a, PKM b)
        => a.Species == b.Species && a.PID == b.PID && a.TID16 == b.TID16 && a.SID16 == b.SID16;

    private static bool SameMoves(PKM a, PKM b)
        => a.Move1 == b.Move1 && a.Move2 == b.Move2 && a.Move3 == b.Move3 && a.Move4 == b.Move4;

    private static void EnsureDifferentPaths(string input, string output)
    {
        if (Path.GetFullPath(input).Equals(Path.GetFullPath(output), StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("No se permite sobrescribir directamente el guardado de entrada.");
    }

    private static void ValidateBoxPosition(SaveFile sav, int box, int slot)
    {
        if ((uint)box >= sav.BoxCount || (uint)slot >= sav.BoxSlotCount)
            throw new ArgumentOutOfRangeException(nameof(box), "El slot del PC indicado está fuera del rango de este juego.");
    }

    private static void ExportAndWrite(SaveFile sav, string input, string output)
    {
        Memory<byte> exported = sav.Write();
        string fullOutput = Path.GetFullPath(output);
        Directory.CreateDirectory(Path.GetDirectoryName(fullOutput)!);
        WriteSaveContainer(input, fullOutput, exported.ToArray());
    }

    private static string OptionalValue(string[] args, string key)
    {
        for (int i = 0; i < args.Length - 1; i++)
            if (string.Equals(args[i], key, StringComparison.OrdinalIgnoreCase))
                return args[i + 1];
        return string.Empty;
    }

    private static int OptionalInt(string[] args, string key, int min, int max)
    {
        string value = OptionalValue(args, key);
        if (string.IsNullOrWhiteSpace(value))
            return -1;
        if (!int.TryParse(value, out int parsed) || parsed < min || parsed > max)
            throw new ArgumentOutOfRangeException(key, $"{key} debe estar entre {min} y {max}.");
        return parsed;
    }

    private static int[] OptionalMoveSlots(string[] args, string key)
    {
        string value = OptionalValue(args, key);
        if (string.IsNullOrWhiteSpace(value))
            return [];
        var result = new List<int>();
        foreach (string token in value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (!int.TryParse(token, out int slot) || slot < 1 || slot > 4)
                throw new ArgumentOutOfRangeException(key, "Los slots de movimiento deben estar entre 1 y 4.");
            if (!result.Contains(slot))
                result.Add(slot);
        }
        return [.. result];
    }

    private static void WriteSaveContainer(string inputPath, string outputPath, byte[] rawSave)
    {
        byte[] output = rawSave;
        if (Path.GetExtension(inputPath).Equals(".dsv", StringComparison.OrdinalIgnoreCase))
        {
            byte[] original = ReadAllBytesShared(inputPath);
            const int rawLength = 0x80000;
            if (original.Length > rawLength && rawSave.Length == rawLength)
            {
                byte[] footer = original[rawLength..];
                output = new byte[rawSave.Length + footer.Length];
                Buffer.BlockCopy(rawSave, 0, output, 0, rawSave.Length);
                Buffer.BlockCopy(footer, 0, output, rawSave.Length, footer.Length);
            }
        }
        File.WriteAllBytes(outputPath, output);
    }

    private static byte[] ReadAllBytesShared(string path, int attempts = 20, int delayMs = 100)
    {
        IOException? lastError = null;
        for (int attempt = 1; attempt <= attempts; attempt++)
        {
            try
            {
                // DeSmuME puede mantener el .dsv abierto mientras el juego está
                // funcionando. FileShare.ReadWrite permite obtener una instantánea
                // de lectura sin exigir que el emulador cierre su manejador.
                using var stream = new FileStream(
                    path,
                    FileMode.Open,
                    FileAccess.Read,
                    FileShare.ReadWrite | FileShare.Delete,
                    bufferSize: 64 * 1024,
                    options: FileOptions.SequentialScan);

                if (stream.Length > int.MaxValue)
                    throw new IOException("El archivo es demasiado grande para cargarlo en memoria.");

                byte[] data = new byte[(int)stream.Length];
                int offset = 0;
                while (offset < data.Length)
                {
                    int read = stream.Read(data, offset, data.Length - offset);
                    if (read == 0)
                        throw new EndOfStreamException("El archivo cambió mientras se estaba leyendo.");
                    offset += read;
                }
                return data;
            }
            catch (IOException ex)
            {
                lastError = ex;
                if (attempt < attempts)
                    Thread.Sleep(delayMs);
            }
        }

        throw new IOException(
            "No se pudo leer el guardado mientras el emulador lo estaba actualizando. " +
            "Espera un instante sin guardar dentro del juego y vuelve a intentarlo.",
            lastError);
    }

    private static SaveFile LoadSave(string path)
    {
        string full = Path.GetFullPath(path);
        if (!File.Exists(full))
            throw new FileNotFoundException("El archivo seleccionado no existe.", full);

        // DeSmuME guarda un bloque SAV estándar de 512 KiB seguido de un pie
        // propio del emulador. PKHeX.Core reconoce el bloque puro, no siempre el
        // contenedor .dsv completo, así que lo extraemos temporalmente.
        if (Path.GetExtension(full).Equals(".dsv", StringComparison.OrdinalIgnoreCase))
        {
            byte[] container = ReadAllBytesShared(full);
            const int rawLength = 0x80000;
            if (container.Length < rawLength)
                throw new InvalidDataException("El archivo .dsv está truncado: no contiene los 512 KiB del guardado de Nintendo DS.");

            string temporary = Path.Combine(Path.GetTempPath(), $"rolerun_{Guid.NewGuid():N}.sav");
            try
            {
                File.WriteAllBytes(temporary, container[..rawLength]);
                object? extracted = FileUtil.GetSupportedFile(temporary);
                return extracted as SaveFile
                    ?? throw new InvalidDataException("PKHeX.Core no pudo identificar el bloque interno del archivo .dsv como un guardado compatible.");
            }
            finally
            {
                try { File.Delete(temporary); } catch { /* limpieza no crítica */ }
            }
        }

        object? loaded = FileUtil.GetSupportedFile(full);
        return loaded as SaveFile ?? throw new InvalidDataException("PKHeX.Core no pudo identificar el archivo como un guardado compatible.");
    }

    private static ushort ResolveMoveId(string name, ushort maxMoveId)
    {
        if (ushort.TryParse(name, out ushort numeric))
        {
            if (numeric == 0 || numeric > maxMoveId)
                throw new ArgumentOutOfRangeException(nameof(name), $"El ID debe estar entre 1 y {maxMoveId}.");
            return numeric;
        }

        var names = GameInfo.Strings.Move;
        for (ushort i = 1; i < names.Count && i <= maxMoveId; i++)
        {
            if (string.Equals(names[i], name, StringComparison.OrdinalIgnoreCase))
                return i;
        }
        throw new ArgumentException($"No existe un movimiento llamado '{name}' en la base de datos compatible con este guardado.");
    }

    private static ushort GetMove(PKM pk, int index) => index switch
    {
        0 => pk.Move1,
        1 => pk.Move2,
        2 => pk.Move3,
        3 => pk.Move4,
        _ => throw new ArgumentOutOfRangeException(nameof(index)),
    };

    private static void SetMove(PKM pk, int index, ushort value)
    {
        switch (index)
        {
            case 0: pk.Move1 = value; break;
            case 1: pk.Move2 = value; break;
            case 2: pk.Move3 = value; break;
            case 3: pk.Move4 = value; break;
            default: throw new ArgumentOutOfRangeException(nameof(index));
        }
    }


    private static int GetMovePP(PKM pk, int index) => index switch
    {
        0 => pk.Move1_PP,
        1 => pk.Move2_PP,
        2 => pk.Move3_PP,
        3 => pk.Move4_PP,
        _ => throw new ArgumentOutOfRangeException(nameof(index)),
    };

    private static void SetMovePP(PKM pk, int index, int value)
    {
        switch (index)
        {
            case 0: pk.Move1_PP = value; break;
            case 1: pk.Move2_PP = value; break;
            case 2: pk.Move3_PP = value; break;
            case 3: pk.Move4_PP = value; break;
            default: throw new ArgumentOutOfRangeException(nameof(index));
        }
    }

    private static int GetMovePPUps(PKM pk, int index) => index switch
    {
        0 => pk.Move1_PPUps,
        1 => pk.Move2_PPUps,
        2 => pk.Move3_PPUps,
        3 => pk.Move4_PPUps,
        _ => throw new ArgumentOutOfRangeException(nameof(index)),
    };

    private static void SetMovePPUps(PKM pk, int index, int value)
    {
        switch (index)
        {
            case 0: pk.Move1_PPUps = value; break;
            case 1: pk.Move2_PPUps = value; break;
            case 2: pk.Move3_PPUps = value; break;
            case 3: pk.Move4_PPUps = value; break;
            default: throw new ArgumentOutOfRangeException(nameof(index));
        }
    }

    private static void RemoveMoveAndCompact(PKM pk, int index)
    {
        for (int i = index; i < 3; i++)
        {
            SetMove(pk, i, GetMove(pk, i + 1));
            SetMovePP(pk, i, GetMovePP(pk, i + 1));
            SetMovePPUps(pk, i, GetMovePPUps(pk, i + 1));
        }
        SetMove(pk, 3, 0);
        SetMovePP(pk, 3, 0);
        SetMovePPUps(pk, 3, 0);
    }

    private static string GetMoveName(ushort id)
    {
        var strings = GameInfo.GetStrings("es");
        return id == 0 ? "—" : NameSafe(strings.Move, id, $"Movimiento #{id}");
    }

    private static string GetSpeciesName(ushort id)
    {
        var strings = GameInfo.GetStrings("es");
        return NameSafe(strings.Species, id, $"Especie #{id}");
    }

    private static string RequirePath(string[] args, string key)
    {
        string value = RequireValue(args, key);
        string path = Path.GetFullPath(value);
        if (!File.Exists(path))
            throw new FileNotFoundException("El archivo seleccionado no existe.", path);
        return path;
    }

    private static string RequireValue(string[] args, string key)
    {
        int index = Array.FindIndex(args, x => string.Equals(x, key, StringComparison.OrdinalIgnoreCase));
        if (index < 0 || index + 1 >= args.Length || string.IsNullOrWhiteSpace(args[index + 1]))
            throw new ArgumentException($"Falta el argumento {key}.");
        return args[index + 1];
    }

    private static int RequireInt(string[] args, string key, int min, int max)
    {
        string value = RequireValue(args, key);
        if (!int.TryParse(value, out int result) || result < min || result > max)
            throw new ArgumentException($"{key} debe ser un número entre {min} y {max}.");
        return result;
    }

    private static string NameSafe(IReadOnlyList<string> names, int index, string fallback)
        => (uint)index < (uint)names.Count && !string.IsNullOrWhiteSpace(names[index]) ? names[index] : fallback;

    private static int Fail(string message)
    {
        Console.WriteLine(JsonSerializer.Serialize(new { success = false, error = message }, JsonOptions));
        return 1;
    }
}
