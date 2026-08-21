RoleRun Manager 1.12.0

GESTIÓN DE EQUIPO Y PC
- RoleRun Manager puede leer el PC completo de todos los juegos soportados mediante PKHeX.Core.
- La pestaña EQUIPO incorpora CONSULTAR PC y los huecos libres muestran un botón + / ABRIR PC.
- Se puede enviar un Pokémon del equipo al primer hueco libre del PC, incorporar uno desde una caja o hacer un intercambio Equipo ↔ PC.
- Al enviar un Pokémon al PC, el equipo se compacta de forma segura y nunca se escribe un hueco intermedio en la party.
- Los Pokémon del PC conservan sus datos y marcadores de rol salvo cuando una operación cambia expresamente su rol.
- El selector del PC permite navegar por todas las cajas, consultar sprite, nivel, rol registrado, habilidad, objeto y movimientos.
- Con las reglas activas, el selector muestra la compatibilidad del Pokémon con el rol que va a ocupar y prepara la eliminación de movimientos incompatibles antes de incorporarlo.

JERARQUÍA DE ROLES
- Con REGLAS DE ROL ACTIVAS, cada Pokémon del equipo debe tener exactamente un rol y no puede haber dos Pokémon activos con el mismo rol.
- Ya no es obligatorio ocupar los seis roles: se puede jugar legalmente con menos de seis Pokémon y dejar huecos libres.
- Al intentar asignar un rol ocupado se puede TRANSFERIR ROL, INTERCAMBIAR ROLES, ENVIAR ANTERIOR AL PC o SUSTITUIR DESDE EL PC.
- Un Pokémon desplazado puede quedar temporalmente SIN ROL mientras se reorganiza el equipo, pero no se permite GUARDAR hasta resolver la composición.
- Si el guardado cambia desde el propio juego y aparecen roles duplicados o un Pokémon activo sin rol, el Manager lo detecta automáticamente y abre una resolución guiada.
- Dashboard y Equipo mantienen una alerta EQUIPO IRREGULAR hasta que se resuelva el conflicto.

REGLAS Y DRAFTEOS
- Se mantiene la FASE DE PREPARACIÓN antes del primer líder: las restricciones no se fuerzan hasta activar las reglas.
- Support no puede usar movimientos de protección y esos movimientos tampoco aparecen en sus drafteos.
- No se han añadido cambios a las reglas globales de Velocidad.
- Un movimiento obtenido con otro rol puede conservarse tras un cambio de rol siempre que sea legal para el nuevo rol.

AYUDA
- Nuevo bloque visual ¿QUÉ ES ROLERUN? para explicar el formato a usuarios que todavía no lo conocen.
- La Ayuda documenta Equipo ↔ PC, huecos libres, roles únicos, detección de conflictos y la posibilidad de jugar con menos de seis Pokémon.

SEGURIDAD
- Las operaciones Equipo ↔ PC se escriben primero en un guardado temporal y se validan antes de sustituir el archivo activo.
- El motor comprueba identidad, movimientos, rol solicitado y resultado del intercambio.
- Se siguen creando copias de seguridad fechadas antes de guardar.

IMPORTANTE
Esta versión añade comandos nuevos al motor de guardados. Ejecuta preparar_motor.bat una vez antes de usar la gestión del PC. Si abres con instalar_y_abrir.bat, el propio lanzador detectará un motor antiguo y solicitará actualizarlo.
