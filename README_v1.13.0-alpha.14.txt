RoleRun Manager 1.13.0-alpha.14

ARCHIVOS PERSISTENTES POR JUEGO
===============================

Cada juego recuerda ahora dos archivos locales:

1. La partida guardada.
2. El archivo del juego: ROM .cxi/.3ds/.app en 3DS, .nds en DS o .nsp/.xci en
   Switch, según corresponda.

La aplicación guarda solo las rutas, nunca copia el contenido de tus ROMs ni
de tus partidas. Esa configuración sigue ahí aunque cierres RoleRun Manager.

USO
===

1. En "SELECCIONA TU JUEGO", pulsa CONFIGURAR la primera vez.
2. Elige primero el guardado y después el archivo del juego.
3. La tarjeta pasará a mostrar los dos nombres y el botón ABRIR.
4. A partir de entonces, pulsa ABRIR: RoleRun carga la partida directamente.

CAMBIAR DE RUN
==============

Cada tarjeta tiene el botón ARCHIVOS. También aparece "CAMBIAR ARCHIVOS" en
Configuración. Al sustituir ambos archivos, RoleRun pregunta si se trata de
una Run nueva:

- SÍ: conserva la Run anterior y crea otra limpia, incluso si usas el mismo
  entrenador y el mismo juego.
- NO: actualiza las rutas de la misma Run, útil si solo moviste los archivos.

ORAS / AZAHAR
=============

Para Zafiro Alfa u Omega Rubí, configura una vez el archivo main y la ROM
.cxi/.3ds/.app que abres en Azahar. Tras F5, al pulsar + en un hueco de ataque,
RoleRun usará esa ROM para leer las MT y compatibilidades reales sin pedirla de
nuevo ni requerir el log del randomizer.

Si algún archivo se mueve o se borra, RoleRun no hace suposiciones: marcará la
tarjeta en rojo y te pedirá reasignarlo desde ARCHIVOS.
