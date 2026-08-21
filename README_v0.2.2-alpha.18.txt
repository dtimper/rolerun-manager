RoleRun Manager v0.2.2-alpha.18 — Pokémon Sol/Luna · MT LIVE + UI RESPONSIVA

OBJETIVOS DE ESTA BUILD
=======================
Corregir dos fallos demostrados de alpha.17:

1) Equipo podía bloquear la interfaz 30–60 s.
   Causa real: el render pasivo calculaba si cada SUSTITUIR tenía una MT válida
   llamando a read_tm_inventory(), que a su vez podía recorrer el backing FCRAM.
   Ese trabajo pesado se estaba ejecutando en el hilo principal de Tk.

2) Una MT seleccionada aparecía en RoleRun pero no en Pokémon Sol/Luna.
   Causa real: la cola de auto-aplicación de SM omitía PendingTMTeach, aunque el
   writer SMLiveWriter sí soportaba y verificaba PendingTMTeach.

CAMBIOS
=======
- El render de Equipo en Sol/Luna no lee ni escanea nunca la mochila viva.
- SUSTITUIR puede abrir el selector; la compatibilidad/inventario se demuestra
  únicamente cuando el usuario solicita explícitamente MT.
- La calibración de mochila SM se ejecuta en un thread de trabajo. Windows/Tk
  permanece respondiendo mientras la validación continúa.
- Eliminada una lectura PKHeX de inventario redundante antes de la lectura SM.
- La primera calibración demostrada se reutiliza dentro de la misma sesión solo
  tras releer host + guest y exigir igualdad byte a byte. Si falla, se descarta
  y vuelve al escaneo completo seguro.
- La clave de sesión incluye Title ID, process_id guest, nombre del proceso y
  party_base; además la caché conserva el PID host demostrado.
- PendingTMTeach ya entra en la cola automática de escritura live de Sol/Luna.
- El writer sigue comprobando que la MT exista en la mochila viva justo antes de
  escribir el PK7, y mantiene verificación/rollback.
- Monitor y auto-aplicación no compiten con la calibración de mochila SM.

SEGURIDAD
=========
No se añade ninguna dirección RAM supuesta. El camino rápido solo reutiliza una
ubicación que ya fue demostrada end-to-end en esa misma sesión y vuelve a leer
host + guest antes de aceptarla. Si la sesión o el proceso cambian, se invalida.

PRUEBAS RECOMENDADAS
====================
1. Abrir Equipo: debe aparecer sin el bloqueo de 30–60 s.
2. Pulsar el logo de la barra flotante: la ventana debe volver sin esperar al
   escaneo de mochila.
3. Pulsar + por primera vez: puede aparecer el estado "validando mochila de MT
   en segundo plano", pero la ventana debe seguir respondiendo.
4. Enseñar una MT (por ejemplo Avivar): esperar el aviso de escritura aplicada y
   comprobar EN EL JUEGO que el movimiento cambió.
5. Abrir otro + en la misma sesión: debe reutilizar la calibración demostrada y
   ser mucho más rápido.
6. Guardar en Pokémon Sol/Luna, reiniciar emulación y comprobar persistencia.
