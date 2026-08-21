RoleRun Manager 1.13.0-alpha.2
================================

CORRECCIÓN DE ESTA ALPHA
------------------------
La alpha.1 podía leer el área equivocada de RAM en ORAS y mostrar "el equipo
no contiene ningún Pokémon" aun cuando Azahar respondía correctamente. Esta
alpha usa la dirección y la distribución real de los slots de equipo de ORAS.
No cambia el alcance de seguridad: continúa siendo estrictamente de lectura.

OBJETIVO DE ESTA PRIMERA PRUEBA
-------------------------------
Comprobar en una partida real de Omega Rubí / Zafiro Alfa que RoleRun puede
leer el equipo actual directamente desde Azahar, sin guardar, cerrar ni
reiniciar el juego y sin escribir ningún byte en la memoria del emulador.

PREPARACIÓN EN AZAHAR
---------------------
1. Abre ORAS en Azahar y carga tu partida con normalidad.
2. En la configuración de Azahar, activa el servidor RPC.
3. Abre en RoleRun el archivo main correspondiente a esa misma partida.
4. Mantén RoleRun abierto. F5 queda reservado como atajo global de RoleRun
   mientras la Run esté activa (Azahar no recibirá su acción habitual de F5).

PRUEBA RECOMENDADA
------------------
1. Colócate fuera de un combate y pulsa F5.
2. RoleRun leerá dos veces los seis slots del equipo.
3. Solo aceptará el resultado si ambas lecturas son idénticas y todos los
   Pokémon superan checksum, especie y nivel PK6.
4. Tras validarlo, Equipo, Dashboard, OBS y barra flotante recibirán una única
   actualización. El archivo main, el juego y los estados no se modifican.
5. Gana un nivel o captura/cambia un Pokémon en el juego y vuelve a pulsar F5.

También puedes ejecutar la prueba desde Ajustes > Azahar · ORAS en vivo.

LÍMITES INTENCIONADOS DE ESTA ALPHA
-----------------------------------
- Solo Omega Rubí / Zafiro Alfa en Azahar.
- Perfil de memoria inicial: ORAS revisión 1.4 (`sango-1` / `sango-2`).
- Sincroniza el equipo; el PC en vivo se incorporará después de validar esta base.
- Si RoleRun tiene cambios pendientes, F5 no los descarta: se detiene y pide
  guardarlos o descartarlos primero.
- Los Pokémon que ya estaban en RoleRun conservan sus etiquetas localizadas de
  especie, objeto y habilidad. Un Pokémon nuevo puede mostrar objeto/habilidad
  mediante su número interno durante esta prueba.
- No aplica roles, movimientos ni traslados al juego. Esa escritura se añadirá
  únicamente después de comprobar esta lectura con una partida real.

SI FALLA
--------
- "Azahar no responde por RPC": comprueba que el servidor RPC esté activado.
- "No aparece Omega Rubí/Zafiro Alfa": asegúrate de que el juego está arrancado,
  no solo visible en la lista de Azahar.
- "No superó checksum/especie/nivel": no insistas ni cambies archivos. La ROM,
  región o revisión puede necesitar otro perfil de memoria. Envía el texto exacto
  del aviso y la edición/región/actualización del juego.
- "El equipo cambió durante todas las lecturas": sal de la animación o combate y
  pulsa F5 de nuevo.

SEGURIDAD
---------
El cliente RPC incluido en esta alpha solo implementa consultas de procesos y
lectura de memoria. No contiene una función de escritura. Tampoco toca archivos
.cst ni fuerza un guardado del juego.
