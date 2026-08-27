RoleRun Manager v0.2.6-alpha.31 — necesito una traza tuya

La sustitución ya funciona. Con eso, el ciclo de bajas está entero salvo UNA
cosa: que durante el combate no se actualiza nada, y todo aparece al terminarlo.

POR QUÉ NO LO ARREGLO DIRECTAMENTE

Tengo dos explicaciones posibles y ninguna demostrada:

  A) Que Negro 2 no actualice la ficha del equipo hasta que acaba el combate.
     Durante la pelea el juego trabaja con una copia aparte, y RoleRun mira la
     ficha del equipo para detectar bajas. Si el juego no la toca hasta el
     final, la baja no se puede ver antes.

  B) Que RoleRun sí tenga los datos del combate, pero los descarte justo en el
     momento de morir. RoleRun solo tiene demostrados dos valores del "estado"
     de un Pokémon en combate, y si aparece otro (por ejemplo uno propio de
     estar debilitado) rechaza la lectura entera por seguridad.

Podría probar a ciegas, pero es tu partida. Prefiero medirlo.

QUÉ NECESITO QUE HAGAS

He preparado una herramienta que SOLO LEE. No escribe nada en tu partida y no
activa ninguna función.

1. Abre melonDS con tu partida de Negro 2 y déjalo en el mapa.
2. CIERRA RoleRun (para que no interfiera).
3. Abre una ventana de comandos en la carpeta de RoleRun y ejecuta:

       py -3 tools_b2w2_battle_faint_capture.py

4. Te dirá cuántos Pokémon ve en tu equipo. Pulsa INTRO.
5. Entra en un combate.
6. Deja que uno de tus Pokémon se debilite.
7. Termina el combate y vuelve al mapa.
8. La herramienta se para sola a los 3 minutos y te dirá dónde guardó el
   archivo.
9. Avísame cuando esté.

El archivo se guarda en:

    diagnostics\manual\b2w2_battle_faint_latest.json

Con eso sabré exactamente cuál de las dos explicaciones es, y podré arreglarlo
sin tocar nada a ciegas.

Si te da algún error al ejecutarla, mándame el mensaje y lo corrijo.
