RoleRun Manager v0.2.2-alpha.110

- Corrige la carrera de inicio que impedía publicar en la ficha los stats, IV,
  EV y naturaleza de Pokémon almacenados en el PC de BDSP.
- La lectura viva completa se inicia al quedar validada la conexión con Ryujinx
  y actualiza la vista unificada Equipo y PC.
- Permite asignar letras simples como atajos sin bloquear su escritura fuera de
  RoleRun/Ryujinx: Windows las registra solo mientras una ventana autorizada
  mantiene el foco.

Validación real: Ornita (caja 1, posición 8) muestra naturaleza Huraña, stats
44/31/21/19/18/30, IV 23/13/29/17/8/8 y EV 0.

Baseline: 705 tests superados con `python -m pytest -q`.
