# RoleRun Manager

Compañero de escritorio para jugar una **RoleRun**: una partida Pokémon por
equipos donde cada Pokémon tiene asignado un rol (ofensivo, soporte, curador...)
y pierde su sitio en el equipo si es derrotado. RoleRun Manager lee la partida
en tiempo real desde el emulador, calcula el drafteo por roles, vigila el
guardado y refleja el estado de la Run en pantalla (incluida una capa lista
para OBS).

> Proyecto en desarrollo activo — funciona, pero puede cambiar de una versión
> a otra. El historial completo de cambios está en
> [CHANGELOG.md](CHANGELOG.md).

## Juegos soportados

Negro/Blanco · Negro 2/Blanco 2 · X/Y · Rubí Omega/Zafiro Alfa · Sol/Luna ·
Ultrasol/Ultraluna · Diamante Brillante/Perla Reluciente

Cada juego se lee en vivo desde el emulador correspondiente (melonDS para
DS, Azahar para 3DS o Ryujinx para Switch, según el título) — no hace falta
cerrar la partida para consultar el estado.

Diamante/Perla, Platino y HeartGold/SoulSilver tienen motor propio en el
código pero están ocultos del selector por ahora, a la espera de estabilizar
la detección de combate en tiempo real (ver [CHANGELOG.md](CHANGELOG.md)).

## Instalar

La forma normal es la **[página de RoleRun](https://dtimper.github.io/rolerun-manager/)**,
que explica el formato a fondo y tiene el botón de descarga. También puedes
bajar el instalador directamente desde [Releases](../../releases/latest):

1. Descarga **RoleRunManager-Setup.exe** y ábrelo.
2. Si Windows avisa de que «protegió su PC», pulsa «Más información» y luego
   «Ejecutar de todas formas»: el programa no tiene firma digital de pago.
3. Sigue los pasos. No hace falta instalar nada más: Python y .NET van dentro.

Después, abre tu emulador con la partida cargada y elige tu juego en RoleRun
Manager.

## Actualizaciones

Al abrir el programa, comprueba en segundo plano si hay una versión más
nueva y avisa con sus novedades y un botón que baja el instalador. No se
autoactualiza ni descarga nada sin que lo pidas. El instalador nuevo se
instala encima del anterior, y tus Runs no se tocan: se guardan aparte, en
`Documentos\RoleRun Manager`.

## Ejecutar desde el código

Para desarrollar: clona el repositorio y usa `instalar_y_abrir.bat` la
primera vez (necesita Python 3 y el SDK de .NET 10 para compilar el motor) y
`abrir_rolerun.bat` después. `tools/construir_instalador.py` fabrica el
instalador y `tools/probar_instalador.py` lo prueba como en un ordenador sin
Python ni .NET; al subir una etiqueta `vX.Y.Z`, GitHub hace las dos cosas y
publica la versión solo (`.github/workflows/publicar.yml`).

## Más documentación

- [CHANGELOG.md](CHANGELOG.md) — historial de versiones
- [ROADMAP.md](ROADMAP.md) — qué viene después
- [AGENTS.md](AGENTS.md) — normas de desarrollo del proyecto (para quien
  quiera tocar código: cómo se exige evidencia para cada cambio)
