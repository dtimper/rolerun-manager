RoleRun Manager v0.2.2-alpha.16 — Pokémon Sol/Luna · MT EN VIVO
=================================================================

OBJETIVO DE ESTA ALPHA
----------------------
Habilitar el flujo de MT de Sol/Luna sin usar tablas vanilla ni direcciones RAM inventadas.

QUÉ CAMBIA
----------
- Lee las 100 MT desde el ExeFS .code de la ROM Sol/Luna configurada.
- Valida que la ROM sea la misma edición (Sol o Luna) que está abierta en Azahar cuando el Title ID está disponible.
- Tiene en cuenta code.bin / IPS / BPS de las capas ExeFS que RoleRun puede demostrar desde la configuración de Azahar o junto a la ROM.
- Lee las MT que existen AHORA en la mochila viva de Sol/Luna.
- La mochila se localiza dentro del mismo backing FCRAM ya demostrado por la party; se exige una única copia host+guest.
- Si el bloque ya cambió respecto al último main, usa testigos estructurales distribuidos y exige una única estructura fuerte.
- Enseñar una MT modifica únicamente el PK7 del Pokémon; la MT no se consume.
- Antes de escribir el PK7, RoleRun vuelve a comprobar que la MT elegida sigue presente en la mochila viva de la misma sesión.
- PendingTMTeach ya es compatible con el backend live de Sol/Luna.
- El selector sigue ignorando compatibilidad vanilla de especie: mandan las reglas RoleRun.
- Sustituto sigue permitido para Asesino y Mago mediante las reglas globales ya existentes.

SEGURIDAD
---------
- Si la tabla de MT de la ROM no es única o contiene movimientos fuera del catálogo del guardado, se aborta.
- Si la ROM no coincide con la edición abierta, se aborta.
- Si la mochila viva no puede demostrarse de forma única, se aborta.
- Si la MT desaparece entre abrir el selector y aplicar el cambio, se aborta antes de escribir el Pokémon.
- El writer PK7 conserva validación de identidad, checksum, relectura y rollback de alpha.15.

PRUEBAS AUTOMÁTICAS
-------------------
283/283 tests pasan en el entorno de desarrollo de esta build.

PRUEBAS MANUALES RECOMENDADAS
-----------------------------
1. Entra al overworld de Pokémon Sol/Luna y pulsa F5.
2. Abre Equipo y pulsa + en un hueco de movimiento.
3. Comprueba que aparecen únicamente MT que posees realmente y que el movimiento corresponde a la MT de tu ROM/randomización.
4. Enseña una MT y comprueba inmediatamente el movimiento dentro del juego.
5. Comprueba que la MT sigue en la mochila después de enseñarla.
6. Prueba una MT en un Pokémon cuya compatibilidad vanilla no la permitiría, siempre que el rol sí la permita.
7. Con Asesino o Mago, si tienes Sustituto como MT, comprueba que aparece como compatible.
8. Sustituye un movimiento ya ocupado mediante SUSTITUIR y verifica el cambio dentro del juego.
9. Guarda desde el juego, reinicia la emulación y comprueba persistencia.
10. Regresión rápida: cambia un rol y confirma que Caramelo Raro, Repelente Máximo y Dinero máximo siguen funcionando.

Si el selector no puede demostrar la mochila, guarda dentro del juego, vuelve al overworld, pulsa F5 y repite. No se escribe ningún byte cuando falla la validación.
