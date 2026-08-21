RoleRun Manager 1.13.0-alpha.5
================================

RECONCILIACIÓN SEGURA DESPUÉS DE REINICIAR AZAHAR
-------------------------------------------------
Esta alpha corrige una diferencia posible entre Azahar y RoleRun Manager:
si RoleRun aplicaba un rol o movimiento directamente en la RAM, y después
reiniciabas Azahar o cargabas un estado sin guardar, el juego volvía al equipo
anterior pero RoleRun podía seguir mostrando la instantánea viva nueva.

Ahora RoleRun no guarda por ti. Después de una escritura viva confirmada,
comprueba discretamente el equipo de Azahar mientras ese cambio no haya llegado
a main. Si Azahar vuelve a un estado distinto, RoleRun sustituye su copia viva
por la captura real y muestra el aviso `ESTADO DE ORAS RECUPERADO`.

LO QUE HACE
------------
- Detecta cambios de identidad del equipo, roles y movimientos después de una
  escritura viva de RoleRun.
- Actualiza aplicación, OBS y barra flotante desde el equipo que Azahar tiene
  realmente abierto.
- Mantiene protegidos los cambios que aún estés preparando en RoleRun: no los
  sustituye con una lectura automática.
- Si guardas normalmente dentro del juego, el vigilante de main consolida esa
  versión y deja de vigilar la escritura de RAM anterior.

LO QUE NO HACE
--------------
- No pulsa Guardar dentro del juego.
- No modifica main, estados, historia, ubicación, nivel, dinero ni inventario.
- No reacciona a PS, nivel u otros cambios normales de combate; por eso no
  refresca ni produce flicker mientras juegas.
- No escribe ningún byte cuando detecta que has vuelto a un estado anterior.

PRUEBA RECOMENDADA
------------------
1. Pulsa F5 en ORAS y verifica el aviso verde de sincronización.
2. Cambia un rol o un movimiento desde RoleRun y pulsa GUARDAR CAMBIOS.
3. Comprueba que Azahar muestra el cambio. No guardes dentro del juego.
4. Reinicia Azahar o carga un estado anterior.
5. Cuando el juego haya terminado de abrir, espera unos segundos. RoleRun debe
   recuperar el rol/movimiento anterior automáticamente, sin pulsar F5 y sin
   escribir nada. OBS y la barra deben reflejar el mismo equipo.

F5 sigue disponible como comprobación manual inmediata. Si el emulador está
cerrado o arrancando, RoleRun espera en silencio y vuelve a comprobarlo cuando
Azahar vuelva a responder.

La barra flotante conserva el mecanismo anti-flicker de 1.12: la corrección se
publica una sola vez y el aviso es una superposición temporal, sin reabrir la
ventana principal.
