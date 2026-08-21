RoleRun Manager 0.2.1-alpha.4
================================

OBJETIVO DE ESTA ALPHA
----------------------
Añadir compatibilidad X/Y -> Citra SIN eliminar X/Y -> Azahar. Esta versión es
la primera prueba del Real-Time Core cambiando no solo de juego, sino también de
emulador/transporte.

X/Y MULTI-EMULADOR
------------------
RoleRun intenta automáticamente:
1. Azahar mediante RPC UDP (ruta conservada de alpha.3).
2. Citra mediante su GDB Stub / Remote Serial Protocol.

Cuando una ruta funciona, se mantiene como preferida para capturas y escrituras.
Si deja de responder, RoleRun vuelve a sondear la otra. Nunca se escribe en un
emulador distinto del que produjo el último snapshot válido.

CITRA: PREPARACIÓN NECESARIA
----------------------------
El Citra clásico no expone el RPC de Azahar. Para permitir lectura/escritura de
la RAM hay que activar su GDB Stub:

1. Abre Citra.
2. Emulación -> Configurar -> General -> Debug/Depuración.
3. Activa "Enable GDB Stub" / "Use GDB Stub".
4. Mantén el puerto 24689 (RoleRun también lee el puerto configurado cuando
   encuentra qt-config.ini).
5. Reinicia el juego si Citra lo requiere.
6. Abre RoleRun y entra en la Run de X/Y.

RoleRun busca automáticamente la configuración habitual de Citra y también
acepta la variable ROLERUN_CITRA_GDB_PORT para instalaciones personalizadas.

X/Y EN CITRA — ALPHA.4
-----------------------
- Equipo vivo.
- Cambios juego -> RoleRun sin guardar main.
- Roles/marcadores en ambas direcciones.
- Movimientos del equipo en ambas direcciones con verificación.
- Mismo RealTimeSnapshot, eventos, diagnóstico y replay.
- La cabecera identifica el emulador activo.
- Se elimina GUARDAR CAMBIOS/DESCARTAR para X/Y: el modelo de edición es live,
  igual que ORAS.

Las medallas de X/Y en Citra usan temporalmente el último main como fallback.
El detector live de Misc de alpha.3 sigue activo en Azahar. Se ha evitado hacer
el barrido grande por GDB en esta alpha porque algunos Citra clásicos detienen
la CPU mientras el debugger está adjunto; primero queremos validar el transporte
party/roles/movimientos sin introducir congelaciones largas.

SIGUE PENDIENTE EN X/Y
----------------------
- PC vivo y Equipo <-> PC.
- Mochila MT/MO viva y selector MT.
- Inventario vivo.
- Sonda de batalla.
- Medallas 100% live en Citra.
- Flujo completo de bajas/sustituciones dependiente del PC.

ORAS
----
ORAS/Azahar permanece sin cambios funcionales. Medallas, MT, PC, inventario,
bajas, sustituciones y el resto de funciones vivas siguen utilizando la ruta
validada anteriormente.

PRUEBA RECOMENDADA EN CITRA
----------------------------
1. Activa GDB Stub y abre X/Y.
2. Abre RoleRun. Arriba debe pasar de "Esperando X/Y en Azahar/Citra" a
   "X/Y en vivo ... Citra".
3. Cambia un marcador de rol DESDE EL JUEGO sin guardar: RoleRun debe actualizarse.
4. Cambia el rol desde RoleRun: el marcador debe cambiar inmediatamente en X/Y.
5. Sustituye un movimiento mediante un drafteo normal: debe verse en el juego.
6. Graba 5-10 segundos desde Configuración -> Real-Time Core y abre el replay.
   El adaptador debe figurar como `xy-citra-gdb`.

Si Citra no conecta, el diagnóstico indicará que hay que activar el GDB Stub y
qué puerto está intentando usar RoleRun.
