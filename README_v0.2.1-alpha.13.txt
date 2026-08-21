RoleRun Manager v0.2.1-alpha.13
================================

OBJETIVO DE ESTA BUILD
----------------------
Corregir dos problemas detectados durante las pruebas reales de Pokémon X en Citra:

1) Cajas PC podía mostrar "0 Pokémon" aunque el juego tuviera un Pokémon depositado.
2) F5 mostraba "CAMBIOS PENDIENTES PROTEGIDOS" y pedía guardar/descartar incluso en el flujo de cambios instantáneos.

CAMBIO PRINCIPAL: PC X/Y CALIBRADO CON UN POKÉMON REAL
------------------------------------------------------
Alpha.12 trataba 0x08C861C8 como base suficiente cuando el último main no tenía Pokémon en cajas. Esa dirección está documentada en herramientas Gen 6, pero una región llena de ceros no demuestra que sea la copia viva usada por la sesión concreta de Citra.

Alpha.13 ya no publica "PC vacío" por ese motivo cuando existe evidencia contraria.

Cuando RoleRun observa que un Pokémon acaba de desaparecer de la party:
- conserva su identidad estable (especie + PID + TID + SID),
- lo pasa al lector del PC como testigo SIN inventar caja/slot,
- comprueba candidatas alrededor de la base documentada,
- solo acepta una candidata si contiene exactamente ese PK6 válido,
- después lee y valida la matriz 31x30 completa,
- si no puede demostrar una base, mantiene la última vista y avisa; no enseña una caja vacía falsa.

La primera conexión automática también dispara esta reconciliación si RoleRun se abre después de haber hecho el depósito en el juego.

F5
---
F5 no guarda cambios en el modo Gen 6 en vivo.

- Si queda una acción compatible terminando de aplicarse/verificarse en RAM, RoleRun solicita su aplicación inmediata y avisa de que F5 está esperando esa confirmación.
- Si queda una operación todavía no soportada en tiempo real, RoleRun lo indica expresamente y no habla de "guardar".
- El falso ENVIAR AL PC de alpha.11 ya estaba bloqueado en alpha.12 y continúa bloqueado: no crea una proyección ni un cambio pendiente.

PRUEBA MANUAL RECOMENDADA
-------------------------
IMPORTANTE: sigue evitando Emulación -> Reiniciar con RoleRun conectado; ese bug de Citra/GDB continúa aparcado deliberadamente.

1. Arranca Pokémon X/Y completamente.
2. Abre RoleRun Manager.
3. Confirma que Equipo está sincronizado.
4. Desde el PC DEL JUEGO, deja un Pokémon en una caja. Para repetir exactamente el caso diagnosticado, Caja 1 / hueco 1 es ideal, pero el localizador no depende de esa posición.
5. Espera a que termine la lectura de PC y abre/actualiza CAJAS PC.
   ESPERADO: el Pokémon aparece en la caja/hueco real.
6. Sácalo de nuevo desde el juego.
   ESPERADO: vuelve al equipo y la casilla queda libre en RoleRun.
7. Pulsa F5 cuando no haya ninguna escritura en curso.
   ESPERADO: F5 actúa como resincronización y no pide "guardar cambios".

Si el PC no puede localizarse, alpha.13 debe mostrar un aviso explícito en vez de afirmar que la caja está vacía. Ese aviso será información útil para ampliar el rango de calibración sin escribir a ciegas.

VALIDACIÓN INTERNA
------------------
- Suite completa: 208/208 tests.
- compileall correcto.
- citra_broker.py y citra_gdb.py permanecen sin cambios respecto a alpha.12.
