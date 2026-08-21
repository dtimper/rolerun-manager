RoleRun Manager v0.2.2-alpha.23

Objetivo de esta alpha
======================
Localizar y leer el PC vivo de Pokémon Sol/Luna aunque el último main se guardase
con las cajas vacías, sin depender de la contigüidad de bloques del archivo SAV7SM.

Qué demostró alpha.22
=====================
El diagnóstico real de la partida mostró una única party host válida y un bloque
Items vivo demostrado, pero el supuesto Misc = Items + 0x4000 solo conservaba 19
bytes iguales de 0x200 y ninguna ventana estructural válida.

Eso demuestra que los offsets contiguos del archivo SAV7SM no pueden trasladarse
como relaciones de RAM viva. Alpha.23 deja de usar esa relación para el PC.

Nuevo localizador directo
=========================
1. La party viva sigue siendo el ancla host ya demostrada.
2. RoleRun recorre únicamente la misma región RW de Azahar que contiene esa party.
3. Busca registros de 0xE8 que puedan ser PK7 de caja.
4. Cada registro no vacío debe superar sanity, descifrado, checksum y especie.
5. Se buscan exactamente 960 slots consecutivos (32 cajas x 30 huecos).
6. Cada slot debe ser cero o un PK7 válido.
7. Si la carrera válida es mayor de 960, la frontera es ambigua y se rechaza.
8. La base host candidata se proyecta a guest usando solo el delta de la party host
   ya demostrada.
9. La matriz completa se relee dos veces en host y dos veces por RPC guest.
10. Las cuatro lecturas deben ser idénticas antes de publicar una sola caja.

Seguridad
=========
- No usa BoxPokemon = Items + offset.
- No necesita Pokémon guardados en el main.
- No publica un PC vacío cuando la prueba falla.
- Varias matrices completas válidas abortan.
- Una identidad recién movida party→PC, cuando existe, debe aparecer en la matriz.
- Una matriz que contiene también un Pokémon de la party actual se rechaza.
- Las escrituras Equipo <-> PC continúan bloqueadas.

Prueba solicitada
=================
1. No guardes la partida para actualizar el main.
2. Abre Pokémon Sol en el overworld y pulsa F5.
3. Entra en CAJAS PC.
4. Comprueba que aparecen los Pokémon que existen ahora mismo en las cajas.
5. Desde el juego, mueve un Pokémon entre dos huecos del PC y comprueba la sincronía.
6. Deposita uno del equipo y comprueba Equipo + PC.
7. Saca uno del PC y vuelve a comprobar ambos lados.

Si falla, envía:
Documentos\RoleRun Manager\Logs\sm_pc_diagnostic_latest.json

El JSON debe indicar version 0.2.2-alpha.23.

Validación automática
=====================
309 tests pasan.
