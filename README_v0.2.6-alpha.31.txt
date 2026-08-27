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

No tienes que escribir ningún comando. He dejado un archivo para hacer doble
clic, en la misma carpeta que abrir_rolerun.bat:

    capturar_baja_b2w2.bat

La herramienta SOLO LEE. No escribe nada en tu partida ni activa ninguna función.

1. Abre melonDS con tu partida de Negro 2 y déjalo en el mapa.
2. CIERRA RoleRun Manager, para que no interfiera.
3. Doble clic en  capturar_baja_b2w2.bat
4. Se abre una ventana negra que te recuerda los dos puntos de arriba: pulsa
   una tecla.
5. Te dirá cuántos Pokémon ve en tu equipo. Pulsa INTRO.
6. Entra en un combate.
7. Deja que uno de tus Pokémon se debilite.
8. Termina el combate y vuelve al mapa.
9. A los 3 minutos se para sola y te dice dónde ha guardado el archivo.
10. Avísame cuando esté.

El archivo se guarda en:

    diagnostics\manual\b2w2_battle_faint_latest.json

Con eso sabré exactamente cuál de las dos explicaciones es, y podré arreglarlo
sin tocar nada a ciegas.

Si la ventana negra se cierra sola o sale un error, hazle una foto o copia el
texto y mándamelo.
