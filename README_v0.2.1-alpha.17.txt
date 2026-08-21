RoleRun Manager v0.2.1-alpha.17
================================

OBJETIVO DE ESTA BUILD
----------------------
Esta alpha combina dos frentes:

1) cerrar la principal diferencia funcional conocida de X/Y frente a ORAS:
   utilidades de inventario en vivo (Caramelo Raro, Repelente Máximo y dinero);
2) aplicar tres cambios globales de reglas/UX a todos los juegos soportados.

CAMBIOS GLOBALES — TODOS LOS JUEGOS
------------------------------------

1. SUSTITUTO PARA ASESINO Y MAGO
- Sustituto (movimiento #164) pasa a ser legal para Asesino y Mago.
- Es una excepción de VALIDACIÓN DE ROL.
- NO se añade a ningún pool/categoría de drafteo.
- Si un Asesino o Mago aprende Sustituto por nivel o por MT, RoleRun no debe marcarlo en rojo por el rol.

2. NUEVA PESTAÑA MOVIMIENTOS
- Nueva entrada MOVIMIENTOS en la barra lateral.
- Permite seleccionar cualquiera de los seis roles.
- Buscador incremental por ID, nombre español o nombre inglés.
- Dos paneles independientes:
    MOVIMIENTOS COMPATIBLES
    MOVIMIENTOS INCOMPATIBLES
- La lista se genera únicamente con los movimientos que el motor de guardado valida para el JUEGO ACTUAL.
  No se usa un límite de generación supuesto: SaveEngine consulta el save actual y descarta movimientos dummied/no utilizables.
- El catálogo local contiene los nombres/metadatos; si el juego no aporta una lista validada, la pestaña no inventa una.

3. LAS MT IGNORAN LA COMPATIBILIDAD DE ESPECIE
- RoleRun ya no usa la tabla vanilla "este Pokémon puede/no puede aprender esta MT" para decidir qué MT ofrece.
- Una MT se ofrece si:
    a) existe en el juego actual;
    b) está disponible en la mochila/perfil de MT de la Run;
    c) el movimiento es legal para el ROL del Pokémon.
- La escritura directa de movimiento ya existente tampoco introduce una comprobación de especie.
- Se mantienen las restricciones propias de RoleRun y la protección frente a movimientos que el juego actual no soporta.

X/Y — UTILIDADES EN VIVO
------------------------
Se añade soporte de escritura viva para:

- Caramelo Raro ×999
- Repelente Máximo ×999
- Dinero: 9.999.999

SEGURIDAD DE LA ESCRITURA X/Y
-----------------------------
No se habilita una dirección fija a ciegas.

Mochila:
- usa la estructura completa de bolsa X/Y (0xB88 bytes);
- se calibra contra varios objetos/slots del último main como testigos;
- puede derivar la base desde la mochila MT ya validada o localizarla dinámicamente;
- una candidata solo se acepta si el bloque completo vuelve a coincidir con la huella;
- Caramelo Raro/Repelente modifican un único registro de 4 bytes (item ID + cantidad);
- si el objeto no existe, solo se usa un slot realmente vacío;
- no se reordena el bolsillo.

Dinero:
- usa el bloque Misc del último main como huella estructural;
- Money/Badges/BP se excluyen de la huella porque pueden cambiar durante la sesión;
- se localiza y valida la copia viva antes de tocar Misc+0x08;
- se escriben exactamente 4 bytes para 9.999.999.

En ambos casos:
- la captura debe ser estable;
- se prepara el cambio antes de escribir;
- se relee y verifica después de escribir;
- si la verificación falla, RoleRun intenta restaurar los bytes originales;
- si no puede demostrar la calibración, aborta explícitamente y no escribe ningún byte;
- una utilidad X/Y se procesa de una en una y no se mezcla con cambios de Pokémon.

NO CAMBIA EN ESTA BUILD
-----------------------
- PC/cajas X/Y.
- detección de muertes y flujo de sustitución.
- medallas alpha.16.
- batalla.
- operaciones protegidas que cambian arbitrariamente el tamaño de la party.

PRUEBAS MANUALES RECOMENDADAS
-----------------------------

A) Regla Sustituto
1. Pon Sustituto en un Asesino y en un Mago (por el flujo disponible o haciendo que el juego lo aprenda).
2. Comprueba que no aparece en rojo por incompatibilidad de rol.
3. Abre Drafteos y confirma que NO existe una categoría nueva de Sustituto.

B) Pestaña MOVIMIENTOS
1. Entra en MOVIMIENTOS.
2. Elige Asesino y busca "Sustituto": debe aparecer en COMPATIBLES.
3. Busca un ataque especial de daño: debe aparecer en INCOMPATIBLES para Asesino.
4. Cambia a Mago: un ataque especial válido debe ser compatible y un ataque físico de daño debe ser incompatible.
5. Comprueba que no aparecen movimientos de generaciones posteriores al juego cargado.

C) MT sin compatibilidad de especie
1. Usa un Pokémon que vanilla NO pueda aprender una MT que tengas en la mochila.
2. Asegúrate de que el movimiento sí sea legal para su rol.
3. Abre el selector de MT: la MT debe aparecer.
4. Enséñala y comprueba dentro del juego que el Pokémon recibe exactamente ese movimiento.

D) X/Y — Caramelo Raro ×999
1. Guarda normalmente dentro de Pokémon X/Y antes de la prueba.
2. Deja AzaharPlus + RPC y RoleRun sincronizados; preferiblemente overworld y mochila cerrada.
3. Ejecuta Caramelo Raro ×999 desde RoleRun.
4. Abre la mochila del juego y verifica que la cantidad es 999.

E) X/Y — Repelente Máximo ×999
1. Repite el mismo flujo, de forma independiente.
2. Verifica 999 dentro de la mochila.

F) X/Y — Dinero máximo
1. Guarda normalmente dentro del juego antes de la prueba.
2. Ejecuta dinero máximo desde RoleRun.
3. Verifica en el juego 9.999.999.

IMPORTANTE: prueba D, E y F DE UNA EN UNA.
Si aparece "MOCHILA SIN CALIBRAR", "DINERO SIN CALIBRAR" o un error de validación, no cambies configuraciones ni pruebes offsets. Ese error significa que RoleRun no ha podido demostrar con seguridad la copia viva. Conserva el mensaje/log para diagnosticarlo.

SMOKE TEST FINAL
----------------
Tras las utilidades, comprobar que siguen funcionando:
- lectura de equipo;
- cambio de rol;
- sacar/dejar Pokémon del PC;
- muerte + ventana ELIGE AL SUSTITUTO DE;
- contador actual de medallas.
