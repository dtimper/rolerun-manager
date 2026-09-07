# RoleRun Manager

Compañero de escritorio para jugar una **RoleRun**: una partida Pokémon por
equipos donde cada Pokémon tiene asignado un rol (ofensivo, soporte, curador...)
y pierde su sitio en el equipo si es derrotado. RoleRun Manager lee la partida
en tiempo real desde el emulador, calcula el drafteo por roles, vigila el
guardado y refleja el estado de la Run en pantalla (incluida una capa lista
para OBS).

> Proyecto en desarrollo activo. La versión actual está en fase alpha — se
> puede jugar, pero puede cambiar de una sesión a otra. El historial completo
> de cambios está en [CHANGELOG.md](CHANGELOG.md).

## Juegos soportados

Diamante/Perla · Platino · HeartGold/SoulSilver · Negro/Blanco · Negro 2/Blanco 2
· X/Y · Rubí Omega/Zafiro Alfa · Sol/Luna · Ultrasol/Ultraluna · Diamante
Brillante/Perla Reluciente

Cada juego se lee en vivo desde el emulador correspondiente (Azahar/Citra para
3DS, o Ryujinx para Switch, según el título) — no hace falta cerrar la partida
para consultar el estado.

## Primeros pasos

1. Descarga o clona este repositorio.
2. Haz doble clic en `instalar_y_abrir.bat` la primera vez (instala las
   dependencias de Python automáticamente). En los siguientes usos, basta con
   `abrir_rolerun.bat`.
3. Abre tu emulador con la partida cargada y selecciona el archivo de
   guardado desde RoleRun Manager.

Requiere Python 3 instalado en Windows.

## Actualizaciones

Al abrir el programa, comprueba en segundo plano si hay una versión más
nueva publicada en la pestaña [Releases](../../releases) de este repositorio
y avisa con un enlace de descarga — no se autoactualiza ni descarga nada sin
que lo pidas.

## Más documentación

- [CHANGELOG.md](CHANGELOG.md) — historial de versiones
- [ROADMAP.md](ROADMAP.md) — qué viene después
- [AGENTS.md](AGENTS.md) — normas de desarrollo del proyecto (para quien
  quiera tocar código: cómo se exige evidencia para cada cambio)
