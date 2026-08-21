RoleRun Manager 1.13.0-alpha.36

Objetivo de esta alpha
----------------------
1. Reparar el flujo de enseñar/borrar movimientos en ORAS sin depender de la calibración de mochila.
2. Evitar que un fallo de escritura automática deje cambios fantasma y rompa la sincronización posterior.
3. Reforzar la detección automática de medallas cuando el `main` está desfasado respecto a la sesión viva.

Cambios principales
-------------------
- MTs de ORAS: escritura directa y verificada sobre el PK6; no se lee ni escribe la mochila al aplicar.
- Selector de MTs: usa el bolsillo vivo de Azahar cuando puede y el guardado como respaldo.
- Un cambio automático fallido se elimina de la cola/proyección y RoleRun vuelve a leer Azahar inmediatamente.
- Ya no aparece el bloqueo genérico de “acciones que requieren flujo manual” por tener una cola mixta no relacionada.
- Medallas: Misc se localiza por huella + Money/BP runtime; el contador del `main` no se usa como condición para aceptar la copia viva.
- MEDALLAS sigue siendo automático y sin botones +/-.
- Caja 4 sigue siendo Cementerio.
- La mecánica de muerte conserva el delay visual de 1 segundo.

Persistencia
------------
RoleRun escribe cambios compatibles en la RAM de Azahar. Para conservarlos tras cerrar el emulador, guarda normalmente dentro de Pokémon.
