RoleRun Manager 1.13.0-alpha.11
=================================

CALIBRACIÓN SEGURA DEL INVENTARIO ORAS
--------------------------------------
La alpha.10 mostraba que Caramelo Raro ya estaba presente porque una dirección
fija podía apuntar a una copia secundaria de la mochila en RAM. Esta alpha no
escribe con una dirección conocida por aproximación.

RoleRun toma varias posiciones de objetos del último guardado, busca la
mochila activa de Azahar y exige una coincidencia única. También comprueba los
objetos que no existían: una copia antigua con Caramelo Raro x999 ya no puede
confundirse con la mochila real.

PRIMERA PRUEBA
--------------
1. Sustituye la carpeta anterior por esta alpha y abre abrir_rolerun.bat.
   La primera apertura recompilará el motor automáticamente; espera a que
   termine antes de abrir la Run.
2. Dentro de ORAS, fuera de combate o menús, guarda la partida normalmente una
   vez. Esto da a RoleRun una referencia segura de tu mochila actual.
3. Pulsa F5 en RoleRun.
4. Pulsa solo Caramelo Raro x999 y abre la mochila dentro del juego para
   comprobarlo.

Si RoleRun no localiza una mochila única, no escribirá nada. Guarda la partida
normalmente, pulsa F5 y vuelve a probar; si persiste, envía la captura exacta
del aviso antes de intentar Repelente, dinero o MTs.

Los cambios que sí se confirmen siguen siendo solo de RAM: el archivo main,
la historia y la ubicación no se modifican hasta que tú guardes desde el juego.
