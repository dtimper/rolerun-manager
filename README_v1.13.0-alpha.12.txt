RoleRun Manager 1.13.0-alpha.12
=================================

MT ALEATORIAS DE UNIVERSAL POKÉMON RANDOMIZER FVX (ORAS)
---------------------------------------------------------
Esta alpha permite enseñar MTs de una ROM de Omega Rubí/Zafiro Alfa
randomizada con Universal Pokémon Randomizer FVX sin asumir las MT originales.

El programa usa el archivo .log que genera FVX: de él obtiene las 100 MT y la
compatibilidad real de cada especie. No abre ni modifica la ROM, el archivo
main, los estados de Azahar, la historia o la ubicación.

PRIMER USO
----------
1. Abre la Run de ORAS y pulsa F5 con Azahar abierto.
2. En un hueco vacío de movimientos, pulsa + para abrir el selector de MT.
3. Cuando pregunte por las MT originales, elige NO.
4. Selecciona el .log generado por Universal Pokémon Randomizer FVX para esta
   ROM (por ejemplo, "Twitch Zafiro Alfa 1.cxi.log").
5. RoleRun valida el log y mostrará únicamente las MT de tu mochila que ese
   Pokémon puede aprender en esta randomización y que encajen con su rol.

Al elegir ENSEÑAR, RoleRun vuelve a comprobar la MT dentro de la mochila viva
de Azahar y aplica el movimiento inmediatamente en RAM. Las MT de ORAS son
reutilizables. Guarda dentro del juego cuando quieras conservar el cambio; si
reinicias o cargas un estado sin guardar, volverá el estado de ese punto.

Para usar otro randomizer o regenerar la ROM, abre el selector de MT y pulsa
CAMBIAR LOG FVX. El nuevo perfil reemplaza al anterior solo si supera todas las
validaciones.
