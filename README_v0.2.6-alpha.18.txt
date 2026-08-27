RoleRun Manager v0.2.6-alpha.18 — RoleRun deja de gastar CPU en balde

Primera mejora de rendimiento de la nueva fase, y está medida, no supuesta.

RoleRun comprueba si tienes Ryujinx abierto para poder usar el mando. Esa
comprobación repasa TODOS los procesos abiertos de Windows, y se estaba haciendo
60 veces por segundo, sin parar, desde que se abre el programa.

Cuando Ryujinx no está abierto —es decir, en todos los juegos menos Perla
Reluciente— eso significaba gastar el 14 % de un núcleo del procesador de forma
permanente, y además en el mismo hilo que dibuja la interfaz. Es decir: parte de
la lentitud y de los tirones venía de RoleRun buscando algo que no estaba.

Ahora esa comprobación se hace como mucho una vez cada 2 segundos.

Si abres Ryujinx con RoleRun ya arrancado, el mando se sigue detectando; solo
tarda un par de segundos en darse cuenta.

QUÉ DEBES PROBAR AHORA

1. Abre RoleRun con cualquier juego que NO sea Perla Reluciente y déjalo un rato
   abierto. Debería notarse algo más fluido, sobre todo al navegar.
2. Si usas mando con Perla Reluciente: abre Ryujinx, abre RoleRun y comprueba
   que el mando responde con normalidad.
3. Prueba también a abrir Ryujinx DESPUÉS de RoleRun y confirma que el mando
   acaba funcionando igual (puede tardar un par de segundos).

Y sigue pendiente lo más importante: la prueba de retirar un Pokémon del PC al
equipo en Negro 2, explicada en README_v0.2.6-alpha.16.txt.
