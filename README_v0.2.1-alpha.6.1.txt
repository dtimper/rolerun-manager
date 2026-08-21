RoleRun Manager 0.2.1-alpha.6.1

HOTFIX de alpha.6:
- Mantiene PC vivo + mochila/MT X/Y de alpha.6.
- Mantiene Citra GDB persistente de alpha.5.
- Añade bootstrap de transporte independiente: Citra recibe `continue` aunque una captura X/Y todavía no pueda empezar.
- El bootstrap no fuerza Citra: X/Y -> Azahar sigue siendo compatible y la captura validada decide el emulador activo.

Prueba principal: con GDB Stub activo, abrir X/Y en Citra debe dejar de quedarse en `Iniciando...` en cuanto RoleRun tenga abierta la Run X/Y.
