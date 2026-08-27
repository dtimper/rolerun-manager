RoleRun Manager v0.2.2-alpha.111

- Todos los atajos de teclado se activan exclusivamente cuando un emulador
  compatible está en primer plano.
- Las letras asignadas, como D, siguen disponibles para buscar y escribir en
  RoleRun y en cualquier otra aplicación.
- Una segunda comprobación en el momento de ejecutar evita que un evento de
  teclado encolado produzca una acción después de abandonar el juego.

Validación Win32 real: D y NUM 7 libres en RoleRun, reservadas en Ryujinx y
libres de nuevo al regresar a RoleRun.

Baseline: 705 tests superados con `python -m pytest -q`.
