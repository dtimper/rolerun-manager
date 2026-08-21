RoleRun Manager 1.13.0-alpha.9
================================

CALIBRACIÓN SEGURA DEL PC PARA ORAS
-----------------------------------
La alpha.8 seguía sin poder leer la primera casilla de PC de esta instalación
de Azahar/ROM. En lugar de probar otra dirección fija, esta alpha localiza la
matriz viva de cajas en la RAM antes de aplicar el primer cambio de rol.

Para aceptar una ubicación no basta con encontrar al Pokémon elegido: RoleRun
comprueba también Pokémon adicionales de esa misma caja en sus posiciones
contiguas. Si no encuentra esa coincidencia completa, cancela la operación sin
escribir ningún byte.

PRUEBA
------
1. Inicia ORAS y pulsa F5 en RoleRun.
2. En Cajas PC, cambia el rol de B-Boy o de otro Pokémon de una caja con al
   menos dos Pokémon.
3. La primera vez puede tardar un instante adicional mientras calibra la caja.
   Después se conserva para el resto de la sesión.
4. Abre la caja dentro del juego y confirma que aparece la marca nueva.

El cambio sigue siendo solo de RAM: guardar o cargar estado dentro de Azahar
sigue siendo decisión del jugador. La barra flotante y OBS reciben únicamente
la actualización final confirmada.
