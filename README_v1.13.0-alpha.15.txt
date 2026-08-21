RoleRun Manager 1.13.0-alpha.15

SUSTITUCIÓN EQUIPO ↔ PC EN ORAS
================================

Después de sincronizar Zafiro Alfa/Omega Rubí con F5, CAMBIAR CON PC aplica
ahora la sustitución uno por uno directamente en Azahar. No hace falta pulsar
GUARDAR CAMBIOS.

RoleRun comprueba los dos Pokémon por su identidad PK6 y escribe como una sola
operación protegida:

1. El Pokémon del PC en el hueco elegido del equipo.
2. Su bloque nuevo de nivel, PS y estadísticas de combate.
3. El Pokémon saliente en la casilla del PC que quedó libre.

Si cualquiera de los tres bloques no se confirma, RoleRun restaura todos los
bytes originales. El archivo main no se modifica.

ROMS RANDOMIZADAS
=================

El bloque de estadísticas se calcula con la experiencia, IV, EV y naturaleza
del Pokémon. Las estadísticas base y la curva de crecimiento se leen del
archivo .cxi/.3ds/.app que ya configuraste para ORAS, incluida su capa activa
de Azahar. Por eso no se usa una tabla genérica ni se heredan los PS o las
estadísticas del Pokémon que salió.

PRUEBA RECOMENDADA
==================

1. Abre Azahar y RoleRun Manager 1.13.0-alpha.15.
2. Pulsa F5 y espera la confirmación verde de ORAS.
3. En EQUIPO, pulsa CAMBIAR CON PC y elige un Pokémon.
4. Comprueba inmediatamente el equipo dentro del juego y después la casilla
   correspondiente del PC. No pulses GUARDAR CAMBIOS.

El cambio solo vive en RAM hasta que guardes desde el menú del juego. Si haces
Reset o cargas un estado anterior, RoleRun volverá a mostrar el estado real.

ALCANCE ACTUAL
==============

Esta versión habilita la sustitución uno por uno, que mantiene el mismo número
de miembros. ENVIAR AL PC o añadir un miembro a un equipo con huecos todavía
requiere el flujo normal: la dirección del contador/compactación de party no se
escribe hasta validarla con la misma seguridad.
