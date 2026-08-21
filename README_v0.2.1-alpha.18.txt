RoleRun Manager v0.2.1-alpha.18

Corrección focalizada de las utilidades de inventario en X/Y.

Problema encontrado en alpha.17
------------------------------
La ruta X/Y de escritura de Caramelo Raro ×999, Repelente Máximo ×999 y Dinero máximo ya existía en XYLiveWriter y estaba validada por tests, pero la capa de UI seguía clasificando PendingInventoryChange como una operación no soportada para X/Y. Por eso la aplicación se detenía antes de llegar al escritor y mostraba "Esta operación requiere el flujo manual".

Cambio de alpha.18
------------------
- PendingInventoryChange pasa a estar permitido por el gate vivo de X/Y en la UI.
- Se mantiene intacta la protección del propio XYLiveWriter: localización por testigos, preflight, verificación y rollback.
- No se modifica la lógica de PC, muertes, medallas, roles, movimientos ni MT.

Prueba manual recomendada
-------------------------
1. Pokémon X abierto en AzaharPlus con RPC activo y partida en overworld.
2. RoleRun alpha.18 conectado en vivo.
3. Probar primero Caramelo Raro ×999.
4. Verificar el resultado dentro de la mochila del juego.
5. Si funciona, probar Repelente Máximo ×999.
6. Si funciona, probar Dinero máximo y comprobar 9.999.999.
7. Si alguna operación muestra un error de calibración/verificación, detener las pruebas y conservar el mensaje exacto.
