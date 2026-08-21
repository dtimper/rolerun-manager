# Prueba alpha.49 — USUM PartyCount

1. Arranca UltraSol/UltraLuna con **6 Pokémon** en el equipo y abre RoleRun alpha.49.
2. Pulsa **ENVIAR AL PC** una vez. La operación debe abortar sin escribir y generar `Logs/usum_partycount_probe_latest.json`.
3. Sin usar RoleRun para mover Pokémon, entra al PC **desde el propio juego** y deposita un Pokémon, dejando exactamente **5 Pokémon** en el equipo.
4. Vuelve a RoleRun, deja que se resincronice y pulsa **ENVIAR AL PC** otra vez. Debe volver a abortar sin escribir, pero ahora el JSON incluirá una sección `comparison` entre 6 y 5.
5. Envía el `usum_partycount_probe_latest.json`.

No hace falta guardar la partida entre los pasos. Esta build es diagnóstica para cambios de tamaño; roles/movimientos siguen su flujo normal.
