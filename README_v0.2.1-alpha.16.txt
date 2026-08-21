RoleRun Manager v0.2.1-alpha.16

OBJETIVO
- Corregir la detección de medallas X/Y usando evidencia binaria real pre/post gimnasio.

HALLAZGOS CONFIRMADOS
- En el main real de Pokémon X, Misc+0x0C cambia 0x00 -> 0x01 al obtener la primera medalla.
- El campo Badges es un contador decimal 0..8, no una máscara de bits.
- El bloque SUBE guarda la party vencedora desde +0x2C.
- Las cabeceras u32 conceptualmente llamadas "SUBE" aparecen en bytes como "EBUS" por little-endian.
- Alpha.14/15 buscaban literalmente b"SUBE" en RAM, por lo que nunca podían localizar una copia SUBE real.

CAMBIO
- El localizador vivo de SUBE busca ahora la secuencia real b"EBUS".
- El parser de Misc vuelve a leer el byte como contador 0..8.
- No se modifica PC, muertes, roles, movimientos, batalla ni inventario.

PRUEBA MANUAL
1. Abre Pokémon X en AzaharPlus con RPC activo.
2. Abre RoleRun alpha.16.
3. Con una medalla ya obtenida, el Dashboard debe mostrar 1.
4. La línea superior debería indicar "medallas SUBE:1" si la copia viva se localiza.
5. Para la siguiente medalla, comprueba que el contador pase 1 -> 2 sin necesidad de guardar primero.
