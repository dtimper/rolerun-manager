RoleRun Manager 1.13.0-alpha.19

CAMBIOS PRINCIPALES

- ORAS se sincroniza automáticamente al entrar en la partida:
  * al abrir una Run de Omega Rubí/Zafiro Alfa, RoleRun empieza a buscar Azahar en segundo plano;
  * si el emulador todavía está arrancando, estás en el menú o la party no es estable, reintenta silenciosamente;
  * en cuanto detecta una party válida hace la misma doble lectura y validación PK6 que antes exigía F5;
  * la primera captura actualiza RoleRun, OBS y la barra flotante sin escribir ningún byte.
- F5 se conserva como resincronización manual de emergencia, no como paso obligatorio.
- Si un F5 manual falla, RoleRun vuelve a armar automáticamente la detección en segundo plano.
- La pantalla de Configuración y los avisos de MT/mochila explican el nuevo flujo automático.

BASE CONSERVADA DE alpha.18

- Los cambios compatibles de RoleRun siguen aplicándose directamente en la RAM de Azahar.
- El archivo main sigue sin escribirse desde RoleRun; el guardado definitivo se hace dentro del juego.
- REVISAR CAMBIOS conserva el historial reversible hasta que el juego guarda main.
- La barra flotante sigue regresando a la última pestaña utilizada.

SIGUIENTE OBJETIVO PROPUESTO

Evolucionar el monitor ya existente de Azahar a una sincronización permanente juego -> RoleRun Manager,
primero para Equipo/movimientos y después, con sondeos separados, para PC e inventario.
