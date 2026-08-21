ROLERUN MANAGER v1.6.0-alpha.4
================================

Aplicación automática de cambios durante Reset en DeSmuME.

- Los .dsv pueden mantenerse abiertos mientras se leen.
- Si DeSmuME bloquea la escritura, GUARDAR CAMBIOS prepara y valida el nuevo .dsv.
- RoleRun Manager intenta instalarlo cada 25 ms y aprovecha la ventana en la que DeSmuME libera el archivo durante Reset.
- El estado superior muestra "Esperando al reinicio del juego".
- Si DeSmuME guarda después de preparar el cambio, la instalación se cancela para proteger el progreso nuevo.
- Al completarse, el guardado se vuelve a abrir, validar y sincronizar con OBS.
- Se mantienen la copia visible anterior y el backup interno.
