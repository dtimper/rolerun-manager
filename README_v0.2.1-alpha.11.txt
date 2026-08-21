RoleRun Manager 0.2.1-alpha.11
================================

Esta build continúa 0.2.1-alpha.10 y centra el trabajo exclusivamente en
acercar las CAJAS PC de Pokémon X/Y al comportamiento ya disponible en ORAS.
El problema de Citra/GDB al usar Emulación -> Reiniciar queda APARCADO de forma
intencionada en esta versión: no se ha modificado el broker ni el protocolo GDB.

1) X/Y · CAJAS PC VIVAS AL ABRIR LA PESTAÑA
- X/Y ya disponía desde alpha.6 de un lector seguro de la matriz completa PK6
  (31 cajas x 30 huecos). Alpha.11 conecta ese lector con la pestaña CAJAS PC.
- Al entrar en CAJAS PC durante una sesión Gen 6 enlazada, RoleRun muestra la
  base del último main y lanza en segundo plano una reconciliación con la RAM.
- Solo se acepta una matriz cuya dirección pueda validarse con identidades PK6
  conocidas. Si no puede localizarse con seguridad, no se inventa ningún offset
  y se conserva la última vista conocida.
- Los Pokémon movidos entre huecos del PC desde el propio juego pueden verse al
  volver a entrar en CAJAS PC, aunque el main todavía tenga la distribución vieja.

2) X/Y · CAMBIOS DEL PC HECHOS DESDE EL JUEGO
- El reconciliador que ORAS ya usaba al cambiar la composición del equipo pasa a
  ejecutarse también para X/Y.
- Mover Pokémon (sustitución 1↔1): RoleRun puede reflejar el Pokémon saliente en
  la casilla real donde lo dejó el juego.
- Sacar Pokémon: la casilla origen detectada vacía se refleja como libre.
- Dejar Pokémon: la lectura completa permite conocer la casilla real de destino,
  algo que no puede deducirse únicamente observando la party.
- Las reglas de autoasignación/herencia de rol continúan usando la lógica común
  Gen 6 existente; alpha.11 no crea reglas nuevas específicas de X/Y.

3) HUECOS LIBRES VIVOS
- Una casilla que estaba ocupada en el último main pero que X/Y ha vaciado en RAM
  pasa a contarse como destino libre dentro de RoleRun.
- Esto evita que la interfaz siga tratando como ocupada una casilla que el propio
  juego ya liberó.

4) FUNCIONES QUE YA EXISTÍAN Y SE CONSERVAN
- Lectura viva del PC X/Y (31x30) y caché de su base RAM.
- Cambio de rol de Pokémon del PC cuando la escritura está validada.
- Sustitución Equipo ↔ PC 1↔1 desde RoleRun.
- Sustitución por muerte/cementerio en la ruta soportada.
- MTs/movimientos, roles, medallas y monitor X/Y conservan el código de alpha.10.

5) LÍMITES INTENCIONADOS DE ESTA BUILD
- NO se ha intentado arreglar Emulación -> Reiniciar de Citra con GDB activo.
- Las operaciones iniciadas desde RoleRun que cambian el tamaño de la party
  (party-to-box / box-to-party) continúan protegidas en X/Y hasta validarlas.
- Las escrituras de utilidades de inventario que X/Y todavía no tiene validadas
  siguen bloqueadas; no se habilitan por aproximación.
- Esta es la primera build para validar en una partida real la integración UI de
  las cajas vivas X/Y. Los tests prueban contratos/estructuras, no sustituyen la
  comprobación manual en Citra con tu partida real.

PRUEBAS RECOMENDADAS · X/Y / CITRA
----------------------------------
Debido al bug de reinicio aparcado, usa para estas pruebas el flujo que ya ha
funcionado: deja X/Y completamente cargado en Citra y después abre RoleRun.
No uses Emulación -> Reiniciar durante este bloque de pruebas.

A. ABRIR CAJAS PC
   1. Sincroniza X/Y con RoleRun.
   2. Entra en CAJAS PC.
   3. Comprueba que aparecen cajas y Pokémon correctamente y que no cambia nada
      que no hayas cambiado tú en el juego.

B. MOVER 1↔1 DESDE EL PC DEL JUEGO
   1. Con RoleRun abierto, sustituye directamente un Pokémon del equipo por uno
      del PC usando el propio PC de X/Y.
   2. Comprueba que Equipo se actualiza.
   3. Vuelve a CAJAS PC y verifica que el Pokémon saliente está exactamente en el
      hueco que muestra el juego.
   4. Comprueba que la herencia de rol coincide con las reglas ya validadas.

C. SACAR POKÉMON DESDE EL JUEGO
   1. Con menos de 6 Pokémon, saca uno del PC.
   2. Comprueba que RoleRun lo añade al equipo según la lógica común de roles.
   3. Verifica que su antiguo hueco aparece vacío y reutilizable en CAJAS PC.

D. DEJAR POKÉMON DESDE EL JUEGO
   1. Deposita un Pokémon del equipo en una casilla concreta.
   2. Comprueba que desaparece del equipo en RoleRun.
   3. En CAJAS PC verifica que aparece en la casilla real elegida en X/Y.

E. CAMBIO DE ROL EN PC DESDE ROLERUN
   1. Elige un Pokémon almacenado y cambia su rol.
   2. Comprueba en el juego que la marca correspondiente cambia sin moverlo.
   3. Sal y vuelve a CAJAS PC; el rol debe mantenerse.

F. SUSTITUCIÓN 1↔1 DESDE ROLERUN
   1. Usa la operación ya habilitada para intercambiar un Pokémon del equipo con
      uno del PC.
   2. Comprueba ambos lados: equipo y casilla de caja.
   3. Verifica también OBS/roles si los tienes visibles.

Si una prueba falla, indica letra, acción exacta y qué mostró X/Y frente a lo que
mostró RoleRun. Para un fallo temporal/reconciliación, el grabador de diagnóstico
sigue siendo útil.

VALIDACIÓN INTERNA
------------------
- Suite completa: 203/203 tests superados con stub gráfico.
- compileall: correcto.
