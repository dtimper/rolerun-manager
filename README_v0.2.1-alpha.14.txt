RoleRun Manager v0.2.1-alpha.14
================================

OBJETIVO DE ESTA BUILD
----------------------
Corregir exclusivamente la lectura de medallas de Pokémon X/Y en tiempo real tras la validación real de alpha.13 sobre AzaharPlus.

En la prueba real con Pokémon X + AzaharPlus 2126.0-A + RPC:
- equipo: OK,
- roles: OK,
- Cajas PC (sacar/dejar): OK,
- muerte y selector post-combate: OK,
- medallas: NO actualizaban; el estado permanecía en "MiscXY:0".

Alpha.14 no modifica los subsistemas que ya han funcionado en esas pruebas.

QUÉ SE HA CORREGIDO
-------------------
Alpha.13 leía las medallas desde una copia viva candidata del bloque Misc de X/Y. La dirección era validada estructuralmente y el byte de medallas dentro de Misc era correcto, pero en la sesión real de AzaharPlus esa copia seguía devolviendo 0 después de conseguir una medalla.

Para no sustituir una dirección dudosa por otra inventada, alpha.14 añade una segunda fuente independiente y demostrable: el bloque SubEventLog (SUBE) de X/Y.

Según la estructura de guardado Gen 6 usada por PKHeX:
- SubEventLog X/Y está en el bloque de guardado de offset 0x1D800 y tamaño 0x308.
- Guarda 8 registros de victoria de gimnasio, cada uno con hasta 6 IDs de especie.
- El propio bloque contiene cuatro firmas estructurales "SUBE".

RoleRun usa esos datos para contar las victorias de gimnasio en vivo.

LOCALIZACIÓN EN RAM SIN OFFSET INVENTADO
-----------------------------------------
No se ha añadido una dirección RAM fija nueva para SUBE.

En la primera lectura de una sesión:
1. RoleRun busca la firma estructural del bloque SUBE en memoria X/Y.
2. Solo acepta una candidata que contenga las cuatro firmas "SUBE" en sus posiciones internas correctas.
3. Valida los 8 registros de gimnasio como IDs de especie Gen 6 válidos y exige una progresión consecutiva de medallas.
4. Si hay varias copias válidas al calibrar, elige la que tenga mayor progreso de gimnasio; esto evita preferir una copia histórica con 0 frente a una viva con 1.
5. Una vez demostrada una base, la cachea para la sesión. Si un save-state hace retroceder el progreso, conserva esa misma base mientras siga siendo un SUBE válido; no salta a otra copia solo porque tenga más medallas.

Si SUBE no puede localizarse de forma segura, la ruta Misc existente de alpha.13 continúa como fallback. El `main` sigue siendo el último fallback, igual que antes.

DIAGNÓSTICO
-----------
Cuando la fuente nueva funciona, la cabecera de RoleRun debe mostrar:

    medallas SUBE:<número>

El recorder/diagnóstico de tiempo real incluye también el bloque SUBE resuelto una vez localizado, para poder analizar una sesión real si el contador siguiera fallando.

PRUEBA MANUAL RECOMENDADA
-------------------------
1. Abre Pokémon X/Y en AzaharPlus con "Activar servidor RPC" habilitado y GDB deshabilitado.
2. Carga la partida y llega al overworld.
3. Abre RoleRun Manager v0.2.1-alpha.14.
4. Mira la cabecera superior.
   ESPERADO: tras la calibración inicial aparece `medallas SUBE:N` y N coincide con las medallas reales de la partida.
5. Comprueba el contador MEDALLAS del Dashboard.
   ESPERADO: coincide con N.
6. Si estás justo antes de conseguir una medalla, gana el gimnasio SIN guardar ni reiniciar.
   ESPERADO: el contador pasa de N a N+1 en vivo.
7. Haz una comprobación rápida de los subsistemas ya validados:
   - Equipo sigue leyendo correctamente.
   - Un cambio de rol sigue aplicándose.
   - Cajas PC sigue reflejando sacar/dejar Pokémon.
   No es necesario repetir las pruebas exhaustivas de alpha.13.

SI SIGUE FALLANDO
-----------------
No cambies ROM, RPC, offsets ni otras configuraciones a ciegas.

Si sigue mostrando 0 o la cabecera no cambia a `medallas SUBE:N`, genera el paquete de diagnóstico/replay del Real-Time Core con X/Y abierto. Alpha.14 ya incluye el bloque SUBE resuelto en la captura cuando consigue localizarlo, por lo que esa prueba dará información concreta para la siguiente corrección.

VALIDACIÓN INTERNA
------------------
- Nueva regresión que reproduce el fallo observado: Misc vivo permanece en 0 y SUBE vivo contiene 1 victoria -> RoleRun devuelve 1 desde SUBE.
- Regresiones para 0, 3 y 8 medallas guardadas.
- Rechazo de historiales no consecutivos y de IDs de especie imposibles.
- Regresión de save-state: una base SUBE ya validada puede retroceder sin saltar a otra copia.
- Suite completa: 212/212 pruebas con stub gráfico temporal de test.
- compileall correcto.
