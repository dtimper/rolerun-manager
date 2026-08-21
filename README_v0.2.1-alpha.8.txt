RoleRun Manager 0.2.1-alpha.8
================================

PRIORIDAD: Citra reconectable sin reiniciar el juego
----------------------------------------------------
- X/Y en Citra usa ahora un broker local persistente.
- El broker mantiene viva la única sesión GDB aunque cierres RoleRun Manager.
- Puedes cerrar y volver a abrir RoleRun sin cerrar Pokémon X/Y ni Citra.
- Si Citra se reinicia, el broker descarta el socket obsoleto y vuelve a enlazar en el siguiente intento.
- El broker se inicia solo; no hay que ejecutar ningún programa adicional.
- X/Y -> Azahar sigue funcionando y no usa este broker.

IMPORTANTE AL ACTUALIZAR DESDE ALPHA.7
--------------------------------------
Alpha.7 cerraba directamente la sesión GDB al salir. Si ya cerraste alpha.7 y el
GDB Stub de Citra quedó apagado para esa sesión, haz UN reinicio limpio de Citra
al estrenar alpha.8. A partir de ese momento el broker evita tener que repetirlo.

BAJAS X/Y
---------
- La sonda ya no intenta adivinar el Pokémon activo comparando PS máximos.
- Lee los seis punteros de party de batalla por slot real.
- Una transición PS > 0 -> 0 puede registrar la baja durante el combate incluso
  si dos Pokémon tienen los mismos PS máximos.
- Se conserva la señal de fin de combate de alpha.7 para no abrir el selector antes de tiempo.
- La consecuencia visual sigue teniendo ~1 s de delay intencionado.

MT/MO X/Y
---------
- Corregido el tamaño del bolsillo: 100 MT + 5 MO = 105 registros = 0x1A4 bytes.
- Alpha.7 usaba 0x1A8 y podía leer 4 bytes del bolsillo siguiente y rechazar una mochila real.
- Se prueban las bases conocidas de X/Y v1.5 (0x08C67D24) y v1.0 (0x08C67D14).
- Si acabas de obtener tu primera MT y todavía no has guardado, RoleRun puede localizarla
  directamente en RAM sin depender de testigos del último main.

PRUEBA RECOMENDADA
------------------
1. Para el primer arranque desde alpha.7, reinicia Citra una vez y abre alpha.8.
2. Comprueba X/Y en vivo.
3. Cierra SOLO RoleRun Manager, deja Citra y el juego abiertos, espera unos segundos.
4. Abre alpha.8 otra vez: debe reconectar sin tocar Citra.
5. Repite una segunda vez para confirmar que no depende del orden de apertura.
6. En combate, deja debilitarse un Pokémon: tras ~1 s deben bajar las vidas y desaparecer su slot proyectado; el selector debe esperar al final del combate.
7. Pulsa + en un Pokémon y comprueba que la MT recién obtenida en el gimnasio aparece sin guardar.
