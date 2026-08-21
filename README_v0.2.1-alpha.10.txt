RoleRun Manager 0.2.1-alpha.10
================================

Esta build parte de 0.2.1-alpha.8 (la última base validada antes de la regresión
alpha.9) y corrige tres problemas observados en una prueba real de X/Y/Citra.

1) REINICIO INTERNO DE CITRA
- Broker Citra v3 (puerto local 24791) para no reutilizar brokers antiguos.
- Watchdog independiente de la ventana de RoleRun: mantiene/reengancha GDB aunque
  no haya un snapshot en curso.
- Consume stop-replies de reinicio y envía continue automáticamente.
- Si Citra recrea el socket GDB, el broker detecta EOF, espera al nuevo listener
  y se vuelve a adjuntar sin pedir cerrar el emulador.

2) MUERTES X/Y SIN FALSOS POSITIVOS
- Eliminada la interpretación errónea de 0x081FB284+n*4 como seis slots.
- X/Y usa PARTY_1/PARTY_2 como dos copias redundantes del battler ACTIVO.
- El rival usa su propio par redundante y nunca puede restar vidas del jugador.
- El battler activo solo se asocia a un Pokémon cuando la identidad es segura.
- Tras una baja, 0 -> PS positivos fuerza remapeo al Pokémon que entra.
- Si hay ambigüedad, RoleRun espera al fallback post-combate antes que inventar
  una muerte.

3) COMPATIBILIDAD MT DE LA CAPA EFECTIVA
- La mochila RAM de alpha.8 se conserva.
- El perfil X/Y ya no lee obligatoriamente solo el .3ds base: en Citra/Azahar
  combina ROM, actualización y load/mods/<TitleID> cuando existen.
- Si un randomizer sustituye romfs/a/2/1/8, esa tabla de compatibilidad es la que
  usa RoleRun.
- También se respetan code.bin / IPS / BPS para la tabla MT->movimiento.
- La ventana MT muestra la fuente efectiva en la línea verde.

PRUEBAS RECOMENDADAS
--------------------
Al pasar desde alpha.8/alpha.9, haz UNA vez un inicio limpio cerrando Citra y
RoleRun; el nuevo broker usa otro protocolo/puerto. Después:

A. Reinicia Pokémon X desde Emulación -> Reiniciar. Debe salir de "Iniciando"
   sin cerrar RoleRun ni Citra.
B. En combate: deja morir un Pokémon, saca otro sano y derrota un Pokémon rival.
   Solo la primera acción debe restar una vida.
C. En la mochila del propio juego identifica un Pokémon al que X/Y permita usar
   MT83 Acoso y prueba exactamente ese Pokémon desde el botón + de RoleRun.
   Mira también la línea verde: si hay LayeredFS debe mencionar "mod RomFS personal".

GRABADOR / REPLAY
-----------------
Úsalo cuando el bug dependa de una transición temporal: cambio de Pokémon en
combate, muerte, cambio de PC, medalla, save state, reconexión, objeto recién
obtenido, etc. No hace falta para errores estáticos de layout ni para una tabla
ROM que se rechaza siempre igual, salvo que se pida expresamente.
