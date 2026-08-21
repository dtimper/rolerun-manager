RoleRun Manager v0.2.2-alpha.15

Objetivo principal de esta build:
- Resolver el fallo seguro de Dinero máximo en Pokémon Sol/Luna sin introducir ninguna dirección RAM supuesta.
- Mantener intactos los readers/writers ya validados de party, roles y movimientos.

CAMBIO DE DINERO SOL/LUNA:
- Alpha.14 exigía que los 0x200 bytes completos del bloque Misc vivo fueran idénticos al último main.
- Eso podía fallar si campos runtime ajenos a Money cambiaban después de guardar.
- Alpha.15 conserva primero la búsqueda exacta de alpha.14.
- Si no existe una copia exacta, Money usa un fallback estructural: selecciona múltiples fragmentos exactos e informativos del Misc del mismo main, excluyendo los 4 bytes de Money, y los busca únicamente dentro de la misma región RW host que ya contiene la party FCRAM demostrada.
- Una candidatura solo se acepta si hay evidencia exacta distribuida suficiente, aparece una única estructura válida y los 0x200 bytes leídos por host y por RPC guest son idénticos en ese instante.
- No se deriva ninguna dirección desde offsets de X/Y u ORAS ni desde la posición del bloque dentro del save.
- Una vez demostrada la estructura, el saldo vivo puede ser distinto al del último guardado (por compras/ventas), pero debe ser un uint32 válido <= 9.999.999.
- Solo se escriben los 4 bytes de Money, con relectura host + guest y rollback.
- Si aparecen cero o varias estructuras suficientemente demostradas, NO se escribe.
- Alpha.15 genera además Documentos\RoleRun Manager\Logs\sm_utility_diagnostic_latest.json con la evidencia del intento estructural.

VALIDAR EN ESTE ORDEN:
1. Abre Pokémon Sol y quédate en el overworld.
2. Pulsa F5 en RoleRun y espera a que el equipo esté sincronizado.
3. Pulsa Dinero máximo.
4. Comprueba dentro del juego que el saldo sea exactamente 9.999.999.
5. Haz una compra pequeña y confirma que el juego descuenta dinero normalmente desde 9.999.999.
6. Guarda dentro del juego, reinicia la emulación y confirma que el dinero persiste.

SI DINERO TODAVÍA FALLA:
- NO sigas reintentando muchas veces.
- Envíame este archivo:
  Documentos\RoleRun Manager\Logs\sm_utility_diagnostic_latest.json
- Esa captura indica qué fragmentos del Misc se encontraron, cuántos bytes coinciden, cuántas zonas del bloque quedaron demostradas y por qué cada candidatura fue aceptada o rechazada.

PRUEBAS PENDIENTES PARA CERRAR MOVIMIENTOS RoleRun -> JUEGO:
7. Sustituye un ataque mediante Drafteo y comprueba el movimiento dentro del juego.
8. Elimina un ataque intermedio y comprueba que los movimientos posteriores se compacten sin huecos.
9. Guarda dentro del juego, reinicia la emulación y confirma que el movimiento escrito desde RoleRun persiste.

BARRA FLOTANTE:
10. Pulsa el logo de RoleRun desde la barra flotante y confirma que la ventana principal reaparece maximizada.

REGRESIÓN RÁPIDA:
11. Cambia un rol RoleRun -> juego.
12. Cambia un marcador juego -> RoleRun.
13. Comprueba que Caramelo Raro x999 y Repelente Máximo x999 siguen funcionando.

TODAVÍA BLOQUEADO EN SOL/LUNA:
- MT mediante +
- PC / Equipo <-> PC
- muertes / sustituciones / Cementerio
- progreso equivalente a medallas

PRUEBAS AUTOMATIZADAS EN EL ENTORNO DE DESARROLLO:
- Sol/Luna live: 31/31.
- Suite no-UI (realtime core, ORAS, X/Y y resto de módulos que no importan CustomTkinter): 218/218.
- 106 archivos Python compilan correctamente.
- Los tests UI no se pudieron ejecutar en este entorno porque CustomTkinter no está instalado y el entorno no dispone de red para descargarlo.
