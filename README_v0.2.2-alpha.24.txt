RoleRun Manager v0.2.2-alpha.24

Objetivo de esta alpha
======================
Corregir el falso aborto del localizador directo de BoxPokemon observado en la
RAM real de Azahar con alpha.23, manteniendo el PC de Sol/Luna en solo lectura.

Qué demostró el diagnóstico alpha.23
====================================
La región RW que contiene la party host válida mide aproximadamente 256 MiB.
Alpha.23 abortó en el prefiltrado con:

  "demasiados registros con sanity cero"

Ese límite se aplicaba ANTES de descifrar/checksum/especie. En memoria arbitraria
un par 00 00 en el campo que ocuparía sanity no demuestra que exista un PK7.
Por tanto ese contador podía agotarse con ventanas falsas y no llegar nunca a
los Pokémon reales de las cajas.

Corrección alpha.24
===================
1. Se sigue recorriendo únicamente la región RW ya anclada por una party host
   demostrada.
2. sanity == 0 pasa a ser solo un prefiltrado barato.
3. Cada ventana no vacía se valida inmediatamente como PK7 almacenado:
   representación plain/encrypted, descifrado, checksum y especie Gen7 válida.
4. Solo los PK7 ocupados que superan esa validación se conservan y cuentan hacia
   el límite de seguridad.
5. Las ventanas que solo tienen sanity == 0 ya no pueden provocar por sí mismas
   el aborto de 32.768 candidatos.
6. El diagnóstico separa ahora sanity hits, candidatos no vacíos, rechazos
   semánticos y PK7 realmente aceptados.
7. La prueba final no cambia: para publicar PC sigue siendo obligatorio demostrar
   una única carrera exacta de 960 slots y después igualdad estable de la matriz
   completa host <-> guest RPC.

Seguridad
=========
- No se añade ninguna dirección RAM de cajas.
- No se usa el main para exigir Pokémon en PC.
- No se recupera la relación Items/Misc/BoxPokemon descartada por evidencia real.
- Varias matrices completas siguen abortando.
- Las escrituras Equipo <-> PC y roles en cajas siguen bloqueadas.

Prueba solicitada
=================
1. No guardes para actualizar el main.
2. Abre Pokémon Sol en overworld y pulsa F5.
3. Entra en CAJAS PC.
4. Si aparecen las cajas, compara Pokémon/slots con el juego y mueve uno desde el
   propio juego para validar sincronía.
5. Si falla, envía Documentos\RoleRun Manager\Logs\sm_pc_diagnostic_latest.json.

El JSON debe indicar version 0.2.2-alpha.24.

Validación automática
=====================
310 tests pasan.
