RoleRun Manager v0.2.2-alpha.26
=====================================

OBJETIVO
--------
Corregir los metadatos incorrectos de Pokémon almacenados en cajas: nivel 0 y nombres de habilidad numéricos.

CAUSA DEMOSTRADA
-----------------
Un PK6/PK7 almacenado en caja ocupa 0xE8 bytes y no contiene la extensión de party donde RoleRun leía el byte de nivel. El parser anterior rellenaba deliberadamente level=0.

PKHeX deriva CurrentLevel desde la experiencia acumulada (EXP) y la curva EXPGrowth de la tabla personal de la especie/forma. Alpha.26 replica ese cálculo para Pokémon stored.

HABILIDADES
-----------
El PK6/PK7 sí contiene Ability ID. RoleRun ya no usa Habilidad #<id> como salida normal: resuelve el ID mediante el catálogo español incluido en PKHeX.Core. Por ejemplo, Ability ID 92 = Encadenado.

ALCANCE
-------
- Pokémon Sol/Luna: PC live de alpha.25 mantiene su localización/validación y ahora muestra nivel/habilidad derivados.
- ORAS: el mismo parser PK6 de caja recibe la corrección.
- X/Y: comparte PK6 pero selecciona su tabla personal específica.
- Party Gen 6/7: conserva el nivel live de su extensión party y mejora el nombre de habilidad.

PRUEBA MANUAL
-------------
1. Abre la misma partida de Pokémon Sol usada para validar alpha.25.
2. F5 -> CAJAS PC.
3. Comprueba el Pikipek/Ledyba visibles: ya no deben aparecer como Nv. 0.
4. Selecciona Pikipek y comprueba que Habilidad #92 pasa a Encadenado.
5. Compara los niveles mostrados por RoleRun con los niveles reales del juego.
6. Mueve un Pokémon dentro del PC desde el juego y confirma que, tras la reconciliación, conserva nivel y habilidad correctos.
7. Si tienes acceso a la partida ORAS donde viste Nv. 0/Habilidad #, comprueba también CAJAS PC allí.

SEGURIDAD
---------
- El PC de Sol/Luna continúa SOLO LECTURA en alpha.26.
- No cambia la dirección/cadena de validación del PC SM validada en alpha.25.
- No se habilitan escrituras Equipo <-> PC hasta cerrar lectura/sincronización de cajas.
