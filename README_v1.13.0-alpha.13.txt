RoleRun Manager 1.13.0-alpha.13

MT ALEATORIAS GENÉRICAS PARA ORAS / AZAHAR
==========================================

Esta alpha deja de depender del archivo .log de un randomizer concreto.
RoleRun lee las tablas que están realmente activas en la ROM/capa con la que
Azahar ha iniciado Pokémon Omega Rubí o Zafiro Alfa:

- Qué movimiento enseña cada una de las 100 MT.
- Qué especies y formas pueden aprender cada MT.
- La actualización instalada y las capas ExeFS/RomFS de Azahar.
- Parches IPS y BPS de ExeFS que Azahar tenga activos.

Por eso sirve con cualquier randomizer que preserve la estructura nativa de
ORAS, no solo Universal Pokémon Randomizer FVX. No se modifica la ROM, la
capa, el archivo main ni se guarda la partida automáticamente.

PRUEBA RECOMENDADA
==================

1. Cierra cualquier RoleRun Manager anterior y extrae esta carpeta sustituyendo
   la anterior.
2. Abre tu ROM randomizada en Azahar y entra en la partida normalmente.
3. Pulsa F5 en RoleRun. Debe aparecer ORAS sincronizado.
4. En Equipo, pulsa + en un hueco de ataque vacío de un Pokémon.
5. RoleRun debe abrir el selector sin pedir un .log y mostrar una línea verde
   que empieza por: "ROM ORAS leída".
6. Comprueba una MT cuyo resultado conozcas en tu randomización y enséñasela.
   La MT sigue siendo reutilizable, como en ORAS.

SI NO LOCALIZA LA ROM AUTOMÁTICAMENTE
=====================================

El selector ofrecerá elegir manualmente el .cxi, .3ds o .app que está abierto
en Azahar. Selecciónalo: RoleRun lo valida contra el proceso sango-1/sango-2 y
lee sus datos. No hace falta buscar ni entregar el .log del randomizer.

SEGURIDAD Y LÍMITES
===================

El lector no adivina datos. Solo habilita una MT si encuentra una sola tabla
ORAS válida, los 100 movimientos están dentro del catálogo de Generación 6 y
el GARC personal cubre las 721 especies. Si una ROM está cifrada, ha cambiado
esa estructura de forma no estándar o el parche no corresponde a la base
abierta, RoleRun muestra el motivo y no escribe nada.

Esta alpha sigue modificando solo la RAM viva de Azahar tras cada verificación.
Guardar dentro del juego sigue siendo decisión del jugador.
